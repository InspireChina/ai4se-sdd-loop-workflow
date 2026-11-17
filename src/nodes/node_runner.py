"""通用节点执行器 — 每个节点是独立 agent，读取配置后执行。"""

import logging
import sys
import time
from datetime import datetime
from pathlib import Path

from ..agents.base import AIToolResult
from ..agents.prompt_file import save_node_prompt
from ..agents.registry import get_ai_tool
from ..agents.subagent_delegation import (
    testcase_delegation,
    testcase_ready_note,
)
from ..config_loader import NodeConfig, NodeScoringRules, WorkflowConfig
from ..requirement_dir import (
    path_for_state,
    resolve_app_root,
    resolve_docs_path,
    resolve_project_docs_dir,
)
from ..ai_rules_loader import (
    build_ai_rules_prompt,
    materialize_rule_references,
    restrict_rules_to_involved,
    rule_catalog_mode,
)
from ..parsers.clarification_parser import parse_clarification_checklist
from ..parsers.approval_parser import (
    parse_intent_approval,
    parse_intent_metadata,
    parse_plan_approval,
    parse_plan_metadata,
    parse_plan_role,
    parse_requirement_approval,
    parse_tasks_approval,
    parse_test_cases_approval,
)
from ..parsers.requirement_parser import RequirementMetadata, parse_requirement_metadata
from ..parsers.test_report_parser import parse_test_passed, verify_report_ready
from ..parsers.workflow_status_parser import WorkflowStatus, upsert_workflow_status
from ..router import persist_intent
from ..role_output import (
    ROLE_SCOPED_OUTPUTS,
    find_output,
    format_role_scope,
    output_hint,
    role_from_filename,
    write_output_path,
)
from ..phase_gate import (
    PHASE_CONFIGS,
    get_phase_config,
    phase_complete,
    phase_content_ready,
    plan_session_complete,
    resolve_doc_path,
)
from ..state import DevWorkflowState

logger = logging.getLogger(__name__)

EMPTY_SCORING_HINT = "（本节点未配置 suggestion_confidence 把握规则；按你的整体把握给 0-1 浮点，无法评估写 0.0）"


def _hydrate_involved_repos(
    docs_dir: Path, state: DevWorkflowState
) -> dict[str, list[str]]:
    """state 里已有涉及仓库（含意图确认的空列表）就不动。没有则从本次角色的计划读一次。"""
    if state.get("involved_repos") is not None:
        return {}
    role = str(state.get("delivery_role") or "")
    if role in ("", "unknown"):
        return {}
    plan_path = find_output(docs_dir, "02-plan.md", role)
    if plan_path is None:
        return {}
    present, repos = parse_plan_metadata(plan_path.read_text(encoding="utf-8"))
    if not present:
        return {}
    return {"involved_repos": repos}


def _hydrate_delivery_role(
    docs_dir: Path, state: DevWorkflowState
) -> dict[str, object]:
    """角色由意图节点或启动时的本地 intent 缓存写入 state，不从别的角色的计划里取。"""
    del docs_dir, state
    return {}


def _format_rule_list(rules: list, label: str) -> list[str]:
    lines: list[str] = []
    for rule in rules:
        lines.append(
            f"  - {rule.condition}"
            + (f"（{rule.reason}）" if rule.reason else "")
        )
    return lines


def build_suggestion_confidence_prompt(
    scoring_rules: dict[str, NodeScoringRules],
    node_id: str,
) -> str:
    """把当前节点的 suggestion_confidence 把握规则渲染为可注入 prompt 的文本。"""
    rules = scoring_rules.get(node_id)
    if not rules:
        return EMPTY_SCORING_HINT

    lines: list[str] = []
    if rules.description:
        lines.append(f"**节点**：{rules.description}")
    lines.append("")
    lines.append("**高把握规则 high_confidence_rules**（命中则把握更高）：")
    if rules.high_confidence_rules:
        lines.extend(_format_rule_list(rules.high_confidence_rules, "high"))
    else:
        lines.append("  - （无）")
    lines.append("")
    lines.append("**低把握规则 low_confidence_rules**（命中则把握更低）：")
    if rules.low_confidence_rules:
        lines.extend(_format_rule_list(rules.low_confidence_rules, "low"))
    else:
        lines.append("  - （无）")
    lines.append("")
    lines.append(
        "综合命中的高/低把握规则，自行给出 0-1 的 `suggestion_confidence`，"
        "并在 `suggestion_reason` 注明命中的规则依据；无硬性公式。"
    )
    return "\n".join(lines)

