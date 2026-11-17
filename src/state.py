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
    # 本次启动确认的角色；确认后写入 intent/02-intent-local.md（本地不提交），续跑直接读取。前后端各走各的计划、任务和代码。
    delivery_role: str  # backend | frontend | both | unknown
    delivery_blocks: list[str]  # backend / frontend
    role_basis: str
    # None：还没确认。list（可为空）：相对 app_root 的仓库路径，后续节点只读这份
    involved_repos: list[str] | None
    requirement_metadata: Annotated[dict, merge_dict]
    # 需求澄清 loop
    clarification_questions: list[dict[str, str]]
    clarification_resolved: bool
    clarification_pending_count: int
    clarification_round: int
    user_clarifications: str
    auto: bool  # --auto 无人值守：禁止向用户提问，门禁在内容就绪后自动通过
    requirement_approved: bool
    intent_approved: bool
    plan_approved: bool
    test_cases_approved: bool
    implementation_approved: bool
    test_report_approved: bool
    ai_review_approved: bool
    commit_approved: bool
    tasks_approved: bool
    resume_from_node: str
    # 意图确认的工作分支；新建时的基线（可空）。由 AI 在涉及仓库目录内 checkout。
    git_branch: str
    git_base: str
    test_passed: bool
    last_error: Optional[str]
