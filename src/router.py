"""启动时读取 docs 产出，决定 workflow 从哪个节点继续。"""

from __future__ import annotations

import logging
from pathlib import Path

from .parsers.clarification_parser import parse_clarification_checklist
from .parsers.approval_parser import (
    parse_plan_approval,
    parse_requirement_approval,
    parse_review_plan_tests_approval,
    parse_tasks_approval,
    parse_test_cases_approval,
)
from .parsers.requirement_parser import parse_requirement_metadata
from .parsers.test_report_parser import parse_test_passed
from .parsers.workflow_status_parser import WorkflowStatus, parse_workflow_status_file
from .phase_gate import (
    phase_complete,
    phase_content_ready,
    plan_and_tests_content_ready,
    requirements_complete,
    requirements_content_ready,
    resolve_draft_path,
    review_plan_tests_complete,
)

logger = logging.getLogger(__name__)

# 产出文件检查顺序：越靠前表示流程越靠后
RESUME_CHECKPOINTS: list[tuple[str, str | None]] = [
    ("07-commit.md", None),
    ("06-ai-review.md", "commit_code"),
    ("05-test-report.md", "ai_review"),
    ("04-implementation.md", "verify_tests"),
    ("03-tasks.md", "implement_code"),
    ("02-plan-test-review.md", "split_tasks"),
    ("02-test-cases.md", "review_plan_and_tests"),
    ("02-plan.md", "parallel_plan_and_tests"),
    ("01-requirements.md", "parallel_plan_and_tests"),
    ("draft/01-requirements.draft.md", None),
]

ROUTABLE_NODES = frozenset(
    {
        "analyze_requirements",
        "parallel_plan_and_tests",
        "create_plan",
        "design_test_cases",
        "review_plan_and_tests",
        "split_tasks",
        "implement_code",
        "verify_tests",
        "ai_review",
        "commit_code",
    }
)

_LEGACY_NODE_ALIASES = {
    "create_plan": "parallel_plan_and_tests",
}


def _gate_state(*, skip_clarification: bool = False, auto: bool = False) -> dict:
    return {"skip_clarification": skip_clarification or auto, "auto": auto}


def determine_start_node(
    docs_dir: Path, *, skip_clarification: bool = False, auto: bool = False
) -> str:
    """根据 docs 目录已有 md 决定启动节点（仅启动时调用一次）。"""
    if not docs_dir.is_dir():
        return "analyze_requirements"

    if not (docs_dir / "03-tasks.md").exists():
        plan_tests_start = _resolve_plan_tests_phase_start(
            docs_dir, skip_clarification, auto=auto
        )
        if plan_tests_start:
            logger.info("续跑：plan/test 阶段 → 从节点 %s 开始", plan_tests_start)
            return plan_tests_start

    for filename, fallback_node in RESUME_CHECKPOINTS:
        path = docs_dir / filename
        if not path.exists():
            continue

        start = _resolve_from_file(
            path, filename, skip_clarification=skip_clarification, auto=auto
        )
        if start:
            logger.info("续跑：基于 %s → 从节点 %s 开始", filename, start)
            return _normalize_start_node(start)

        if fallback_node:
            adjusted = _adjust_fallback(
                filename, fallback_node, path.parent, skip_clarification, auto=auto
            )
            logger.info("续跑：发现 %s（无状态表）→ 从 %s 开始", filename, adjusted)
            return _normalize_start_node(adjusted)

    return "analyze_requirements"


def _normalize_start_node(node: str) -> str:
    return _LEGACY_NODE_ALIASES.get(node, node)


def _resolve_plan_tests_phase_start(
    docs_dir: Path, skip_clarification: bool, *, auto: bool = False
) -> str | None:
    """03-tasks 之前：plan + test-cases + review 阶段的续跑入口。"""
    state = _gate_state(skip_clarification=skip_clarification, auto=auto)
    review_path = docs_dir / "02-plan-test-review.md"
    plan_path = docs_dir / "02-plan.md"
    tests_path = docs_dir / "02-test-cases.md"

    if review_path.exists():
        if review_plan_tests_complete(docs_dir, state):
            return "split_tasks"
        return "review_plan_and_tests"

    if plan_path.exists() and tests_path.exists():
        return "review_plan_and_tests"

    if plan_path.exists() or tests_path.exists():
        return "parallel_plan_and_tests"

    return None


