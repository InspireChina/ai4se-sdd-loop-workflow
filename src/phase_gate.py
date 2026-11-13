"""各阶段（需求 / 计划 / 任务）完成判定 — 内容就绪 vs 用户已确认。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .parsers.approval_parser import parse_approval, read_approval_status
from .parsers.clarification_parser import parse_clarification_checklist
from .parsers.requirement_parser import parse_requirement_metadata
from .state import DevWorkflowState


@dataclass(frozen=True)
class PhaseConfig:
    node_id: str
    final_file: str
    approval_block: str
    approval_state_key: str
    next_node: str
    min_body_chars: int = 120
    requires_approval: bool = True
    # True：允许 clarification_checklist 仍有 pending（用例等人澄清，不挡计划会话结束）
    allow_unresolved_checklist: bool = False


def resolve_doc_path(docs_dir: Path, doc_key: str) -> Path:
    return docs_dir / doc_key


PHASE_CONFIGS: dict[str, PhaseConfig] = {
    "analyze_requirements": PhaseConfig(
        node_id="analyze_requirements",
        final_file="01-requirements.md",
        approval_block="requirement_approval",
        approval_state_key="requirement_approved",
        next_node="plan_session",
        min_body_chars=200,
    ),
    "design_test_cases": PhaseConfig(
        node_id="design_test_cases",
        final_file="02-test-cases.md",
        approval_block="test_cases_approval",
        approval_state_key="test_cases_approved",
        next_node="plan_session",
        min_body_chars=200,
        requires_approval=False,
        allow_unresolved_checklist=True,
    ),
    "plan_session": PhaseConfig(
        node_id="plan_session",
        final_file="02-plan.md",
        approval_block="plan_approval",
        approval_state_key="plan_approved",
        next_node="split_tasks",
        min_body_chars=200,
    ),
    "split_tasks": PhaseConfig(
        node_id="split_tasks",
        final_file="03-tasks.md",
        approval_block="tasks_approval",
        approval_state_key="tasks_approved",
        next_node="implement_code",
        min_body_chars=200,
    ),
}


def get_phase_config(node_id: str) -> PhaseConfig | None:
    return PHASE_CONFIGS.get(node_id)


def _body_without_status(content: str) -> str:
    if "## Workflow 状态" in content:
        content = content.split("## Workflow 状态", 1)[0]
    return content.strip()


def _checklist_ready(content: str, state: DevWorkflowState) -> bool:
    if state.get("skip_clarification"):
        return True
    checklist = parse_clarification_checklist(content)
    return checklist.all_resolved or not checklist.items


def _validate_requirements_final(content: str) -> bool:
    metadata = parse_requirement_metadata(content)
    # 仅接受规范化后的 new | existing_change（见 requirement_parser 别名表）
    return metadata.requirement_type in ("new", "existing_change")


def _validate_test_cases_final(content: str, cfg: PhaseConfig) -> bool:
    """用例写完的标志是确认块落成 pending 或 approved。

    pending：AI 已写完，等待人工澄清。approved：人已经确认。
    块还没写出来表示仍在写，不能放行。
    """
    if not _validate_generic_final(content, cfg):
        return False
    status = read_approval_status(content, "test_cases_approval")
    return status in ("pending", "approved")


def _validate_generic_final(content: str, cfg: PhaseConfig) -> bool:
    body = _body_without_status(content)
    if len(body) < cfg.min_body_chars:
        return False
    return "##" in body or len(body.splitlines()) >= 8


CONTENT_VALIDATORS: dict[str, Callable[[str, PhaseConfig], bool]] = {
    "analyze_requirements": lambda content, cfg: _validate_generic_final(content, cfg)
    and _validate_requirements_final(content),
    "design_test_cases": _validate_test_cases_final,
    "plan_session": _validate_generic_final,
    "split_tasks": _validate_generic_final,
}


def phase_content_ready(docs_dir: Path, node_id: str, state: DevWorkflowState) -> bool:
    """定稿 md 结构完整（正文达标）；默认还要求澄清清单已消解。

    design_test_cases 允许澄清清单仍有 pending（allow_unresolved_checklist）。
    """
    cfg = PHASE_CONFIGS.get(node_id)
    if not cfg:
        return False

    final_path = docs_dir / cfg.final_file
    if not final_path.exists():
        return False

    content = final_path.read_text(encoding="utf-8")
    if not cfg.allow_unresolved_checklist and not _checklist_ready(content, state):
        return False

    validator = CONTENT_VALIDATORS.get(node_id, _validate_generic_final)
    return validator(content, cfg)


def phase_user_approved(docs_dir: Path, node_id: str) -> bool:
    cfg = PHASE_CONFIGS.get(node_id)
    if not cfg:
        return False

    final_path = docs_dir / cfg.final_file
    if not final_path.exists():
        return False

    approval = parse_approval(final_path.read_text(encoding="utf-8"), cfg.approval_block)
    return approval.is_approved


def phase_complete(docs_dir: Path, node_id: str, state: DevWorkflowState) -> bool:
    """定稿内容就绪且（若需要）用户已确认，可进入下一阶段。"""
    if not phase_content_ready(docs_dir, node_id, state):
        return False
    cfg = PHASE_CONFIGS.get(node_id)
    if cfg and not cfg.requires_approval:
        return True
    # --auto：内容就绪即过门禁，不等人写 approved
    if state.get("auto"):
        return True
    return phase_user_approved(docs_dir, node_id)


def plan_session_complete(docs_dir: Path, state: DevWorkflowState) -> bool:
    """计划会话结束：`02-plan.md` 已确认，且用例已写完。

    用例写完的标志是 `test_cases_approval` 为 `pending`（等待人工澄清）或 `approved`。
    不要求人已经把用例改成 `approved`。
    """
    if not phase_complete(docs_dir, "plan_session", state):
        return False
    return phase_content_ready(docs_dir, "design_test_cases", state)


def requirements_content_ready(docs_dir: Path, state: DevWorkflowState) -> bool:
    return phase_content_ready(docs_dir, "analyze_requirements", state)


def requirements_complete(docs_dir: Path, state: DevWorkflowState) -> bool:
    return phase_complete(docs_dir, "analyze_requirements", state)
