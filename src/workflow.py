"""LangGraph workflow 编排 — 节点与边在代码中固定定义。"""

import logging
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from langgraph.graph import END, StateGraph

from .config_loader import load_workflow_config
from .nodes.node_runner import NodeRunner
from .parsers.clarification_parser import parse_clarification_checklist
from .parsers.requirement_parser import parse_requirement_metadata
from .phase_gate import (
    plan_and_tests_content_ready,
    phase_complete,
    requirements_complete,
    resolve_draft_path,
    review_plan_tests_complete,
)
from .requirement_dir import (
    resolve_app_root,
    resolve_docs_path,
    resolve_requirement_docs_dir,
    save_original_requirement,
)
from .router import determine_start_node, is_workflow_complete, restore_state_from_docs
from .state import DevWorkflowState

logger = logging.getLogger(__name__)

_PARALLEL_BRANCHES = ("create_plan", "design_test_cases")


class DevWorkflow:
    def __init__(self, project_root: Path, config_path: Path | None = None):
        self.project_root = project_root.resolve()
        self.config_path = config_path or (self.project_root / "config" / "workflow.yaml")
        self.workflow_config = load_workflow_config(self.config_path)
        self.node_runner = NodeRunner(self.workflow_config, self.project_root)
        self._graph = self._build_graph()

    def route_next(self, state: DevWorkflowState) -> DevWorkflowState:
        start = state.get("resume_from_node") or "analyze_requirements"
        logger.info("启动路由 → 从节点 %s 开始", start)
        return {"current_node": "route_next"}

    def analyze_requirements(self, state: DevWorkflowState) -> DevWorkflowState:
        docs_dir = self._resolve_docs_path(state)
        if state.get("skip_clarification"):
            promoted = self._try_promote_draft_without_clarification(state, docs_dir)
            if promoted is not None:
                return promoted
        return self.node_runner.run_node("analyze_requirements", state)

    def _try_promote_draft_without_clarification(
        self, state: DevWorkflowState, docs_dir: Path
    ) -> DevWorkflowState | None:
        draft_path_resolved = resolve_draft_path(docs_dir, "01-requirements.draft.md")
        final_path = docs_dir / "01-requirements.md"
        if not draft_path_resolved.exists() or final_path.exists():
            return None

        checklist = parse_clarification_checklist(
            draft_path_resolved.read_text(encoding="utf-8")
        )
        if checklist.pending_items():
            return None

        shutil.copyfile(draft_path_resolved, final_path)
        metadata = parse_requirement_metadata(final_path.read_text(encoding="utf-8"))
        if not metadata.requirement_type or metadata.requirement_type == "unknown":
            metadata = parse_requirement_metadata(
                draft_path_resolved.read_text(encoding="utf-8")
            )

        logger.info("跳过澄清且无 pending，已将初稿提升为定稿: %s", final_path)
        app_root = self._resolve_app_root(state)
        updates: DevWorkflowState = {
            "node_outputs": {
                "analyze_requirements": str(final_path.relative_to(app_root)),
            },
            "clarification_resolved": True,
            "clarification_pending_count": 0,
        }
        updates.update(metadata.to_state_updates())
        updates.update(checklist.to_state())
        merged = {**state, **updates}
        self.node_runner.write_workflow_status_for_file(
            docs_dir, "01-requirements.md", "analyze_requirements", merged
        )
        return updates

    def parallel_plan_and_tests(self, state: DevWorkflowState) -> DevWorkflowState:
        """并行 headless：create_plan + design_test_cases（线程池，完成后进入 review）。"""
        docs_dir = self._resolve_docs_path(state)
        if plan_and_tests_content_ready(docs_dir, state):
            logger.info("plan 与 test-cases 已就绪，跳过并行生成")
            return {"current_node": "parallel_plan_and_tests"}

        merged: DevWorkflowState = {}
        errors: list[str] = []

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = {
                pool.submit(self.node_runner.run_node, node_id, state): node_id
                for node_id in _PARALLEL_BRANCHES
            }
            for future in as_completed(futures):
                node_id = futures[future]
                try:
                    branch_updates = future.result()
                    merged = self._merge_branch_updates(merged, branch_updates)
                except Exception as exc:
                    logger.exception("并行节点 %s 失败", node_id)
                    errors.append(f"{node_id}: {exc}")

        if errors:
            merged["last_error"] = "; ".join(errors)
        merged["current_node"] = "parallel_plan_and_tests"
        return merged

    @staticmethod
    def _merge_branch_updates(
        base: DevWorkflowState, branch: DevWorkflowState
    ) -> DevWorkflowState:
        result = dict(base)
        for key, value in branch.items():
            if key in ("node_outputs", "requirement_metadata") and isinstance(value, dict):
                existing = dict(result.get(key) or {})
                existing.update(value)
                result[key] = existing
            elif key == "completed_nodes" and isinstance(value, list):
                existing = list(result.get("completed_nodes") or [])
                existing.extend(value)
                result["completed_nodes"] = existing
            else:
                result[key] = value
        return result

    def review_plan_and_tests(self, state: DevWorkflowState) -> DevWorkflowState:
        return self.node_runner.run_node("review_plan_and_tests", state)

    def create_plan(self, state: DevWorkflowState) -> DevWorkflowState:
        return self.node_runner.run_node("create_plan", state)

    def split_tasks(self, state: DevWorkflowState) -> DevWorkflowState:
        return self.node_runner.run_node("split_tasks", state)

    def implement_code(self, state: DevWorkflowState) -> DevWorkflowState:
        return self.node_runner.run_node("implement_code", state)

    def verify_tests(self, state: DevWorkflowState) -> DevWorkflowState:
        return self.node_runner.run_node("verify_tests", state)

    def ai_review(self, state: DevWorkflowState) -> DevWorkflowState:
        return self.node_runner.run_node("ai_review", state)

    def commit_code(self, state: DevWorkflowState) -> DevWorkflowState:
        return self.node_runner.run_node("commit_code", state)

    def _route_from_start(self, state: DevWorkflowState) -> str:
        return state.get("resume_from_node") or "analyze_requirements"

    def _route_after_analyze(self, state: DevWorkflowState) -> str:
        docs_dir = self._resolve_docs_path(state)
        if requirements_complete(docs_dir, state):
            return "parallel_plan_and_tests"
        return END

    def _route_after_parallel(self, state: DevWorkflowState) -> str:
        docs_dir = self._resolve_docs_path(state)
        if plan_and_tests_content_ready(docs_dir, state):
            return "review_plan_and_tests"
        return END

    def _route_after_review(self, state: DevWorkflowState) -> str:
        docs_dir = self._resolve_docs_path(state)
        if review_plan_tests_complete(docs_dir, state):
            return "split_tasks"
        return END

    def _route_after_split_tasks(self, state: DevWorkflowState) -> str:
        docs_dir = self._resolve_docs_path(state)
        if phase_complete(docs_dir, "split_tasks", state):
            return "implement_code"
        return END

    def _resolve_app_root(self, state: DevWorkflowState | None = None) -> Path:
        if state and state.get("app_root"):
            return resolve_app_root(self.project_root, state["app_root"])
        return resolve_app_root(self.project_root, self.workflow_config.app_root)

    def _resolve_docs_path(self, state: DevWorkflowState) -> Path:
        docs_dir = state.get("docs_dir") or self.workflow_config.docs_dir
        return resolve_docs_path(self._resolve_app_root(state), docs_dir)

    def _build_graph(self):
        workflow = StateGraph(DevWorkflowState)

        workflow.add_node("route_next", self.route_next)
        workflow.add_node("analyze_requirements", self.analyze_requirements)
        workflow.add_node("parallel_plan_and_tests", self.parallel_plan_and_tests)
        workflow.add_node("review_plan_and_tests", self.review_plan_and_tests)
        workflow.add_node("create_plan", self.create_plan)
        workflow.add_node("split_tasks", self.split_tasks)
        workflow.add_node("implement_code", self.implement_code)
        workflow.add_node("verify_tests", self.verify_tests)
        workflow.add_node("ai_review", self.ai_review)
        workflow.add_node("commit_code", self.commit_code)

        workflow.set_entry_point("route_next")
        workflow.add_conditional_edges(
            "route_next",
            self._route_from_start,
            {
                "analyze_requirements": "analyze_requirements",
                "parallel_plan_and_tests": "parallel_plan_and_tests",
                "review_plan_and_tests": "review_plan_and_tests",
                "create_plan": "create_plan",
                "split_tasks": "split_tasks",
                "implement_code": "implement_code",
                "verify_tests": "verify_tests",
                "ai_review": "ai_review",
                "commit_code": "commit_code",
            },
        )
        workflow.add_conditional_edges(
            "analyze_requirements",
            self._route_after_analyze,
            {
                "parallel_plan_and_tests": "parallel_plan_and_tests",
                END: END,
            },
        )
        workflow.add_conditional_edges(
            "parallel_plan_and_tests",
            self._route_after_parallel,
            {
                "review_plan_and_tests": "review_plan_and_tests",
                END: END,
            },
        )
        workflow.add_conditional_edges(
            "review_plan_and_tests",
            self._route_after_review,
            {
                "split_tasks": "split_tasks",
                END: END,
            },
        )
        workflow.add_conditional_edges(
            "split_tasks",
            self._route_after_split_tasks,
            {
                "implement_code": "implement_code",
                END: END,
            },
        )
        workflow.add_edge("implement_code", "verify_tests")
        workflow.add_edge("verify_tests", "ai_review")
        workflow.add_edge("ai_review", "commit_code")
        workflow.add_edge("commit_code", END)

        return workflow.compile()

    @property
    def graph(self):
        return self._graph

    def run(
        self,
        requirement: str,
        docs_dir: str | None = None,
        *,
        name: str | None = None,
        source_file: Path | None = None,
        skip_clarification: bool = False,
        auto: bool = False,
        fresh: bool = False,
    ) -> DevWorkflowState:
        # --auto 隐含跳过澄清；门禁在内容就绪后自动通过（见 phase_gate）
        if auto:
            skip_clarification = True

        app_root = self._resolve_app_root()
        resolved_docs_dir, requirement_slug = resolve_requirement_docs_dir(
            app_root,
            self.workflow_config.docs_dir,
            requirement,
            docs_dir=docs_dir,
            name=name,
            source_file=source_file,
        )
        docs_path = resolve_docs_path(app_root, resolved_docs_dir)

        if fresh and docs_path.exists():
            for path in docs_path.glob("*.md"):
                if path.name != "00-requirement.md":
                    path.unlink()
            draft_subdir = docs_path / "draft"
            if draft_subdir.is_dir():
                for path in draft_subdir.glob("*.md"):
                    path.unlink()

        original_path = save_original_requirement(docs_path, requirement)

        if is_workflow_complete(docs_path):
            logger.info("Workflow 已完成（07-commit.md status=completed）")
            done_state: DevWorkflowState = {
                "requirement": requirement,
                "app_root": str(app_root),
                "docs_dir": resolved_docs_dir,
                "requirement_slug": requirement_slug,
                "clarification_resolved": True,
                "resume_from_node": "",
                "auto": auto,
                "skip_clarification": skip_clarification,
            }
            done_state.update(
                restore_state_from_docs(docs_path, skip_clarification, auto=auto)
            )
            return done_state

        start_node = determine_start_node(
            docs_path, skip_clarification=skip_clarification, auto=auto
        )

        initial: DevWorkflowState = {
            "requirement": requirement,
            "project_root": str(self.project_root),
            "app_root": str(app_root),
            "docs_dir": resolved_docs_dir,
            "requirement_slug": requirement_slug,
            "resume_from_node": start_node,
            "node_outputs": {
                "original_requirement": str(
                    original_path.relative_to(app_root)
                ),
            },
            "completed_nodes": [],
            "requirement_type": "",
            "requirement_summary": "",
            "change_scope": "",
            "affected_modules": [],
            "compatibility_risk": "",
            "requirement_metadata": {},
            "clarification_questions": [],
            "clarification_resolved": False,
            "clarification_pending_count": 0,
            "clarification_round": 0,
            "user_clarifications": "",
            "skip_clarification": skip_clarification,
            "auto": auto,
            "requirement_approved": False,
            "plan_approved": False,
            "test_cases_approved": False,
            "review_plan_tests_approved": False,
            "tasks_approved": False,
            "test_passed": False,
            "last_error": None,
        }
        initial.update(
            restore_state_from_docs(docs_path, skip_clarification, auto=auto)
        )
        return self._graph.invoke(initial)


def create_graph(project_root: str | Path | None = None):
    root = Path(project_root) if project_root else Path(__file__).parent.parent
    return DevWorkflow(root).graph
