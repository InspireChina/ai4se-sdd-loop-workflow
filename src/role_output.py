"""计划及之后的产出按角色加文件名后缀。需求文件不拆。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# delivery_role -> 文件名后缀。前端用 front，两边用 all。
ROLE_SUFFIX = {
    "backend": "backend",
    "frontend": "front",
    "both": "all",
}

SUFFIX_ROLE = {suffix: role for role, suffix in ROLE_SUFFIX.items()}

# 这些逻辑文件名会变成 <stem>-backend.md / <stem>-front.md / <stem>-all.md。
ROLE_SCOPED_OUTPUTS = frozenset(
    {
        "02-plan.md",
        "02-test-cases.md",
        "03-tasks.md",
        "04-implementation.md",
        "05-test-report.md",
        "06-ai-review.md",
        "07-commit.md",
    }
)


def role_from_filename(name: str) -> str | None:
    for suffix, role in SUFFIX_ROLE.items():
        if name.endswith(f"-{suffix}.md"):
            return role
    return None


def blocks_for_role(role: str) -> list[str]:
    if role == "both":
        return ["backend", "frontend"]
    if role in ("backend", "frontend"):
        return [role]
    return []


def suffixed_name(logical: str, role: str | None) -> str:
    suffix = ROLE_SUFFIX.get(role or "")
    if not suffix or logical not in ROLE_SCOPED_OUTPUTS or not logical.endswith(".md"):
        return logical
    return f"{logical[:-3]}-{suffix}.md"


def candidate_names(logical: str) -> list[str]:
    if logical not in ROLE_SCOPED_OUTPUTS:
        return [logical]
    stem = logical[:-3]
    return [f"{stem}-{suffix}.md" for suffix in ("backend", "front", "all")]


def find_output(docs_dir: Path, logical: str, role: str | None = None) -> Path | None:
    """已有产出。角色已知时只认对应后缀；未知时三个后缀里取最新的一份。"""
    if logical not in ROLE_SCOPED_OUTPUTS:
        path = docs_dir / logical
        return path if path.is_file() else None

    if role and role not in ("", "unknown"):
        path = docs_dir / suffixed_name(logical, role)
        return path if path.is_file() else None

    found = [docs_dir / name for name in candidate_names(logical) if (docs_dir / name).is_file()]
    if not found:
        return None
    if len(found) == 1:
        return found[0]
    return max(found, key=lambda path: path.stat().st_mtime)


def write_output_path(docs_dir: Path, logical: str, role: str | None) -> Path:
    """本次要写的路径。角色未定且磁盘上已有带后缀的文件时，沿用那一份。"""
    if logical not in ROLE_SCOPED_OUTPUTS:
        return docs_dir / logical
    if role and role not in ("", "unknown"):
        return docs_dir / suffixed_name(logical, role)
    existing = find_output(docs_dir, logical)
    if existing:
        return existing
    return docs_dir / logical


def output_hint(docs_dir: Path, logical: str, role: str | None) -> str:
    """写进提示词的路径。角色未定时列出三个候选。"""
    if logical not in ROLE_SCOPED_OUTPUTS or (role and role not in ("", "unknown")):
        return str(write_output_path(docs_dir, logical, role))
    stem = logical[:-3]
    return "、".join(str(docs_dir / f"{stem}-{suffix}.md") for suffix in ("backend", "front", "all"))


ROLE_ALIASES = {
    "backend": "backend",
    "后端": "backend",
    "frontend": "frontend",
    "前端": "frontend",
    "both": "both",
    "前后端": "both",
    "前后端都有": "both",
}

ROLE_LABELS = {
    "backend": "后端",
    "frontend": "前端",
    "both": "前后端",
}

BLOCK_LABELS = {
    "backend": "后端",
    "frontend": "前端",
}


def format_role_scope(role: str, blocks: list[str] | None, basis: str) -> str:
    """把计划写下的角色渲染成下游 prompt 可直接阅读的文本。"""
    normalized_role, normalized_blocks = _coerce_role_blocks(role, blocks or [])
    if normalized_role == "unknown":
        return "（未识别）"
    block_text = "、".join(
        BLOCK_LABELS[item] for item in normalized_blocks if item in BLOCK_LABELS
    )
    return (
        f"- 角色：{ROLE_LABELS[normalized_role]}\n"
        f"- 版块：{block_text}\n"
        f"- 依据：{basis.strip() or '计划节点写入'}"
    )


def role_fields(role_raw: Any, blocks_raw: Any, basis_raw: Any) -> dict[str, Any]:
    role, blocks = _coerce_role_blocks(role_raw, _as_str_list(blocks_raw))
    return {
        "delivery_role": role,
        "delivery_blocks": blocks,
        "role_basis": str(basis_raw or "").strip(),
    }


def _as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [line.strip("- ").strip() for line in value.splitlines() if line.strip()]
    return [str(value)]


def _coerce_role_blocks(role_raw: Any, blocks_raw: list[str]) -> tuple[str, list[str]]:
    blocks: list[str] = []
    for item in blocks_raw:
        key = ROLE_ALIASES.get(str(item).strip(), "")
        if key == "both":
            for side in ("backend", "frontend"):
                if side not in blocks:
                    blocks.append(side)
        elif key in ("backend", "frontend") and key not in blocks:
            blocks.append(key)

    role = ROLE_ALIASES.get(str(role_raw or "").strip(), "")
    if set(blocks) == {"backend", "frontend"}:
        role = "both"
    elif blocks == ["backend"]:
        role = "backend"
    elif blocks == ["frontend"]:
        role = "frontend"
    elif role == "both":
        blocks = ["backend", "frontend"]
    elif role in ("backend", "frontend"):
        blocks = [role]
    else:
        role = "unknown"
        blocks = []

    ordered = [item for item in ("backend", "frontend") if item in blocks]
    return role, ordered
