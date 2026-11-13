"""解析需求分析节点产出的结构化元数据。"""

import re
from dataclasses import dataclass, field
from typing import Any

import yaml

REQUIREMENT_TYPE_ALIASES = {
    "new": "new",
    "新需求": "new",
    "existing_change": "existing_change",
    "existing_baseline": "existing_change",  # 固化现有行为 / 验收基线
    "baseline": "existing_change",
    "老需求调整": "existing_change",
    "老需求固化": "existing_change",
    "存量需求调整": "existing_change",
    "需求调整": "existing_change",
    "固化": "existing_change",
}

RISK_ALIASES = {
    "low": "low",
    "低": "low",
    "medium": "medium",
    "中": "medium",
    "high": "high",
    "高": "high",
}

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


@dataclass
class RequirementMetadata:
    requirement_type: str = "unknown"
    requirement_summary: str = ""
    change_scope: str = ""
    affected_modules: list[str] = field(default_factory=list)
    compatibility_risk: str = "unknown"
    needs_clarification: bool = False
    open_questions_count: int = 0
    judgment_basis: str = ""
    # 需求分析识别出的前后端角色，写入 workflow 状态后向下游传递
    delivery_role: str = "unknown"  # backend | frontend | both | unknown
    delivery_blocks: list[str] = field(default_factory=list)  # backend / frontend
    role_basis: str = ""

    def to_state_updates(self) -> dict[str, Any]:
        return {
            "requirement_type": self.requirement_type,
            "requirement_summary": self.requirement_summary,
            "change_scope": self.change_scope,
            "affected_modules": self.affected_modules,
            "compatibility_risk": self.compatibility_risk,
            "delivery_role": self.delivery_role,
            "delivery_blocks": list(self.delivery_blocks),
            "role_basis": self.role_basis,
            "requirement_metadata": {
                "needs_clarification": self.needs_clarification,
                "open_questions_count": self.open_questions_count,
                "judgment_basis": self.judgment_basis,
                "delivery_role": self.delivery_role,
                "delivery_blocks": list(self.delivery_blocks),
                "role_basis": self.role_basis,
            },
        }

    def to_context(self) -> dict[str, str]:
        modules = (
            "\n".join(f"- {m}" for m in self.affected_modules)
            if self.affected_modules
            else "（无）"
        )
        type_label = "新需求" if self.requirement_type == "new" else "老需求调整"
        if self.requirement_type == "unknown":
            type_label = "未识别"

        return {
            "requirement_type": self.requirement_type,
            "requirement_type_label": type_label,
            "requirement_summary": self.requirement_summary,
            "change_scope": self.change_scope,
            "affected_modules": modules,
            "compatibility_risk": self.compatibility_risk,
            "needs_clarification": str(self.needs_clarification).lower(),
            "open_questions_count": str(self.open_questions_count),
            "judgment_basis": self.judgment_basis,
        }


def parse_requirement_metadata(content: str) -> RequirementMetadata:
    raw = _extract_yaml_block(content)
    metadata = _from_yaml(raw) if raw else _from_markdown_fallback(content)
    if metadata.delivery_role == "unknown":
        role, blocks, basis = _parse_role_section(content)
        if role != "unknown":
            metadata.delivery_role = role
            metadata.delivery_blocks = blocks
            metadata.role_basis = basis or metadata.role_basis
    return metadata


def format_role_scope(role: str, blocks: list[str] | None, basis: str) -> str:
    """把状态下的角色渲染成下游 prompt 可直接阅读的文本。"""
    normalized_role, normalized_blocks = _coerce_role_blocks(role, blocks or [])
    if normalized_role == "unknown":
        return "（未识别）"
    block_text = "、".join(
        BLOCK_LABELS[item] for item in normalized_blocks if item in BLOCK_LABELS
    )
    return (
        f"- 角色：{ROLE_LABELS[normalized_role]}\n"
        f"- 版块：{block_text}\n"
        f"- 依据：{basis.strip() or '需求分析节点写入'}"
    )


