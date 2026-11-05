"""Claude Code AI 编程工具适配器。

Prompt 写入 docs/<需求>/temp-prompts/ 后只把短指令放进 argv，避免 Windows 命令行超限。
"""

import logging
import subprocess

from .base import AITool, AIToolResult, CompletionCheck
from .interactive_runner import run_interactive_subprocess
from .prompt_file import launch_read_prompt, save_node_prompt

logger = logging.getLogger(__name__)

# 与 Cursor --force/--trust、omp --auto-approve 对齐：写文件/Bash 不再逐条确认
_PERMISSION_FLAGS = (
    "--permission-mode",
    "bypassPermissions",
    "--dangerously-skip-permissions",
)


class ClaudeCodeTool(AITool):
    name = "claude_code"

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
        model_flags = self.model_cli_flags(model)
        for binary in ("claude", "claude-code"):
            cmd = [binary, "--print", *_PERMISSION_FLAGS, *model_flags, launch]
            try:
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
                    logger.warning("Claude Code stderr: %s", proc.stderr[:500])
            except FileNotFoundError:
                continue
            except subprocess.TimeoutExpired:
                return AIToolResult(
                    content="",
                    tool_name=self.name,
                    success=False,
                    message="Claude Code CLI 执行超时",
                )

        return AIToolResult(
            content=self._fallback_content(prompt),
            tool_name=self.name,
            success=False,
            message="Claude Code CLI 不可用",
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
        model_flags = self.model_cli_flags(model)
        for binary in ("claude", "claude-code"):
            cmd = [binary, *_PERMISSION_FLAGS, *model_flags, launch]
            try:
                logger.info(
                    "交互调用 Claude Code CLI: %s model=%s",
                    binary,
                    model or "(default)",
                )
                return run_interactive_subprocess(
                    cmd,
                    cwd,
                    tool_name=self.name,
                    banner_title="进入 Claude Code 交互会话",
                    completion_hint="产出文件写入后将自动退出并继续 workflow",
                    completion_check=completion_check,
                )
            except FileNotFoundError:
                continue

        return AIToolResult(
            content="",
            tool_name=self.name,
            success=False,
            message="Claude Code CLI 不可用",
        )

    @staticmethod
    def _fallback_content(prompt: str) -> str:
        return (
            "# Claude Code 工具未就绪\n\n"
            "> 请安装 Claude Code CLI 后重试，或手动执行以下 prompt。\n\n"
            "---\n\n"
            f"{prompt}"
        )
