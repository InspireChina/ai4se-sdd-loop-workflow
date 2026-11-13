"""OpenAI Codex CLI 适配器。

与 Claude / omp / Cursor 同一套路：长 prompt 落盘，argv 只传短「去读该文件」指令。
差异仅两处：
1. 启动指令必须是**单行**（Windows 转发多行 argv 时常只剩第一行，路径会丢）
2. 放大权限并 ``-C`` 到含 prompt 的仓库根，保证能读到业务仓文件

文档：https://developers.openai.com/codex/noninteractive
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path

from .base import AITool, AIToolResult, CompletionCheck
from .interactive_runner import run_interactive_subprocess
from .prompt_file import TEMP_PROMPT_DIR, save_node_prompt

logger = logging.getLogger(__name__)

_EXTRA_BIN_DIRS = (Path.home() / ".local" / "bin", Path.home() / ".npm-global" / "bin")
_EXEC_SANDBOX_FLAGS = ("--sandbox", "danger-full-access")
_INTERACTIVE_BYPASS_FLAGS = ("--dangerously-bypass-approvals-and-sandbox",)


def _launch_read_prompt_oneline(prompt_file: Path) -> str:
    """与 launch_read_prompt 同义，但禁止换行，避免 Windows 子进程丢路径。"""
    path = prompt_file.resolve().as_posix()
    return (
        "Read and follow ALL instructions in this file using your read tool "
        f"(do NOT use @ to inline it): {path} "
        "Execute everything described in that file completely."
    )


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
        workspace = self._workspace_root(prompt_file, cwd)
        launch = _launch_read_prompt_oneline(prompt_file)
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
            *self._plan_session_agent_flags(node_id),
            "exec",
            "-C",
            str(workspace),
            *_EXEC_SANDBOX_FLAGS,
            "--skip-git-repo-check",
            *self.model_cli_flags(model),
            launch,
        ]
        try:
            logger.info(
                "调用 Codex CLI (headless): %s model=%s -C=%s launch=%s",
                binary,
                model or "(default)",
                workspace,
                launch,
            )
            proc = subprocess.run(
                cmd,
                cwd=str(workspace),
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
        workspace = self._workspace_root(prompt_file, cwd)
        launch = _launch_read_prompt_oneline(prompt_file)
        binary = self._resolve_binary()
        if not binary:
            return AIToolResult(
                content="",
                tool_name=self.name,
                success=False,
                message=f"Codex CLI 不可用，prompt 已保存至 {prompt_file}",
            )

        cmd = [
            binary,
            *self._plan_session_agent_flags(node_id),
            "-C",
            str(workspace),
            *_INTERACTIVE_BYPASS_FLAGS,
            *self.model_cli_flags(model),
            launch,
        ]
        try:
            logger.info(
                "交互调用 Codex CLI: %s model=%s -C=%s launch=%s",
                binary,
                model or "(default)",
                workspace,
                launch,
            )
            return run_interactive_subprocess(
                cmd,
                str(workspace),
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
    def _plan_session_agent_flags(node_id: str | None) -> list[str]:
        """计划会话要在会话内调用 spawn_agent，显式打开 multi_agent。"""
        if node_id == "plan_session":
            return ["--enable", "multi_agent"]
        return []

    @staticmethod
    def _workspace_root(prompt_file: Path, cwd: str) -> Path:
        path = prompt_file.resolve()
        for parent in (path.parent, *path.parents):
            if (parent / ".git").exists():
                return parent
        if path.parent.name == TEMP_PROMPT_DIR:
            return path.parent.parent
        return Path(cwd).resolve()

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