def is_workflow_complete(docs_dir: Path) -> bool:
    path = docs_dir / "07-commit.md"
    if not path.exists():
        return False
    status = parse_workflow_status_file(path)
    return bool(status and status.status == "completed" and not status.next_node)


def restore_state_from_docs(
    docs_dir: Path, skip_clarification: bool, *, auto: bool = False
) -> dict:
    """从 md 恢复澄清清单、元数据、确认状态等 state 字段。"""
    restored: dict = {}

    draft = resolve_draft_path(docs_dir, "01-requirements.draft.md")
    if draft.exists():
        checklist = parse_clarification_checklist(draft.read_text(encoding="utf-8"))
        restored.update(checklist.to_state())

    final = docs_dir / "01-requirements.md"
    if final.exists():
        final_content = final.read_text(encoding="utf-8")
        restored.update(parse_requirement_metadata(final_content).to_state_updates())
        restored.update(parse_requirement_approval(final_content).to_state())
        if not restored.get("clarification_questions"):
            checklist = parse_clarification_checklist(final_content)
            restored.update(checklist.to_state())

    plan = docs_dir / "02-plan.md"
    if plan.exists():
        restored.update(parse_plan_approval(plan.read_text(encoding="utf-8")).to_state("plan_approved"))

    tests = docs_dir / "02-test-cases.md"
    if tests.exists():
        restored.update(
            parse_test_cases_approval(tests.read_text(encoding="utf-8")).to_state(
                "test_cases_approved"
            )
        )

    review = docs_dir / "02-plan-test-review.md"
    if review.exists():
        restored.update(
            parse_review_plan_tests_approval(review.read_text(encoding="utf-8")).to_state(
                "review_plan_tests_approved"
            )
        )

    tasks = docs_dir / "03-tasks.md"
    if tasks.exists():
        restored.update(
            parse_tasks_approval(tasks.read_text(encoding="utf-8")).to_state("tasks_approved")
        )

    report = docs_dir / "05-test-report.md"
    if report.exists():
        report_text = report.read_text(encoding="utf-8")
        status = parse_workflow_status_file(report)
        if status is not None and status.test_passed is not None:
            restored["test_passed"] = status.test_passed
        else:
            restored["test_passed"] = parse_test_passed(report_text)

    if skip_clarification or auto:
        restored["skip_clarification"] = True
    if auto:
        restored["auto"] = True

    return restored


def _adjust_fallback(
    filename: str,
    fallback_node: str,
    docs_dir: Path,
    skip_clarification: bool,
    *,
    auto: bool = False,
) -> str:
    state = _gate_state(skip_clarification=skip_clarification, auto=auto)
    if filename == "01-requirements.md":
        if not requirements_complete(docs_dir, state):
            return "analyze_requirements"
    if filename == "02-plan.md":
        tests_path = docs_dir / "02-test-cases.md"
        if tests_path.exists():
            return "review_plan_and_tests"
        return "parallel_plan_and_tests"
    if filename == "02-test-cases.md":
        plan_path = docs_dir / "02-plan.md"
        if plan_path.exists():
            return "review_plan_and_tests"
        return "parallel_plan_and_tests"
    if filename == "02-plan-test-review.md":
        if not review_plan_tests_complete(docs_dir, state):
            return "review_plan_and_tests"
    if filename == "03-tasks.md":
        if not phase_complete(docs_dir, "split_tasks", state):
            return "split_tasks"
    return fallback_node


def _resolve_from_file(
    path: Path, filename: str, *, skip_clarification: bool, auto: bool = False
) -> str | None:
    status = parse_workflow_status_file(path)
    if status:
        return _resolve_from_status(
            status,
            filename,
            docs_dir=path.parent,
            skip_clarification=skip_clarification,
            auto=auto,
        )

    return _infer_without_status(
        path, filename, skip_clarification=skip_clarification, auto=auto
    )


