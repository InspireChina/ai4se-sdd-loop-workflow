"""通用节点执行器 — 每个节点是独立 agent，读取配置后执行。"""

import logging
import sys
from datetime import datetime
from pathlib import Path

from ..agents.registry import get_ai_tool
from ..config_loader import NodeConfig, WorkflowConfig
from ..requirement_dir import resolve_app_root, resolve_docs_path
from ..ai_rules_loader import build_ai_rules_prompt
from ..parsers.clarification_parser import parse_clarification_checklist
from ..parsers.approval_parser import (
    parse_plan_approval,
    parse_requirement_approval,
    parse_review_plan_tests_approval,
    parse_tasks_approval,
    parse_test_cases_approval,
)
from ..parsers.requirement_parser import RequirementMetadata, parse_requirement_metadata
from ..parsers.test_report_parser import parse_test_passed, verify_report_ready
from ..parsers.workflow_status_parser import WorkflowStatus, upsert_workflow_status
from ..phase_gate import (
    PHASE_CONFIGS,
    draft_path,
    ensure_draft_dir,
    get_phase_config,
    phase_complete,
    phase_content_ready,
    resolve_doc_path,
    resolve_draft_path,
    review_plan_tests_complete,
)
from ..state import DevWorkflowState

logger = logging.getLogger(__name__)

_PHASE_NODE_IDS = frozenset(PHASE_CONFIGS.keys())
_CODE_WORK_NODES = frozenset(
    {"implement_code", "verify_tests", "ai_review", "commit_code"}
)


