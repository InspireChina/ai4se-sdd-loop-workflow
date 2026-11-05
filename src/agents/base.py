"""AI 编程工具抽象层 — 每个节点独立调用，互不影响。"""

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class AIToolResult:
    content: str
    tool_name: str
    success: bool
    message: str = ""


CompletionCheck = Callable[[], bool]


class AITool(ABC):
    name: str

    @staticmethod
    def model_cli_flags(model: str | None) -> list[str]:
        """有配置则追加 ``--model``；空则用 CLI 默认模型。"""
        value = (model or "").strip()
        return ["--model", value] if value else []

    @abstractmethod
    def run(
        self,
        prompt: str,
        cwd: str,
        *,
        node_id: str | None = None,
        prompt_dir: str | None = None,
        model: str | None = None,
    ) -> AIToolResult:
        """非交互模式（headless）执行 prompt，返回 markdown 内容。"""

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
        """交互模式：继承终端 stdin/stdout，用户在 CLI 中与 AI 对话。"""
        return self.run(
            prompt, cwd, node_id=node_id, prompt_dir=prompt_dir, model=model
        )
