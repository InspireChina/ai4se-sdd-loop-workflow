"""将节点 prompt 落到磁盘，避免把全文塞进 CLI argv（Windows 约 32KB 上限）。"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

TEMP_PROMPT_DIR = "temp-prompts"
DEFAULT_PROMPT_STEM = "task"


def save_node_prompt(
    prompt: str,
    cwd: str,
    *,
    node_id: str | None = None,
    prompt_dir: str | Path | None = None,
) -> Path:
    if prompt_dir is not None:
        target_dir = Path(prompt_dir).resolve() / TEMP_PROMPT_DIR
    else:
        target_dir = Path(cwd).resolve() / "spec" / TEMP_PROMPT_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    stem = node_id.strip() if node_id else DEFAULT_PROMPT_STEM
    prompt_file = target_dir / f"{stem}.prompt.md"
    prompt_file.write_text(prompt, encoding="utf-8")
    size = len(prompt.encode("utf-8"))
    logger.info("节点 prompt 已写入 %s (%d bytes)", prompt_file, size)
    print(f"[prompt] 文件: {prompt_file} ({size} bytes)", flush=True)
    return prompt_file


def prompt_display_path(prompt_file: Path, cwd: str | Path | None = None) -> str:
    """启动指令里指向提示词的路径：优先相对 Agent cwd，避免只给文件名找不到。"""
    if cwd is None:
        return prompt_file.name.replace("\\", "/")
    return os.path.relpath(
        str(Path(prompt_file).resolve()), str(Path(cwd).resolve())
    ).replace("\\", "/")


def launch_read_prompt(
    prompt_file: Path,
    *,
    display_path: str | None = None,
    cwd: str | Path | None = None,
    extra: str = "",
) -> str:
    # 路径相对 Agent cwd（业务根）；提示词正文内其它文档路径则相对本文件所在 temp-prompts/
    path = (display_path or prompt_display_path(prompt_file, cwd)).replace("\\", "/")
    parts = [
        "Read and follow ALL instructions in this file using your read tool "
        f"(do NOT use @ to inline it):\n{path}",
        "Paths listed inside that prompt file are relative to the prompt file's "
        "directory (temp-prompts/), not to the shell cwd.",
    ]
    extra = extra.strip()
    if extra:
        parts.append(extra)
    parts.append("Execute everything described in that file completely.")
    return "\n\n".join(parts)
