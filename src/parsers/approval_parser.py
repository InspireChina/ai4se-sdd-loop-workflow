"""解析各阶段定稿中的用户确认状态（通用）。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import yaml

APPROVAL_STATUSES = frozenset({"pending", "approved"})


@dataclass
class Approval:
    status: str = "pending"
    confirmed_at: str = ""
    user_note: str = ""

    @property
    def is_approved(self) -> bool:
        return self.status == "approved"

    def to_state(self, state_key: str = "requirement_approved") -> dict[str, Any]:
        return {state_key: self.is_approved}


def parse_approval(content: str, block_name: str) -> Approval:
    raw = _extract_yaml_block(content, block_name)
    if not raw:
        return Approval()

    status = str(raw.get("status", "pending")).strip().lower() or "pending"
    if status not in APPROVAL_STATUSES:
        status = "pending"

    return Approval(
        status=status,
        confirmed_at=str(raw.get("confirmed_at", "")).strip(),
        user_note=str(raw.get("user_note", "")).strip(),
    )


def parse_requirement_approval(content: str) -> Approval:
    return parse_approval(content, "requirement_approval")


def parse_plan_approval(content: str) -> Approval:
    return parse_approval(content, "plan_approval")


def parse_test_cases_approval(content: str) -> Approval:
    return parse_approval(content, "test_cases_approval")


def parse_review_plan_approval(content: str) -> Approval:
    return parse_approval(content, "review_plan_approval")


def parse_tasks_approval(content: str) -> Approval:
    return parse_approval(content, "tasks_approval")


def _extract_yaml_block(content: str, block_name: str) -> dict[str, Any] | None:
    pattern = rf"```yaml\s+{re.escape(block_name)}\s*\n(.*?)```"
    match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
    if not match:
        return None
    try:
        data = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    if block_name in data and isinstance(data[block_name], dict):
        return data[block_name]
    return data
