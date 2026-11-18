"""启动时优先沿用本地意图；否则进入意图识别。

角色确认后，只读这一角色的计划、任务和代码，决定从哪继续。
另一角色的计划、任务和代码文件不参与本次路由。
意图落在 intent/02-intent-local.md（本地不提交），续跑逻辑与 restore 同在本文件。
"""

from __future__ import annotations

import logging
from pathlib import Path

from .parsers.approval_parser import (
    parse_ai_review_approval,
    parse_commit_approval,
    parse_implementation_approval,
    parse_intent_approval,
    parse_intent_metadata,
    parse_plan_approval,
    parse_plan_git_branch,
    parse_plan_metadata,
    parse_requirement_approval,
    parse_tasks_approval,
    parse_test_cases_approval,
    parse_test_report_approval,
)
from .parsers.clarification_parser import parse_clarification_checklist
from .parsers.requirement_parser import parse_requirement_metadata
from .parsers.test_report_parser import parse_test_passed
from .parsers.workflow_status_parser import parse_workflow_status_file
from .phase_gate import phase_complete, plan_session_complete, requirements_complete
from .role_output import blocks_for_role, find_output

logger = logging.getLogger(__name__)

TRACK_ROLES = ("backend", "frontend", "both")

INTENT_FILENAME = "02-intent-local.md"
_INTENT_GITIGNORE = "*\n!.gitignore\n"

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

_CODE_ORDER = ("implement_code", "verify_tests", "ai_review", "commit_code")


def intent_dir(docs_dir: Path) -> Path:
    return docs_dir / "intent"


def intent_local_path(docs_dir: Path) -> Path:
    return intent_dir(docs_dir) / INTENT_FILENAME


def _ensure_intent_gitignore(docs_dir: Path) -> None:
    folder = intent_dir(docs_dir)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / ".gitignore"
    if path.is_file():
        return
    path.write_text(_INTENT_GITIGNORE, encoding="utf-8")


def clear_intent_cache(docs_dir: Path) -> None:
    """--fresh：清掉意图本地文件（保留 .gitignore）。"""
    folder = intent_dir(docs_dir)
    if not folder.is_dir():
        return
    for path in folder.iterdir():
        if path.name == ".gitignore":
            continue
        if path.is_file():
            path.unlink()


def persist_intent(docs_dir: Path, text: str) -> Path | None:
    """把已确认的意图正文写入 intent/02-intent-local.md。"""
    _ensure_intent_gitignore(docs_dir)
    path = intent_local_path(docs_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
    logger.info("意图已落盘：%s（本地不提交）", path)
    return path


def load_cached_intent(docs_dir: Path) -> dict | None:
    """读取统一的本地意图文件；无效则返回 None。"""
    path = intent_local_path(docs_dir)
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if not parse_intent_approval(text).is_approved:
        return None
    meta = parse_intent_metadata(text)
    if meta.delivery_role not in TRACK_ROLES:
        return None
    if meta.involved_repos is None:
        return None
    branch = meta.git_branch.strip()
    if not branch:
        return None
    return {
        "delivery_role": meta.delivery_role,
        "delivery_blocks": list(meta.delivery_blocks or []),
        "role_basis": meta.role_basis,
        "involved_repos": list(meta.involved_repos or []),
        "git_branch": branch,
        "git_base": meta.git_base,
        "intent_approved": True,
        "intent_text": text,
        "intent_path": str(path),
    }


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
    """需求未完成时从需求开始。需求已完成时优先沿用本地意图，否则做意图识别。"""
    if not docs_dir.is_dir() or not requirements_complete(docs_dir, {"auto": auto}):
        logger.info("续跑：需求未完成 → analyze_requirements")
        return "analyze_requirements"
    cached = load_cached_intent(docs_dir)
    if cached:
        role = str(cached["delivery_role"])
        nxt = resume_node(docs_dir, role, auto=auto)
        logger.info("续跑：沿用本地意图 role=%s → %s", role, nxt)
        return nxt
    logger.info("续跑：无本地意图缓存 → identify_intent")
    return "identify_intent"


def is_workflow_complete(docs_dir: Path, *, role: str) -> bool:
    """只看本次已确认角色的 code/07-commit。另一角色提交完成不算本次结束。"""
    if role not in TRACK_ROLES:
        return False
    if not phase_complete(docs_dir, "commit_code", {"delivery_role": role}):
        return False
    path = find_output(docs_dir, "07-commit.md", role)
    if path is None:
        return False
    status = parse_workflow_status_file(path)
    return bool(status and status.status == "completed" and not status.next_node)


def restore_state_from_docs(
    docs_dir: Path, *, role: str = "", auto: bool = False
) -> dict:
    """恢复需求。传入角色（来自本地意图或本次识别）时再恢复该角色的计划和后续状态。"""
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
            branch = parse_plan_git_branch(plan_text)
            if branch:
                restored["git_branch"] = branch

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

        impl = find_output(docs_dir, "04-implementation.md", active)
        if impl is not None:
            restored.update(
                parse_implementation_approval(
                    impl.read_text(encoding="utf-8")
                ).to_state("implementation_approved")
            )

        report = find_output(docs_dir, "05-test-report.md", active)
        if report is not None:
            report_text = report.read_text(encoding="utf-8")
            restored.update(
                parse_test_report_approval(report_text).to_state(
                    "test_report_approved"
                )
            )
            status = parse_workflow_status_file(report)
            if status is not None and status.test_passed is not None:
                restored["test_passed"] = status.test_passed
            else:
                restored["test_passed"] = parse_test_passed(report_text)

        review = find_output(docs_dir, "06-ai-review.md", active)
        if review is not None:
            restored.update(
                parse_ai_review_approval(review.read_text(encoding="utf-8")).to_state(
                    "ai_review_approved"
                )
            )

        commit = find_output(docs_dir, "07-commit.md", active)
        if commit is not None:
            restored.update(
                parse_commit_approval(commit.read_text(encoding="utf-8")).to_state(
                    "commit_approved"
                )
            )

    if auto:
        restored["auto"] = True
    return restored


def _clamp_code_target(docs_dir: Path, role: str, target: str) -> str:
    """未写对应 ``*_approval.approved`` 时，不得跳到更后面的节点。"""
    state = {"delivery_role": role}
    if target not in _CODE_ORDER:
        return target
    target_idx = _CODE_ORDER.index(target)
    for idx, node in enumerate(_CODE_ORDER):
        if idx > target_idx:
            break
        if not phase_complete(docs_dir, node, state):
            return node
    return target


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
        target = status.node
    elif status and status.next_node in ROUTABLE_NODES:
        target = status.next_node
    elif status and status.status == "completed" and nxt:
        target = nxt
    else:
        target = current

    return _clamp_code_target(docs_dir, role, target)