_PHASE_NODE_IDS = frozenset(PHASE_CONFIGS.keys())
# 工作目录用启动终端所在的业务项目根
_APP_ROOT_NODES = frozenset(
    {
        "analyze_requirements",
        "identify_intent",
        "plan_session",
        "design_test_cases",
        "implement_code",
        "verify_tests",
        "ai_review",
        "commit_code",
    }
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

        hydrated = _hydrate_involved_repos(docs_dir, state)
        hydrated.update(_hydrate_delivery_role(docs_dir, state))
        if hydrated:
            state = {**state, **hydrated}

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
        if node_id == "identify_intent":
            return self._run_identify_intent(node_cfg, docs_dir, prompt)

        tool = get_ai_tool(node_cfg.tool)
        agent_cwd = self._agent_cwd(node_id)
        output_path = write_output_path(
            docs_dir, node_cfg.output_file, str(state.get("delivery_role") or "")
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)

        interactive = node_cfg.mode == "interactive"
        configured_model = (node_cfg.model or "").strip()
        effective_model = configured_model
        if node_cfg.tool == "echo" and configured_model:
            logger.warning(
                "节点 %s tool=echo 无模型概念，忽略 model=%s",
                node_id,
                configured_model,
            )
            effective_model = ""

        logger.info(
            "进入节点 [%s] (%s) tool=%s model=%s mode=%s",
            node_cfg.name,
            node_id,
            node_cfg.tool,
            effective_model or "(tool默认)",
            "interactive" if interactive else "headless",
        )
        if node_cfg.tool in (
            "cursor",
            "claude_code",
            "codex",
            "oh_my_pi",
            "omp",
        ):
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
                model=effective_model or None,
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
                model=effective_model or None,
            )
            content, result = self._resolve_headless_content(
                docs_dir, output_path, node_id, result
            )

        role_now = str(state.get("delivery_role") or "")
        found_output = find_output(
            docs_dir,
            node_cfg.output_file,
            role_now if role_now and role_now != "unknown" else None,
        )
        if found_output is not None:
            output_path = found_output

        updates: DevWorkflowState = {
            "current_node": node_id,
            "node_outputs": {
                node_id: path_for_state(
                    output_path,
                    resolve_app_root(
                        self.project_root,
                        state.get("app_root") or self.workflow_config.app_root,
                    ),
                )
            },
            "completed_nodes": [node_id],
        }
        updates.update(hydrated)
        updates.update(self._parse_node_outputs(node_id, content, docs_dir, state, output_path))

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
            final = find_output(docs_dir, cfg.final_file)
            if final is not None:
                text = final.read_text(encoding="utf-8").strip()
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
            found = find_output(docs_dir, cfg.final_file)
            if found is not None:
                candidates.append(found)
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
            final_path = find_output(docs_dir, cfg.final_file)
            if final_path is not None:
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

        if not _can_create_output(node_cfg.output_file, output_path):
            return
        body = self._strip_existing_status(body_content)
        if not body.strip():
            return
        if not body.lstrip().startswith("# "):
            body = self._wrap_output(node_cfg, body, result)
        output_path.write_text(upsert_workflow_status(body, status), encoding="utf-8")

    def _parse_node_outputs(
        self,
        node_id: str,
        content: str,
        docs_dir: Path,
        state: DevWorkflowState,
        output_path: Path | None = None,
    ) -> DevWorkflowState:
        updates: DevWorkflowState = {}

        cfg = get_phase_config(node_id)
        role = str(state.get("delivery_role") or "")
        if output_path is not None and role_from_filename(output_path.name):
            role = role_from_filename(output_path.name) or role
        if cfg:
            final_path = (
                output_path
                if output_path is not None and output_path.exists()
                else find_output(
                    docs_dir,
                    cfg.final_file,
                    role if role and role != "unknown" else None,
                )
            )
            if final_path is not None and final_path.exists():
                final_content = final_path.read_text(encoding="utf-8")
                if node_id == "analyze_requirements":
                    metadata = parse_requirement_metadata(final_content)
                    if metadata.requirement_type:
                        updates.update(metadata.to_state_updates())
                approval_parser = {
                    "analyze_requirements": parse_requirement_approval,
                    "design_test_cases": parse_test_cases_approval,
                    "plan_session": parse_plan_approval,
                    "split_tasks": parse_tasks_approval,
                }[node_id]
                state_key = cfg.approval_state_key if cfg else f"{node_id}_approved"
                updates.update(approval_parser(final_content).to_state(state_key))
                if node_id == "plan_session":
                    # 角色 / 涉及仓库 / 分支以意图确认为准，只透传，不用计划文件回写覆盖。
                    if state.get("involved_repos") is None:
                        present, repos = parse_plan_metadata(final_content)
                        if present:
                            updates["involved_repos"] = repos
                    if str(state.get("delivery_role") or "") in ("", "unknown"):
                        parsed, blocks, basis = parse_plan_role(
                            final_content, final_path.name
                        )
                        if parsed != "unknown":
                            updates["delivery_role"] = parsed
                            updates["delivery_blocks"] = blocks
                            updates["role_basis"] = basis

                checklist = parse_clarification_checklist(final_content)
                if checklist.items:
                    updates.update(checklist.to_state())

        if node_id == "verify_tests":
            report_role = str(updates.get("delivery_role") or state.get("delivery_role") or "")
            report_path = find_output(
                docs_dir,
                "05-test-report.md",
                report_role if report_role and report_role != "unknown" else None,
            )
            report = (
                report_path.read_text(encoding="utf-8")
                if report_path is not None
                else content
            )
            updates["test_passed"] = parse_test_passed(report)

        return updates

    def _run_identify_intent(
        self,
        node_cfg: NodeConfig,
        docs_dir: Path,
        prompt: str,
    ) -> DevWorkflowState:
        """扫仓库并请用户确认。结论写入 intent/（本地不提交）并进入本次 state。"""
        result_path = _intent_result_path(docs_dir)
        result_path.parent.mkdir(parents=True, exist_ok=True)
        if result_path.exists():
            result_path.unlink()
        started = time.time()

        tool = get_ai_tool(node_cfg.tool)
        agent_cwd = self._agent_cwd(node_cfg.node_id)
        configured_model = (node_cfg.model or "").strip()
        effective_model = "" if node_cfg.tool == "echo" and configured_model else configured_model
        interactive = node_cfg.mode == "interactive"
        logger.info(
            "进入节点 [%s] (%s) tool=%s model=%s mode=%s",
            node_cfg.name,
            node_cfg.node_id,
            node_cfg.tool,
            effective_model or "(tool默认)",
            "interactive" if interactive else "headless",
        )
        if interactive and not sys.stdin.isatty():
            logger.warning("当前非 TTY 终端，交互模式可能无法正常输入")

        def confirmed() -> bool:
            return bool(_read_confirmed_intent(result_path, started))

        if interactive:
            result = tool.run_interactive(
                prompt=prompt,
                cwd=str(agent_cwd),
                completion_check=confirmed,
                node_id=node_cfg.node_id,
                prompt_dir=str(docs_dir),
                model=effective_model or None,
            )
            if not confirmed():
                logger.warning("节点 [%s] 交互已结束，但本次角色还未确认", node_cfg.name)
        else:
            result = tool.run(
                prompt=prompt,
                cwd=str(agent_cwd),
                node_id=node_cfg.node_id,
                prompt_dir=str(docs_dir),
                model=effective_model or None,
            )

        text = _read_confirmed_intent(result_path, started)
        if not text and result.content.strip():
            text = _confirmed_intent_text(result.content)
        if result_path.exists():
            result_path.unlink()

        if not text:
            return {
                "current_node": node_cfg.node_id,
                "intent_approved": False,
                "last_error": result.message or "意图未确认",
            }

        meta = parse_intent_metadata(text)
        branch = meta.git_branch.strip()
        if not branch:
            return {
                "current_node": node_cfg.node_id,
                "intent_approved": False,
                "last_error": "意图未写入 git_branch",
            }
        persist_intent(docs_dir, text)
        logger.info(
            "意图已确认：role=%s repos=%s branch=%s（已落盘 intent/，本地不提交）",
            meta.delivery_role,
            meta.involved_repos,
            branch,
        )
        return {
            "current_node": node_cfg.node_id,
            "completed_nodes": [node_cfg.node_id],
            "delivery_role": meta.delivery_role,
            "delivery_blocks": list(meta.delivery_blocks or []),
            "role_basis": meta.role_basis,
            "involved_repos": list(meta.involved_repos or []),
            "git_branch": branch,
            "git_base": meta.git_base,
            "intent_approved": True,
            "last_error": None,
        }

    def _build_completion_check(
        self,
        node_id: str,
        docs_dir: Path,
        state: DevWorkflowState,
        output_path: Path,
    ):
        if node_id in _PHASE_NODE_IDS:
            if node_id == "plan_session":
                return lambda: plan_session_complete(docs_dir, state)
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
            found = find_output(docs_dir, cfg.final_file)
            paths = [found] if found is not None else [output_path]

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
            and found is None
            and not output_path.exists()
            and body_content.strip()
            and _can_create_output(node_cfg.output_file, output_path)
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
        auto_mode = bool(state.get("auto"))

        phase_labels = {
            "analyze_requirements": "requirements",
            "identify_intent": "intent",
            "design_test_cases": "test_cases",
            "plan_session": "plan",
            "split_tasks": "tasks",
            "implement_code": "implement",
            "verify_tests": "verify",
            "ai_review": "ai_review",
            "commit_code": "commit",
        }
        phase = phase_labels.get(node_id, node_id)
        next_node = ""

        if node_id == "plan_session":
            ready = plan_session_complete(docs_dir, state)
            next_node = "split_tasks" if ready else "plan_session"
        elif node_id in PHASE_CONFIGS:
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

        if auto_mode and node_id == "analyze_requirements" and phase_complete(
            docs_dir, "analyze_requirements", state
        ):
            next_node = "identify_intent"

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
        return resolve_docs_path(
            resolve_project_docs_dir(app_root, self.workflow_config.project_docs_dir),
            docs_dir,
        )

    def _agent_cwd(self, node_id: str) -> Path:
        """这些节点在启动终端所在的业务项目根执行；其余在编排引擎根目录。"""
        if node_id in _APP_ROOT_NODES:
            return self.app_root
        return self.project_root

    def adopt_existing_output(self, node_id: str, state: DevWorkflowState) -> DevWorkflowState:
        """subagent 已经把文件写好时，补审批解析和 Workflow 状态，不再起 CLI。"""
        node_cfg = self.workflow_config.nodes[node_id]
        docs_dir = self._resolve_docs_dir(state)
        output_path = write_output_path(
            docs_dir, node_cfg.output_file, str(state.get("delivery_role") or "")
        )
        if not phase_content_ready(docs_dir, node_id, state):
            return {"last_error": f"{node_id} 产出未就绪（{output_path}）"}

        content = output_path.read_text(encoding="utf-8")
        app_root = resolve_app_root(
            self.project_root,
            state.get("app_root") or self.workflow_config.app_root,
        )
        rel = path_for_state(output_path, app_root)
        updates: DevWorkflowState = {
            "current_node": node_id,
            "node_outputs": {node_id: rel},
            "completed_nodes": [node_id],
        }
        updates.update(self._parse_node_outputs(node_id, content, docs_dir, state, output_path))
        merged = {**state, **updates}
        status = self._build_workflow_status(
            node_id, merged, docs_dir, success=True
        )
        result = AIToolResult(
            content=content,
            tool_name=node_cfg.tool,
            success=True,
            message="subagent 已写入",
        )
        self._finalize_headless_outputs(
            docs_dir,
            node_cfg,
            output_path=output_path,
            body_content=content,
            result=result,
            status=status,
        )
        return updates

    def _testcase_delegation_block(self, state: DevWorkflowState) -> str:
        docs_dir = self._resolve_docs_dir(state)
        output_label = output_hint(
            docs_dir, "02-test-cases.md", str(state.get("delivery_role") or "")
        )
        if phase_content_ready(docs_dir, "design_test_cases", state):
            return testcase_ready_note(output_label)

        tool_name = self.workflow_config.nodes["plan_session"].tool
        test_prompt = self._render_node_prompt("design_test_cases", state)
        prompt_file = save_node_prompt(
            test_prompt,
            str(self._agent_cwd("design_test_cases")),
            node_id="design_test_cases",
            prompt_dir=str(docs_dir),
        )
        return testcase_delegation(tool_name, prompt_file, output_label)

    def _render_node_prompt(self, node_id: str, state: DevWorkflowState) -> str:
        node_cfg = self.workflow_config.nodes[node_id]
        docs_dir = self._resolve_docs_dir(state)
        auto = bool(state.get("auto"))
        template = self._load_prompt(node_cfg.resolve_prompt_file(auto))
        return self._render_prompt(template, self._build_context(node_cfg, state, docs_dir))

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
            "output_path": output_hint(
                docs_dir, node_cfg.output_file, str(state.get("delivery_role") or "")
            ),
            "node_output_path": output_hint(
                docs_dir, node_cfg.output_file, str(state.get("delivery_role") or "")
            ),
            "output_plan": output_hint(docs_dir, "02-plan.md", str(state.get("delivery_role") or "")),
            "output_test_cases": output_hint(
                docs_dir, "02-test-cases.md", str(state.get("delivery_role") or "")
            ),
            "output_tasks": output_hint(
                docs_dir, "03-tasks.md", str(state.get("delivery_role") or "")
            ),
            "output_implementation": output_hint(
                docs_dir, "04-implementation.md", str(state.get("delivery_role") or "")
            ),
            "output_test_report": output_hint(
                docs_dir, "05-test-report.md", str(state.get("delivery_role") or "")
            ),
            "output_ai_review": output_hint(
                docs_dir, "06-ai-review.md", str(state.get("delivery_role") or "")
            ),
            "output_commit": output_hint(
                docs_dir, "07-commit.md", str(state.get("delivery_role") or "")
            ),
            "git_branch": str(state.get("git_branch") or ""),
            "git_base": str(state.get("git_base") or ""),
            "requirement_slug": str(state.get("requirement_slug") or docs_dir.name),
            "requirement_type": str(state.get("requirement_type") or ""),
            "role_scope": format_role_scope(
                str(state.get("delivery_role") or ""),
                list(state.get("delivery_blocks") or []),
                str(state.get("role_basis") or ""),
            ),
        }

        cfg = get_phase_config(node_cfg.node_id)
        role = str(state.get("delivery_role") or "")
        if cfg:
            context["final_output_path"] = output_hint(docs_dir, cfg.final_file, role)
        else:
            context["final_output_path"] = str(docs_dir / "01-requirements.md")
        context["intent_result_path"] = str(_intent_result_path(docs_dir))

        for inp in node_cfg.inputs:
            if inp.kind == "state":
                context[inp.key] = self._format_state_value(state.get(inp.key), inp.key)
            elif inp.kind == "doc":
                doc_path = resolve_doc_path(
                    docs_dir, inp.key, str(state.get("delivery_role") or "")
                )
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

        app_root_setting = state.get("app_root") or self.workflow_config.app_root
        app_root = resolve_app_root(self.project_root, app_root_setting)
        project_docs = resolve_project_docs_dir(
            app_root,
            self.workflow_config.project_docs_dir,
        )
        context.update(_intent_and_repo_context(state))
        involved_repos = state.get("involved_repos")
        metadata_present = involved_repos is not None
        references = materialize_rule_references(
            docs_dir,
            project_docs,
            list(node_cfg.extend_rules),
            involved_repos=list(involved_repos or []),
            restrict_to_involved=restrict_rules_to_involved(
                node_cfg.node_id, metadata_present
            ),
        )
        context["ai_rules"] = build_ai_rules_prompt(
            references,
            mode=rule_catalog_mode(node_cfg.node_id, metadata_present),
            involved_repos=list(involved_repos or []),
        )

        context["recommendation_threshold"] = str(
            node_cfg.recommendation_threshold
        )

        context["suggestion_confidence_rules"] = build_suggestion_confidence_prompt(
            self.workflow_config.suggestion_confidence_rules,
            node_cfg.node_id,
        )
        if node_cfg.node_id == "plan_session":
            context["subagent_delegation"] = self._testcase_delegation_block(state)

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
                        if raw.get("as_is"):
                            lines.append(f"  - 现状(AS-IS)：{raw['as_is']}")
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
            f"> AI 工具: `{node_cfg.tool}`"
            + (f" model=`{node_cfg.model}`" if node_cfg.model else "")
            + "\n"
            f"> 模式: `{node_cfg.mode}`\n"
            f"> 生成时间: {datetime.now().isoformat(timespec='seconds')}\n"
            f"> 执行状态: {'成功' if result.success else '需人工介入'}\n"
        )
        if result.message:
            header += f"> 备注: {result.message}\n"
        header += "\n---\n\n"
        return header + content

