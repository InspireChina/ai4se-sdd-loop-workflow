"""解析各阶段定稿中的用户确认状态（通用）。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import yaml

from ..role_output import blocks_for_role, role_fields, role_from_filename

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


def read_approval_status(content: str, block_name: str) -> str | None:
    """返回确认块里的 status。块不存在时返回 None，不把缺块当成 pending。"""
    raw = _extract_yaml_block(content, block_name)
    if not raw:
        return None
    status = str(raw.get("status", "")).strip().lower()
    return status or None


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


def parse_plan_metadata(content: str) -> tuple[bool, list[str]]:
    """读取计划里的涉及仓库。块不存在时第一项为 False。"""
    raw = _extract_yaml_block(content, "plan_metadata")
    if raw is None:
        return False, []
    repos = raw.get("involved_repos") or []
    if isinstance(repos, str):
        repos = [repos]
    if not isinstance(repos, list):
        return True, []
    names: list[str] = []
    for item in repos:
        name = str(item).strip()
        if name and name not in names:
            names.append(name)
    return True, names


def parse_plan_role(content: str, filename: str = "") -> tuple[str, list[str], str]:
    """计划里的前后端角色。元数据优先，没有时用文件名后缀。"""
    raw = _extract_yaml_block(content, "plan_metadata") or {}
    fields = role_fields(
        raw.get("delivery_role"),
        raw.get("delivery_blocks"),
        raw.get("role_basis"),
    )
    role = fields["delivery_role"]
    blocks = list(fields["delivery_blocks"])
    basis = fields["role_basis"]
    if role == "unknown":
        from_name = role_from_filename(filename)
        if from_name:
            return from_name, blocks_for_role(from_name), basis
    return role, blocks, basis


def parse_test_cases_approval(content: str) -> Approval:
    return parse_approval(content, "test_cases_approval")


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
