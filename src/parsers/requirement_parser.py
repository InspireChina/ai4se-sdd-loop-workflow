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

    def to_state_updates(self) -> dict[str, Any]:
        return {
            "requirement_type": self.requirement_type,
            "requirement_summary": self.requirement_summary,
            "change_scope": self.change_scope,
            "affected_modules": self.affected_modules,
            "compatibility_risk": self.compatibility_risk,
            "requirement_metadata": {
                "needs_clarification": self.needs_clarification,
                "open_questions_count": self.open_questions_count,
                "judgment_basis": self.judgment_basis,
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
    return _from_yaml(raw) if raw else _from_markdown_fallback(content)


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

    return metadata