def _intent_result_path(docs_dir: Path) -> Path:
    return docs_dir / "temp-prompts" / "identify_intent.result.md"


def _intent_and_repo_context(state: DevWorkflowState) -> dict[str, str]:
    """计划提示词用的已确认分支与仓库列表。分支名不由引擎推荐。"""
    repos = state.get("involved_repos")
    if repos is None:
        repos_text = "（尚未确认）"
        repos_yaml = "  []"
    elif not repos:
        repos_text = "（无）"
        repos_yaml = "  []"
    else:
        repos_text = "、".join(str(item) for item in repos)
        repos_yaml = "\n".join(f"  - {item}" for item in repos)

    return {
        "involved_repos_text": repos_text,
        "involved_repos_yaml": repos_yaml,
        "git_branch": str(state.get("git_branch") or ""),
        "git_base": str(state.get("git_base") or ""),
    }


def _confirmed_intent_text(content: str) -> str:
    if not parse_intent_approval(content).is_approved:
        return ""
    meta = parse_intent_metadata(content)
    if meta.delivery_role not in ("backend", "frontend", "both"):
        return ""
    if meta.involved_repos is None:
        return ""
    if not meta.git_branch.strip():
        return ""
    return content


def _read_confirmed_intent(path: Path, started: float) -> str:
    if not path.is_file():
        return ""
    if path.stat().st_mtime + 1 < started:
        return ""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    return _confirmed_intent_text(text)


def _can_create_output(logical: str, path: Path) -> bool:
    """角色文件必须带后缀。角色还没定时，不要另写一份不带后缀的文件。"""
    if logical not in ROLE_SCOPED_OUTPUTS:
        return True
    return role_from_filename(path.name) is not None


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
