"""解析需求澄清问题清单。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import yaml


@dataclass
class ClarificationItem:
    id: str
    question: str
    status: str = "pending"  # pending | resolved
    suggestion: str = ""
    why_it_matters: str = ""
    category: str = ""
    answer: str = ""
    as_is: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "question": self.question,
            "status": self.status,
            "suggestion": self.suggestion,
            "why_it_matters": self.why_it_matters,
            "category": self.category,
            "answer": self.answer,
            "as_is": self.as_is,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ClarificationItem:
        return cls(
            id=str(data.get("id", "")).strip(),
            question=str(data.get("question", "")).strip(),
            status=str(data.get("status", "pending")).strip() or "pending",
            suggestion=str(data.get("suggestion", "")).strip(),
            why_it_matters=str(data.get("why_it_matters", "")).strip(),
            category=str(data.get("category", "")).strip(),
            answer=str(data.get("answer", "")).strip(),
            as_is=str(data.get("as_is", "")).strip(),
        )


@dataclass
class ClarificationChecklist:
    all_resolved: bool = True
    pending_count: int = 0
    items: list[ClarificationItem] = field(default_factory=list)

    def pending_items(self) -> list[ClarificationItem]:
        return [item for item in self.items if item.status != "resolved"]

    def to_state(self) -> dict[str, Any]:
        pending = self.pending_items()
        return {
            "clarification_questions": [item.to_dict() for item in self.items],
            "clarification_resolved": len(pending) == 0,
            "clarification_pending_count": len(pending),
        }


def parse_clarification_checklist(content: str) -> ClarificationChecklist:
    raw = _extract_yaml_block(content)
    if not raw:
        return ClarificationChecklist()

    if "clarification_checklist" in raw and isinstance(raw["clarification_checklist"], dict):
        raw = raw["clarification_checklist"]

    items_raw = raw.get("items") or []
    items: list[ClarificationItem] = []
    if isinstance(items_raw, list):
        for entry in items_raw:
            if isinstance(entry, dict):
                item = ClarificationItem.from_dict(entry)
                if item.id and item.question:
                    items.append(item)

    pending = [item for item in items if item.status != "resolved"]
    all_resolved = bool(raw.get("all_resolved", len(pending) == 0))
    pending_count = int(raw.get("pending_count", len(pending)) or 0)

    if pending:
        all_resolved = False
        pending_count = max(pending_count, len(pending))

    return ClarificationChecklist(
        all_resolved=all_resolved and not pending,
        pending_count=pending_count,
        items=items,
    )


def _extract_yaml_block(content: str) -> dict[str, Any] | None:
    pattern = r"```yaml\s+clarification_checklist\s*\n(.*?)```"
    match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
    if not match:
        return None
    try:
        data = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else None
