"""OpenAI Codex CLI 适配器。

非交互：`codex exec`（https://developers.openai.com/codex/noninteractive）
交互：`codex` + 初始 prompt。

Prompt 写入 docs/<需求>/temp-prompts/ 后只把短指令放进 argv，避免 Windows 命令行超限。
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path

from .base import AITool, AIToolResult, CompletionCheck
from .interactive_runner import run_interactive_subprocess
from .prompt_file import launch_read_prompt, save_node_prompt

logger = logging.getLogger(__name__)

_EXTRA_BIN_DIRS = (Path.home() / ".local" / "bin", Path.home() / ".npm-global" / "bin")


class CodexTool(AITool):
    name = "codex"

    def run(
        self,
        prompt: str,
        cwd: str,
        *,
        node_id: str | None = None,
        prompt_dir: str | None = None,
        model: str | None = None,
    ) -> AIToolResult:
        prompt_file = save_node_prompt(
            prompt, cwd, node_id=node_id, prompt_dir=prompt_dir
        )
        launch = launch_read_prompt(prompt_file)
        binary = self._resolve_binary()
        if not binary:
            return AIToolResult(
                content=self._fallback_content(prompt),
                tool_name=self.name,
                success=False,
                message=f"Codex CLI 不可用，prompt 已保存至 {prompt_file}",
            )

        cmd = [
            binary,
            "exec",
            "--sandbox",
            "workspace-write",
            "--skip-git-repo-check",
            *self.model_cli_flags(model),
            launch,
        ]
        try:
            logger.info(
                "调用 Codex CLI (headless): %s model=%s",
                binary,
                model or "(default)",
            )
            proc = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=600,
                check=False,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                return AIToolResult(
                    content=proc.stdout.strip(),
                    tool_name=self.name,
                    success=True,
                )
            if proc.stderr:
                logger.warning("Codex CLI stderr: %s", proc.stderr[:500])
            return AIToolResult(
                content=self._fallback_content(prompt),
                tool_name=self.name,
                success=False,
                message=(proc.stderr or "").strip()
                or f"Codex CLI 退出码 {proc.returncode}",
            )
        except subprocess.TimeoutExpired:
            return AIToolResult(
                content="",
                tool_name=self.name,
                success=False,
                message="Codex CLI 执行超时",
            )

    def run_interactive(
        self,
        prompt: str,
        cwd: str,
        *,
        completion_check: CompletionCheck | None = None,
        node_id: str | None = None,
        prompt_dir: str | None = None,
        model: str | None = None,
    ) -> AIToolResult:
        prompt_file = save_node_prompt(
            prompt, cwd, node_id=node_id, prompt_dir=prompt_dir
        )
        launch = launch_read_prompt(prompt_file)
        binary = self._resolve_binary()
        if not binary:
            return AIToolResult(
                content="",
                tool_name=self.name,
                success=False,
                message=f"Codex CLI 不可用，prompt 已保存至 {prompt_file}",
            )

        cmd = [binary, *self.model_cli_flags(model), launch]
        try:
            logger.info(
                "交互调用 Codex CLI: %s model=%s",
                binary,
                model or "(default)",
            )
            return run_interactive_subprocess(
                cmd,
                cwd,
                tool_name=self.name,
                banner_title="进入 Codex 交互会话",
                completion_hint="产出文件写入后将自动退出并继续 workflow",
                completion_check=completion_check,
            )
        except FileNotFoundError:
            return AIToolResult(
                content="",
                tool_name=self.name,
                success=False,
                message=f"Codex CLI 不可用，prompt 已保存至 {prompt_file}",
            )

    @staticmethod
    def _resolve_binary() -> str | None:
        search_path = os.environ.get("PATH", "")
        for extra in _EXTRA_BIN_DIRS:
            if extra.is_dir():
                search_path = f"{extra}{os.pathsep}{search_path}"
        return shutil.which("codex", path=search_path)

    @staticmethod
    def _fallback_content(prompt: str) -> str:
        return (
            "# Codex 工具未就绪\n\n"
            "> 请安装 OpenAI Codex CLI 并完成登录后重试，或手动执行以下 prompt。\n\n"
            "---\n\n"
            f"{prompt}"
        )