def _extract_yaml_block(content: str) -> dict[str, Any] | None:
    patterns = [
        r"```yaml\s+requirement_metadata\s*\n(.*?)```",
    ]
    for pattern in patterns:
        match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
        if not match:
            continue
        try:
            data = yaml.safe_load(match.group(1))
        except yaml.YAMLError:
            continue
        if isinstance(data, dict):
            return data
    return None


def _normalize_type(value: Any) -> str:
    if value is None:
        return "unknown"
    normalized = REQUIREMENT_TYPE_ALIASES.get(str(value).strip(), "unknown")
    return normalized


def _normalize_risk(value: Any) -> str:
    if value is None:
        return "unknown"
    return RISK_ALIASES.get(str(value).strip().lower(), str(value).strip().lower())


def _as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [line.strip("- ").strip() for line in value.splitlines() if line.strip()]
    return [str(value)]


def _from_yaml(data: dict[str, Any]) -> RequirementMetadata:
    if "requirement_metadata" in data and isinstance(data["requirement_metadata"], dict):
        data = data["requirement_metadata"]

    return RequirementMetadata(
        requirement_type=_normalize_type(data.get("requirement_type")),
        requirement_summary=str(data.get("requirement_summary", "")).strip(),
        change_scope=str(data.get("change_scope", "")).strip(),
        affected_modules=_as_str_list(data.get("affected_modules")),
        compatibility_risk=_normalize_risk(data.get("compatibility_risk")),
        needs_clarification=bool(data.get("needs_clarification", False)),
        open_questions_count=int(data.get("open_questions_count", 0) or 0),
        judgment_basis=str(data.get("judgment_basis", "")).strip(),
        **_role_fields(data.get("delivery_role"), data.get("delivery_blocks"), data.get("role_basis")),
    )


def _from_markdown_fallback(content: str) -> RequirementMetadata:
    metadata = RequirementMetadata()

    type_match = re.search(
        r"需求类型\s*[:：]\s*`?(新需求|老需求调整|存量需求调整)`?",
        content,
    )
    if type_match:
        metadata.requirement_type = _normalize_type(type_match.group(1))

    summary_match = re.search(r"需求摘要\s*[:：]\s*(.+)", content)
    if summary_match:
        metadata.requirement_summary = summary_match.group(1).strip()

    basis_match = re.search(r"判断依据\s*[:：]\s*(.+)", content)
    if basis_match:
        metadata.judgment_basis = basis_match.group(1).strip()

    risk_match = re.search(
        r"兼容(?:性)?风险\s*[:：]\s*`?(low|medium|high|低|中|高)`?",
        content,
        re.IGNORECASE,
    )
    if risk_match:
        metadata.compatibility_risk = _normalize_risk(risk_match.group(1))

    role, blocks, basis = _parse_role_section(content)
    metadata.delivery_role = role
    metadata.delivery_blocks = blocks
    metadata.role_basis = basis
    return metadata


def _role_fields(role_raw: Any, blocks_raw: Any, basis_raw: Any) -> dict[str, Any]:
    role, blocks = _coerce_role_blocks(role_raw, _as_str_list(blocks_raw))
    return {
        "delivery_role": role,
        "delivery_blocks": blocks,
        "role_basis": str(basis_raw or "").strip(),
    }


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


def _parse_role_section(content: str) -> tuple[str, list[str], str]:
    match = re.search(
        r"##\s*角色与版块\s*\n(.*?)(?:\n##\s|\Z)",
        content,
        re.DOTALL,
    )
    if not match:
        return "unknown", [], ""
    section = match.group(1)
    role_match = re.search(r"角色\s*[:：]\s*([^\n]+)", section)
    block_match = re.search(r"版块\s*[:：]\s*([^\n]+)", section)
    basis_match = re.search(r"依据\s*[:：]\s*([^\n]+)", section)
    block_text = block_match.group(1) if block_match else ""
    blocks = [
        part.strip(" `")
        for part in re.split(r"[、,，/|]+", block_text)
        if part.strip(" `")
    ]
    role, normalized_blocks = _coerce_role_blocks(
        role_match.group(1).strip(" `") if role_match else "",
        blocks,
    )
    basis = basis_match.group(1).strip(" `") if basis_match else ""
    return role, normalized_blocks, basis
