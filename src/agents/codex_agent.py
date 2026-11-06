"""OpenAI Codex CLI 适配器。

与 Claude / omp / Cursor 同一套路：长 prompt 落盘，argv 只传短「去读该文件」指令。

Codex 差异：
- ``-C`` 指到含 prompt 的 git 仓库根（或需求 docs 目录），保证相对路径可读
- headless ``codex exec``：``--sandbox danger-full-access``，必要时 ``--skip-git-repo-check``
- interactive ``codex``：``--dangerously-bypass-approvals-and-sandbox``
  （交互态不支持 ``--skip-git-repo-check``）

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
        launch = self._write_launch_sidecar(prompt_file, workspace)
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
            "-C",
            str(workspace),
            *_EXEC_SANDBOX_FLAGS,
            "--skip-git-repo-check",
            *self.model_cli_flags(model),
            launch,
        ]
        try:
            logger.info(
                "调用 Codex CLI (headless): %s model=%s -C=%s prompt=%s launch=%s",
                binary,
                model or "(default)",
                workspace,
                prompt_file,
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
        launch = self._write_launch_sidecar(prompt_file, workspace)
        binary = self._resolve_binary()
        if not binary:
            return AIToolResult(
                content="",
                tool_name=self.name,
                success=False,
                message=f"Codex CLI 不可用，prompt 已保存至 {prompt_file}",
            )

        # 注意：interactive 不支持 --skip-git-repo-check
        cmd = [
            binary,
            "-C",
            str(workspace),
            *_INTERACTIVE_BYPASS_FLAGS,
            *self.model_cli_flags(model),
            launch,
        ]
        try:
            logger.info(
                "交互调用 Codex CLI: %s model=%s -C=%s prompt=%s launch=%s",
                binary,
                model or "(default)",
                workspace,
                prompt_file,
                launch,
            )
            print(f"[codex] workspace(-C): {workspace}", flush=True)
            print(f"[codex] prompt file: {prompt_file.resolve()}", flush=True)
            print(f"[codex] argv prompt: {launch}", flush=True)
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
    def _workspace_root(prompt_file: Path, cwd: str) -> Path:
        """优先含 prompt 的 git 根；否则需求 docs 目录；再否则 cwd。"""
        path = prompt_file.resolve()
        for parent in (path.parent, *path.parents):
            if (parent / ".git").exists():
                return parent
        if path.parent.name == TEMP_PROMPT_DIR:
            return path.parent.parent
        return Path(cwd).resolve()

    @classmethod
    def _write_launch_sidecar(cls, prompt_file: Path, workspace: Path) -> str:
        """写入 workspace 内短指引文件，argv 只引用该文件名（避开 Windows 多行/长 argv 丢路径）。"""
        abs_path = prompt_file.resolve()
        try:
            rel_path = abs_path.relative_to(workspace.resolve()).as_posix()
        except ValueError:
            rel_path = abs_path.as_posix()
        sidecar = workspace.resolve() / ".sddl-codex-launch.md"
        sidecar.write_text(
            "Read and follow ALL instructions in this file using your read tool "
            f"(do NOT use @ to inline it):\n\n`{rel_path}`\n\n"
            f"Absolute path: `{abs_path.as_posix()}`\n\n"
            "Execute everything described in that file completely.\n",
            encoding="utf-8",
        )
        # 单行、短、无换行 —— Windows 上不易丢
        return "Read .sddl-codex-launch.md and follow it completely."

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
