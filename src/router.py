"""启动时先进入意图识别。角色确认后，只读这一角色的计划、任务和代码，决定从哪继续。

另一角色的计划、任务和代码文件不参与本次路由。意图不落盘，每次启动重新确认。
"""

from __future__ import annotations

import logging
from pathlib import Path

from .parsers.approval_parser import (
    parse_plan_approval,
    parse_plan_metadata,
    parse_requirement_approval,
    parse_tasks_approval,
    parse_test_cases_approval,
)
from .parsers.clarification_parser import parse_clarification_checklist
from .parsers.requirement_parser import parse_requirement_metadata
from .parsers.test_report_parser import parse_test_passed
from .parsers.workflow_status_parser import parse_workflow_status_file
from .phase_gate import phase_complete, plan_session_complete, requirements_complete
from .role_output import blocks_for_role, find_output

logger = logging.getLogger(__name__)

TRACK_ROLES = ("backend", "frontend", "both")

ROUTABLE_NODES = frozenset(
    {
        "analyze_requirements",
        "identify_intent",
        "plan_session",
        "split_tasks",
        "implement_code",
        "verify_tests",
        "ai_review",
        "commit_code",
    }
)

_CODE_LADDER = (
    ("04-implementation.md", "implement_code", "verify_tests"),
    ("05-test-report.md", "verify_tests", "ai_review"),
    ("06-ai-review.md", "ai_review", "commit_code"),
    ("07-commit.md", "commit_code", ""),
)


def _state(role: str, *, auto: bool = False) -> dict:
    return {
        "auto": auto,
        "delivery_role": role if role in TRACK_ROLES else "unknown",
        "delivery_blocks": blocks_for_role(role) if role in TRACK_ROLES else [],
    }


def resume_node(docs_dir: Path, role: str, *, auto: bool = False) -> str:
    """角色已经在本次运行里确认之后，找这一角色第一个还没完成的节点。"""
    state = _state(role, auto=auto)
    if not requirements_complete(docs_dir, state):
        return "analyze_requirements"
    if role not in TRACK_ROLES:
        return "identify_intent"
    if not plan_session_complete(docs_dir, state):
        return "plan_session"
    if not phase_complete(docs_dir, "split_tasks", state):
        return "split_tasks"
    return _code_resume(docs_dir, role)


def determine_start_node(docs_dir: Path, *, auto: bool = False) -> str:
    """需求未完成时从需求开始。需求已完成时每次都先做意图识别。"""
    if not docs_dir.is_dir() or not requirements_complete(docs_dir, {"auto": auto}):
        logger.info("续跑：需求未完成 → analyze_requirements")
        return "analyze_requirements"
    logger.info("续跑：先确认本次角色，再按该角色已有产出继续")
    return "identify_intent"


def is_workflow_complete(docs_dir: Path, *, role: str) -> bool:
    """只看本次已确认角色的 code/07-commit。另一角色提交完成不算本次结束。"""
    if role not in TRACK_ROLES:
        return False
    path = find_output(docs_dir, "07-commit.md", role)
    if path is None:
        return False
    status = parse_workflow_status_file(path)
    return bool(status and status.status == "completed" and not status.next_node)


def restore_state_from_docs(
    docs_dir: Path, *, role: str = "", auto: bool = False
) -> dict:
    """恢复需求。角色要等本次意图确认后才有；传入角色时再恢复该角色的计划和后续状态。"""
    restored: dict = {}

    final = find_output(docs_dir, "01-requirements.md")
    if final is not None:
        final_content = final.read_text(encoding="utf-8")
        checklist = parse_clarification_checklist(final_content)
        restored.update(checklist.to_state())
        restored.update(parse_requirement_metadata(final_content).to_state_updates())
        restored.update(parse_requirement_approval(final_content).to_state())

    if role in TRACK_ROLES:
        plan = find_output(docs_dir, "02-plan.md", role)
        if plan is not None:
            plan_text = plan.read_text(encoding="utf-8")
            restored.update(parse_plan_approval(plan_text).to_state("plan_approved"))
            present, repos = parse_plan_metadata(plan_text)
            if present:
                restored["involved_repos"] = repos

    active = str(restored.get("delivery_role") or (role if role in TRACK_ROLES else ""))
    if active in TRACK_ROLES:
        tests = find_output(docs_dir, "02-test-cases.md")
        if tests is not None:
            restored.update(
                parse_test_cases_approval(tests.read_text(encoding="utf-8")).to_state(
                    "test_cases_approved"
                )
            )

        tasks = find_output(docs_dir, "03-tasks.md", active)
        if tasks is not None:
            restored.update(
                parse_tasks_approval(tasks.read_text(encoding="utf-8")).to_state(
                    "tasks_approved"
                )
            )

        report = find_output(docs_dir, "05-test-report.md", active)
        if report is not None:
            report_text = report.read_text(encoding="utf-8")
            status = parse_workflow_status_file(report)
            if status is not None and status.test_passed is not None:
                restored["test_passed"] = status.test_passed
            else:
                restored["test_passed"] = parse_test_passed(report_text)

    if auto:
        restored["auto"] = True
    return restored


def _code_resume(docs_dir: Path, role: str) -> str:
    found: tuple[Path, str, str] | None = None
    for filename, current, nxt in _CODE_LADDER:
        path = find_output(docs_dir, filename, role)
        if path is not None:
            found = (path, current, nxt)
    if found is None:
        return "implement_code"

    path, current, nxt = found
    status = parse_workflow_status_file(path)
    if (
        path.name.startswith("07-commit")
        and status
        and status.status == "completed"
        and not status.next_node
    ):
        return "commit_code"
    if status and status.status in ("in_progress", "failed") and status.node in ROUTABLE_NODES:
        return status.node
    if status and status.next_node in ROUTABLE_NODES:
        return status.next_node
    if status and status.status == "completed" and nxt:
        return nxt
    return current
