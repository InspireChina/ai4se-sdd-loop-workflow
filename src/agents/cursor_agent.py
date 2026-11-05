"""Cursor AI 编程工具适配器（CLI）。

官方入口是 `agent`（非交互脚本用 `-p/--print`），见：
https://cursor.com/docs/cli/headless
兼容旧命令名 `cursor-agent`。

Prompt 写入 docs/<需求>/temp-prompts/ 后只把短指令放进 argv，避免 Windows 命令行超限。
"""

import logging
import os
import shutil
import subprocess
from pathlib import Path

from .base import AITool, AIToolResult, CompletionCheck
from .interactive_runner import run_interactive_subprocess
from .prompt_file import launch_read_prompt, save_node_prompt

logger = logging.getLogger(__name__)

_EXTRA_BIN_DIRS = (Path.home() / ".local" / "bin",)


class CursorTool(AITool):
    name = "cursor"

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
        cli_flags = [
            "-p",
            "--force",
            "--trust",
            "--approve-mcps",
            "--output-format",
            "text",
            *self.model_cli_flags(model),
            launch,
        ]

        for binary in self._resolve_binaries():
            cmd = [binary, *cli_flags]
            try:
                logger.info(
                    "调用 Cursor CLI (headless): %s model=%s",
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
                    logger.warning("Cursor CLI stderr: %s", proc.stderr[:500])
            except FileNotFoundError:
                continue
            except subprocess.TimeoutExpired:
                return AIToolResult(
                    content="",
                    tool_name=self.name,
                    success=False,
                    message="Cursor CLI 执行超时",
                )

        return AIToolResult(
            content=self._fallback_content(prompt),
            tool_name=self.name,
            success=False,
            message="Cursor CLI 不可用",
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
        cli_flags = [
            "--trust",
            "--force",
            "--approve-mcps",
            *self.model_cli_flags(model),
            launch,
        ]

        for binary in self._resolve_binaries():
            cmd = [binary, *cli_flags]
            try:
                logger.info(
                    "交互调用 Cursor CLI: %s model=%s",
                    binary,
                    model or "(default)",
                )
                return run_interactive_subprocess(
                    cmd,
                    cwd,
                    tool_name=self.name,
                    banner_title="进入 Cursor Agent 交互会话",
                    completion_hint="产出文件写入后将自动退出并继续 workflow",
                    completion_check=completion_check,
                )
            except FileNotFoundError:
                continue

        return AIToolResult(
            content="",
            tool_name=self.name,
            success=False,
            message="Cursor CLI 不可用",
        )

    @staticmethod
    def _resolve_binaries() -> list[str]:
        names = ("agent", "cursor-agent")
        found: list[str] = []
        seen: set[str] = set()
        search_path = os.environ.get("PATH", "")
        for extra in _EXTRA_BIN_DIRS:
            if extra.is_dir():
                search_path = f"{extra}{os.pathsep}{search_path}"
        for name in names:
            path = shutil.which(name, path=search_path)
            if path and path not in seen:
                found.append(path)
                seen.add(path)
        return found

    @staticmethod
    def _fallback_content(prompt: str) -> str:
        return (
            "# Cursor 工具未就绪\n\n"
            "> 请安装 Cursor CLI 后重试，或手动执行以下 prompt。\n\n"
            "---\n\n"
            f"{prompt}"
        )