def _resolve_from_status(
    status: WorkflowStatus,
    filename: str,
    *,
    docs_dir: Path,
    skip_clarification: bool,
    auto: bool = False,
) -> str | None:
    if status.status in ("in_progress", "failed") and status.node in ROUTABLE_NODES:
        return status.node

    state = _gate_state(skip_clarification=skip_clarification, auto=auto)
    if status.next_node in ROUTABLE_NODES:
        if filename == "01-requirements.md" and status.next_node in (
            "create_plan",
            "parallel_plan_and_tests",
        ):
            if not requirements_complete(docs_dir, state):
                return "analyze_requirements"
        if filename == "02-plan-test-review.md" and status.next_node == "split_tasks":
            if not review_plan_tests_complete(docs_dir, state):
                return "review_plan_and_tests"
        if filename == "03-tasks.md" and status.next_node == "implement_code":
            if not phase_complete(docs_dir, "split_tasks", state):
                return "split_tasks"
        return status.next_node

    if status.status == "completed" and not status.next_node and filename == "07-commit.md":
        return None
    # 旧产出：ai_review 已完成且无 next_node → 进入新增的 commit_code
    if (
        status.status == "completed"
        and not status.next_node
        and filename == "06-ai-review.md"
    ):
        return "commit_code"

    return _infer_from_status_fields(
        status,
        filename,
        docs_dir=docs_dir,
        skip_clarification=skip_clarification,
        auto=auto,
    )


def _infer_from_status_fields(
    status: WorkflowStatus,
    filename: str,
    *,
    docs_dir: Path,
    skip_clarification: bool,
    auto: bool = False,
) -> str | None:
    state = _gate_state(skip_clarification=skip_clarification, auto=auto)
    skip = skip_clarification or auto

    if filename.endswith("01-requirements.draft.md") or filename == "01-requirements.md":
        if status.pending_count > 0 and not skip:
            return "analyze_requirements"
        if requirements_complete(docs_dir, state):
            return "parallel_plan_and_tests"
        if requirements_content_ready(docs_dir, state):
            return "analyze_requirements"
        return "analyze_requirements"

    if filename == "02-plan.md" or filename == "02-test-cases.md":
        return _resolve_plan_tests_phase_start(
            docs_dir, skip_clarification, auto=auto
        )

    if filename == "02-plan-test-review.md":
        if review_plan_tests_complete(docs_dir, state):
            return "split_tasks"
        return "review_plan_and_tests"

    if filename == "03-tasks.md":
        if phase_complete(docs_dir, "split_tasks", state):
            return "implement_code"
        return "split_tasks"

    return None


def _infer_without_status(
    path: Path, filename: str, *, skip_clarification: bool, auto: bool = False
) -> str | None:
    content = path.read_text(encoding="utf-8")
    checklist = parse_clarification_checklist(content)
    pending = len(checklist.pending_items())
    state = _gate_state(skip_clarification=skip_clarification, auto=auto)
    skip = skip_clarification or auto

    if filename.endswith("01-requirements.draft.md"):
        return "analyze_requirements"

    if filename == "01-requirements.md":
        if pending > 0 and not skip:
            return "analyze_requirements"
        if requirements_complete(path.parent, state):
            return "parallel_plan_and_tests"
        if requirements_content_ready(path.parent, state):
            return "analyze_requirements"
        metadata = parse_requirement_metadata(content)
        if metadata.requirement_type and metadata.requirement_type != "unknown":
            return "analyze_requirements"
        return "analyze_requirements"

    if filename in ("02-plan.md", "02-test-cases.md", "02-plan-test-review.md"):
        return _resolve_plan_tests_phase_start(
            path.parent, skip_clarification, auto=auto
        )

    if filename == "03-tasks.md":
        if phase_complete(path.parent, "split_tasks", state):
            return "implement_code"
        return "split_tasks"

    return None