class NodeRunner:
    def __init__(self, workflow_config: WorkflowConfig, project_root: Path):
        self.workflow_config = workflow_config
        self.project_root = project_root
        self.app_root = resolve_app_root(project_root, workflow_config.app_root)
        self.prompts_dir = project_root / "prompts"

    def run_node(self, node_id: str, state: DevWorkflowState) -> DevWorkflowState:
        node_cfg = self.workflow_config.nodes[node_id]
        docs_dir = self._resolve_docs_dir(state)

        auto = bool(state.get("auto"))
        prompt_rel = node_cfg.resolve_prompt_file(auto)
        prompt_template = self._load_prompt(prompt_rel)
        context = self._build_context(node_cfg, state, docs_dir)
        prompt = self._render_prompt(prompt_template, context)
        logger.info(
            "节点 [%s] 使用 prompt %s（%s）",
            node_cfg.name,
            prompt_rel,
            "无人值守" if auto else "人工介入",
        )

        tool = get_ai_tool(node_cfg.tool)
        agent_cwd = self._agent_cwd(node_id)
        output_path = docs_dir / node_cfg.output_file
        output_path.parent.mkdir(parents=True, exist_ok=True)

        interactive = node_cfg.mode == "interactive"

        logger.info(
            "节点 [%s] 使用工具 %s (%s) 开始执行",
            node_cfg.name,
            node_cfg.tool,
            "interactive" if interactive else "headless",
        )
        if node_cfg.tool in ("cursor", "claude_code", "oh_my_pi", "omp"):
            logger.info(
                "%s 将把渲染后的 prompt 写入 %s/temp-prompts/%s.prompt.md",
                node_cfg.tool,
                docs_dir,
                node_id,
            )

        if interactive and not sys.stdin.isatty():
            logger.warning("当前非 TTY 终端，交互模式可能无法正常输入")

        if interactive:
            completion_check = self._build_completion_check(
                node_id, docs_dir, state, output_path
            )
            result = tool.run_interactive(
                prompt=prompt,
                cwd=str(agent_cwd),
                completion_check=completion_check,
                node_id=node_id,
                prompt_dir=str(docs_dir),
            )
            # 交互结束仍未过门禁时打日志，避免「已 approved 却停住」难排查
            if node_id in _PHASE_NODE_IDS and not completion_check():
                logger.warning(
                    "节点 [%s] 交互已结束，但阶段门禁未通过"
                    "（内容结构/requirement_type/approval 等仍不满足 phase_complete）；"
                    "将进入 END，续跑前请检查定稿 YAML",
                    node_cfg.name,
                )
            content, result = self._resolve_interactive_content(
                docs_dir, output_path, node_id, result
            )
        else:
            result = tool.run(
                prompt=prompt,
                cwd=str(agent_cwd),
                node_id=node_id,
                prompt_dir=str(docs_dir),
            )
            content, result = self._resolve_headless_content(
                docs_dir, output_path, node_id, result
            )

        updates: DevWorkflowState = {
            "current_node": node_id,
            "node_outputs": {
                node_id: str(
                    output_path.relative_to(
                        resolve_app_root(
                            self.project_root,
                            state.get("app_root") or self.workflow_config.app_root,
                        )
                    )
                )
            },
            "completed_nodes": [node_id],
        }
        updates.update(self._parse_node_outputs(node_id, content, docs_dir))

        merged_state = {**state, **updates}
        workflow_status = self._build_workflow_status(
            node_id, merged_state, docs_dir, success=result.success
        )

        if node_cfg.mode == "interactive":
            self._finalize_interactive_outputs(
                docs_dir,
                node_cfg,
                output_path=output_path,
                body_content=content,
                result=result,
                status=workflow_status,
            )
        else:
            self._finalize_headless_outputs(
                docs_dir,
                node_cfg,
                output_path=output_path,
                body_content=content,
                result=result,
                status=workflow_status,
            )

        logger.info(
            "节点 [%s] 输出已写入 %s（next=%s）",
            node_cfg.name,
            output_path,
            workflow_status.next_node,
        )

        if not result.success:
            updates["last_error"] = result.message or f"{node_cfg.tool} 执行未完全成功"

        return updates

    def _resolve_interactive_content(
        self,
        docs_dir: Path,
        output_path: Path,
        node_id: str,
        result,
    ) -> tuple[str, object]:
        cfg = get_phase_config(node_id)
        if cfg:
            for name in (cfg.final_file, cfg.draft_file):
                path = (
                    resolve_draft_path(docs_dir, name)
                    if ".draft." in name
                    else docs_dir / name
                )
                if path.exists():
                    text = path.read_text(encoding="utf-8").strip()
                    if text:
                        if not result.success:
                            result.success = True
                        return text, result

        if output_path.exists():
            content = output_path.read_text(encoding="utf-8")
            if content.strip():
                return content, result

        if result.content.strip():
            return result.content, result

        result.success = False
        result.message = result.message or "交互会话未产出文件，请确认 AI 已写入产出"
        return "", result

    def _resolve_headless_content(
        self,
        docs_dir: Path,
        output_path: Path,
        node_id: str,
        result,
    ) -> tuple[str, object]:
        """headless：agent 常把正文写入文件，stdout 仅为摘要；优先读磁盘产出。"""
        cfg = get_phase_config(node_id)
        min_chars = cfg.min_body_chars if cfg else 120
        candidates: list[Path] = []
        if cfg:
            candidates.append(docs_dir / cfg.final_file)
        if output_path not in candidates:
            candidates.append(output_path)

        for path in candidates:
            if not path.exists():
                continue
            raw = path.read_text(encoding="utf-8").strip()
            if not raw:
                continue
            body = self._strip_existing_status(raw)
            if len(body) >= min_chars:
                if not result.success:
                    result.success = True
                logger.info("headless 节点使用 Agent 已写入的文件: %s", path)
                return raw, result

        if result.content.strip():
            return result.content, result

        result.success = False
        result.message = result.message or "headless 未产出文件（stdout 为空且目标路径无内容）"
        return "", result

    def _finalize_headless_outputs(
        self,
        docs_dir: Path,
        node_cfg: NodeConfig,
        *,
        output_path: Path,
        body_content: str,
        result,
        status: WorkflowStatus,
    ) -> None:
        """headless：若 Agent 已写文件则只补状态表，避免用 stdout 摘要覆盖正文。"""
        cfg = get_phase_config(node_cfg.node_id)
        target = output_path
        if cfg:
            final_path = docs_dir / cfg.final_file
            if final_path.exists():
                target = final_path

        if target.exists() and body_content.strip():
            raw = target.read_text(encoding="utf-8")
            body = self._strip_existing_status(raw)
            if not body.strip():
                body = self._strip_existing_status(body_content)
            if not body.lstrip().startswith("# "):
                body = self._wrap_output(node_cfg, body, result)
            target.write_text(upsert_workflow_status(body, status), encoding="utf-8")
            return

        body = self._strip_existing_status(body_content)
        if not body.strip():
            return
        if not body.lstrip().startswith("# "):
            body = self._wrap_output(node_cfg, body, result)
        output_path.write_text(upsert_workflow_status(body, status), encoding="utf-8")

    def _parse_node_outputs(
        self, node_id: str, content: str, docs_dir: Path
    ) -> DevWorkflowState:
        updates: DevWorkflowState = {}

        cfg = get_phase_config(node_id)
        if cfg:
            final_path = docs_dir / cfg.final_file
            draft_path_resolved = resolve_draft_path(docs_dir, cfg.draft_file)

            if final_path.exists():
                final_content = final_path.read_text(encoding="utf-8")
                if node_id == "analyze_requirements":
                    metadata = parse_requirement_metadata(final_content)
                    if metadata.requirement_type:
                        updates.update(metadata.to_state_updates())
                approval_parser = {
                    "analyze_requirements": parse_requirement_approval,
                    "create_plan": parse_plan_approval,
                    "design_test_cases": parse_test_cases_approval,
                    "review_plan_and_tests": parse_review_plan_tests_approval,
                    "split_tasks": parse_tasks_approval,
                }[node_id]
                state_key = cfg.approval_state_key if cfg else f"{node_id}_approved"
                updates.update(approval_parser(final_content).to_state(state_key))

            checklist_source = (
                draft_path_resolved if draft_path_resolved.exists() else final_path
            )
            if checklist_source.exists():
                checklist = parse_clarification_checklist(
                    checklist_source.read_text(encoding="utf-8")
                )
                if checklist.items or checklist_source == draft_path_resolved:
                    updates.update(checklist.to_state())

        if node_id == "verify_tests":
            report_path = docs_dir / "05-test-report.md"
            report = (
                report_path.read_text(encoding="utf-8")
                if report_path.exists()
                else content
            )
            updates["test_passed"] = parse_test_passed(report)

        return updates

    def _build_completion_check(
        self,
        node_id: str,
        docs_dir: Path,
        state: DevWorkflowState,
        output_path: Path,
    ):
        if node_id in _PHASE_NODE_IDS:
            if node_id == "review_plan_and_tests":
                return lambda: review_plan_tests_complete(docs_dir, state)
            return lambda: phase_complete(docs_dir, node_id, state)
        return lambda: _node_output_complete(node_id, output_path)

    def _finalize_interactive_outputs(
        self,
        docs_dir: Path,
        node_cfg: NodeConfig,
        *,
        output_path: Path,
        body_content: str,
        result,
        status: WorkflowStatus,
    ) -> None:
        """交互节点：Agent 直接写文件，程序只补 header（若缺失）与状态表。"""
        cfg = get_phase_config(node_cfg.node_id)
        paths: list[Path] = [output_path]
        if cfg:
            paths = [
                docs_dir / cfg.final_file,
                resolve_draft_path(docs_dir, cfg.draft_file),
            ]

        for path in paths:
            if not path.exists():
                continue
            raw = path.read_text(encoding="utf-8")
            body = self._strip_existing_status(raw)
            if not body.strip():
                continue
            if not body.lstrip().startswith("# "):
                body = self._wrap_output(node_cfg, body, result)
            path.write_text(upsert_workflow_status(body, status), encoding="utf-8")

        if (
            cfg
            and not output_path.exists()
            and body_content.strip()
        ):
            wrapped = self._wrap_output(
                node_cfg, self._strip_existing_status(body_content), result
            )
            output_path.write_text(upsert_workflow_status(wrapped, status), encoding="utf-8")

    def write_workflow_status_for_file(
        self,
        docs_dir: Path,
        output_file: str,
        node_id: str,
        state: DevWorkflowState,
        *,
        success: bool = True,
    ) -> None:
        path = docs_dir / output_file
        if not path.exists():
            return
        content = path.read_text(encoding="utf-8")
        status = self._build_workflow_status(node_id, state, docs_dir, success=success)
        path.write_text(upsert_workflow_status(content, status), encoding="utf-8")

    def _build_workflow_status(
        self,
        node_id: str,
        state: DevWorkflowState,
        docs_dir: Path,
        *,
        success: bool,
    ) -> WorkflowStatus:
        pending = int(state.get("clarification_pending_count") or 0)
        all_resolved = bool(state.get("clarification_resolved", pending == 0))
        skip = bool(state.get("skip_clarification"))

        phase_labels = {
            "analyze_requirements": "requirements",
            "create_plan": "plan",
            "design_test_cases": "test_cases",
            "review_plan_and_tests": "plan_test_review",
            "split_tasks": "tasks",
            "implement_code": "implement",
            "verify_tests": "verify",
            "ai_review": "ai_review",
            "commit_code": "commit",
        }
        phase = phase_labels.get(node_id, node_id)
        next_node = ""

        if node_id in PHASE_CONFIGS:
            cfg = PHASE_CONFIGS[node_id]
            if cfg.requires_approval:
                ready = phase_complete(docs_dir, node_id, state)
            else:
                ready = phase_content_ready(docs_dir, node_id, state)
            next_node = cfg.next_node if ready else node_id
        elif node_id == "implement_code":
            next_node = "verify_tests"
        elif node_id == "verify_tests":
            next_node = "ai_review"
        elif node_id == "ai_review":
            next_node = "commit_code"
        elif node_id == "commit_code":
            next_node = ""

        if skip and node_id == "analyze_requirements" and phase_complete(
            docs_dir, "analyze_requirements", state
        ):
            next_node = "parallel_plan_and_tests"

        test_passed = None
        if node_id == "verify_tests":
            test_passed = bool(state.get("test_passed"))

        return WorkflowStatus(
            node=node_id,
            status="completed" if success else "failed",
            next_node=next_node,
            phase=phase,
            pending_count=pending,
            all_resolved=all_resolved,
            updated_at=datetime.now().isoformat(timespec="seconds"),
            test_passed=test_passed,
        )

    @staticmethod
    def _strip_existing_status(content: str) -> str:
        if "## Workflow 状态" not in content:
            return content
        return content.split("## Workflow 状态", 1)[0].rstrip()

    def _resolve_docs_dir(self, state: DevWorkflowState) -> Path:
        docs_dir = state.get("docs_dir") or self.workflow_config.docs_dir
        app_root = resolve_app_root(
            self.project_root,
            state.get("app_root") or self.workflow_config.app_root,
        )
        return resolve_docs_path(app_root, docs_dir)

    def _agent_cwd(self, node_id: str) -> Path:
        """实现/测试节点在应用项目根执行；其余在本仓库（编排引擎）根目录。"""
        if node_id in _CODE_WORK_NODES:
            return self.app_root
        return self.project_root

    def _load_prompt(self, prompt_file: str) -> str:
        path = self.project_root / prompt_file
        if not path.exists():
            path = self.prompts_dir / Path(prompt_file).name
        if not path.exists():
            raise FileNotFoundError(f"Prompt file not found: {prompt_file}")
        return path.read_text(encoding="utf-8")

    def _build_context(
        self, node_cfg: NodeConfig, state: DevWorkflowState, docs_dir: Path
    ) -> dict[str, str]:
        context: dict[str, str] = {
            "requirement": state.get("requirement", ""),
            "project_root": str(self.project_root),
            "app_root": str(
                resolve_app_root(
                    self.project_root,
                    state.get("app_root") or self.workflow_config.app_root,
                )
            ),
            "docs_dir": str(docs_dir),
            "output_path": str(docs_dir / node_cfg.output_file),
            "node_output_path": str(docs_dir / node_cfg.output_file),
            "skip_clarification_hint": (
                "是 — 跳过与用户澄清，初稿无 pending 时直接输出定稿。"
                if state.get("skip_clarification")
                else "否 — 初稿有待澄清/待决策项时，必须在会话中与用户确认。"
            ),
        }

        cfg = get_phase_config(node_cfg.node_id)
        if cfg:
            ensure_draft_dir(docs_dir)
            context["draft_output_path"] = str(draft_path(docs_dir, cfg.draft_file))
            context["final_output_path"] = str(docs_dir / cfg.final_file)
        else:
            ensure_draft_dir(docs_dir)
            context["draft_output_path"] = str(
                draft_path(docs_dir, "01-requirements.draft.md")
            )
            context["final_output_path"] = str(docs_dir / "01-requirements.md")

        for inp in node_cfg.inputs:
            if inp.kind == "state":
                context[inp.key] = self._format_state_value(state.get(inp.key), inp.key)
            elif inp.kind == "doc":
                doc_path = resolve_doc_path(docs_dir, inp.key)
                context[inp.key.replace(".md", "").replace("-", "_")] = (
                    doc_path.read_text(encoding="utf-8") if doc_path.exists() else ""
                )
                context[f"doc_{inp.key}"] = context[
                    inp.key.replace(".md", "").replace("-", "_")
                ]

        if state.get("requirement_type"):
            meta = RequirementMetadata(
                requirement_type=state.get("requirement_type", "unknown"),
                requirement_summary=state.get("requirement_summary", ""),
                change_scope=state.get("change_scope", ""),
                affected_modules=state.get("affected_modules", []),
                compatibility_risk=state.get("compatibility_risk", "unknown"),
                needs_clarification=bool(
                    (state.get("requirement_metadata") or {}).get("needs_clarification")
                ),
                open_questions_count=int(
                    (state.get("requirement_metadata") or {}).get("open_questions_count", 0)
                ),
                judgment_basis=(state.get("requirement_metadata") or {}).get(
                    "judgment_basis", ""
                ),
            )
            context.update(meta.to_context())

        context["ai_rules"] = build_ai_rules_prompt(
            self.project_root,
            node_cfg.extend_rules,
            rules_dir=self.workflow_config.ai_rules_dir,
            app_root=state.get("app_root") or self.workflow_config.app_root,
        )

        return context

    @staticmethod
    def _format_state_value(value, key: str = "") -> str:
        if value is None:
            return ""
        if isinstance(value, list):
            if value and isinstance(value[0], dict):
                if key == "clarification_questions":
                    lines = []
                    for raw in value:
                        if raw.get("status") == "resolved":
                            continue
                        qid = raw.get("id", "")
                        question = raw.get("question", "")
                        lines.append(f"- [{qid}] {question}")
                        if raw.get("why_it_matters"):
                            lines.append(f"  - 原因：{raw['why_it_matters']}")
                        if raw.get("suggestion"):
                            lines.append(f"  - 建议：{raw['suggestion']}")
                    return "\n".join(lines) if lines else "（无待澄清项）"
                return "\n".join(
                    f"- [{raw.get('id', '?')}] {raw.get('question', raw)}" for raw in value
                )
            return "\n".join(f"- {item}" for item in value)
        if isinstance(value, dict):
            return "\n".join(f"- {k}: {v}" for k, v in value.items())
        return str(value)

    @staticmethod
    def _render_prompt(template: str, context: dict[str, str]) -> str:
        rendered = template
        for key, value in context.items():
            rendered = rendered.replace(f"{{{{{key}}}}}", value)
        return rendered

    @staticmethod
    def _wrap_output(node_cfg: NodeConfig, content: str, result) -> str:
        header = (
            f"# {node_cfg.name}\n\n"
            f"> 节点 ID: `{node_cfg.node_id}`\n"
            f"> AI 工具: `{node_cfg.tool}`\n"
            f"> 模式: `{node_cfg.mode}`\n"
            f"> 生成时间: {datetime.now().isoformat(timespec='seconds')}\n"
            f"> 执行状态: {'成功' if result.success else '需人工介入'}\n"
        )
        if result.message:
            header += f"> 备注: {result.message}\n"
        header += "\n---\n\n"
        return header + content

def _node_output_complete(node_id: str, output_path: Path, *, min_chars: int = 120) -> bool:
    if not output_path.exists():
        return False
    content = output_path.read_text(encoding="utf-8")
    body = content.split("## Workflow 状态", 1)[0].strip()
    if len(body) < min_chars:
        return False
    if node_id == "verify_tests":
        if any(output_path.parent.glob("*.png")) or any(
            output_path.parent.glob("*.jpg")
        ):
            return False
        return verify_report_ready(body)
    return True
