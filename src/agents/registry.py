"""AI 工具注册表。"""

from .base import AITool
from .claude_code_agent import ClaudeCodeTool
from .codex_agent import CodexTool
from .cursor_agent import CursorTool
from .echo_agent import EchoTool
from .oh_my_pi_agent import OhMyPiTool

_OH_MY_PI = OhMyPiTool()

_TOOLS: dict[str, AITool] = {
    "cursor": CursorTool(),
    "claude_code": ClaudeCodeTool(),
    "codex": CodexTool(),
    "echo": EchoTool(),
    "oh_my_pi": _OH_MY_PI,
    "omp": _OH_MY_PI,
}


def get_ai_tool(name: str) -> AITool:
    if name not in _TOOLS:
        raise ValueError(
            f"Unknown AI tool: {name}. Available: {', '.join(_TOOLS.keys())}"
        )
    return _TOOLS[name]
