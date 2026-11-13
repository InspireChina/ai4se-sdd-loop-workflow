"""Dev workflow 状态定义 — LangGraph 仅负责状态流转。"""

import operator
from typing import Annotated, Optional

from typing_extensions import TypedDict


def merge_dict(left: dict, right: dict) -> dict:
    merged = dict(left or {})
    merged.update(right or {})
    return merged


class DevWorkflowState(TypedDict, total=False):
    """从需求到测试的 workflow 状态。"""

    requirement: str
    project_root: str
    app_root: str
    docs_dir: str
    requirement_slug: str
    current_node: str
    completed_nodes: Annotated[list[str], operator.add]
    node_outputs: Annotated[dict[str, str], merge_dict]
    # 需求分析节点结构化字段
    requirement_type: str  # new | existing_change | unknown
    requirement_summary: str
    change_scope: str
    affected_modules: list[str]
    compatibility_risk: str  # low | medium | high | unknown
    # 需求分析识别的前后端角色，后续节点只读这份状态
    delivery_role: str  # backend | frontend | both | unknown
    delivery_blocks: list[str]  # backend / frontend
    role_basis: str
    requirement_metadata: Annotated[dict, merge_dict]
    # 需求澄清 loop
    clarification_questions: list[dict[str, str]]
    clarification_resolved: bool
    clarification_pending_count: int
    clarification_round: int
    user_clarifications: str
    skip_clarification: bool
    auto: bool  # --auto 无人值守：禁止向用户提问，门禁在内容就绪后自动通过
    requirement_approved: bool
    plan_approved: bool
    test_cases_approved: bool
    tasks_approved: bool
    resume_from_node: str
    test_passed: bool
    last_error: Optional[str]
