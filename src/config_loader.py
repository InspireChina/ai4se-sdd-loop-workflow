"""加载 workflow 与节点配置。"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .requirement_dir import resolve_app_root

logger = logging.getLogger(__name__)

# 业务项目根下的扩展配置目录（init 生成；运行时读 ai-rules + workflow 运行时项）
APP_CONFIG_DIR_NAME = "sdd-loop-workflow-config"
AI_RULES_CONFIG_FILENAME = "ai-rules.yaml"
APP_WORKFLOW_CONFIG_FILENAME = "workflow.yaml"
DEFAULT_AI_RULES_SUBDIR = "ai-rules"
DEFAULT_DOCS_DIR = "spec"
DEFAULT_APP_ROOT = ".."
DEFAULT_TOOL = "claude_code"
SUGGESTION_CONFIDENCE_RULES_FILENAME = "suggestion-confidence-rules.yaml"


@dataclass
class NodeInput:
    kind: str  # "state" | "doc"
    key: str


@dataclass
class NodeConfig:
    node_id: str
    name: str
    tool: str
    prompt_file: str
    output_file: str
    mode: str = "headless"  # headless | interactive
    # 无人值守（--auto）专用 prompt；缺省时与 prompt_file 相同
    prompt_file_auto: str = ""
    model: str = ""  # 空 = 该 tool 自带默认模型
    inputs: list[NodeInput] = field(default_factory=list)
    extend_rules: list[str] = field(default_factory=list)
    # 推荐强度阈值（0-1）：本节点 suggestion_confidence >= 该值时自动采纳推荐，不打断用户
    recommendation_threshold: float = 0.8

    def resolve_prompt_file(self, auto: bool) -> str:
        """按是否 --auto 选择人工介入 / 无人值守 prompt。"""
        if auto and self.prompt_file_auto:
            return self.prompt_file_auto
        return self.prompt_file


@dataclass
class ScoringRule:
    condition: str
    reason: str


@dataclass
class NodeScoringRules:
    node_id: str
    description: str
    high_confidence_rules: list[ScoringRule] = field(default_factory=list)
    low_confidence_rules: list[ScoringRule] = field(default_factory=list)


@dataclass
class WorkflowConfig:
    docs_dir: str
    nodes: dict[str, NodeConfig]
    ai_rules_dir: str = DEFAULT_AI_RULES_SUBDIR
    app_root: str = ".."
    default_tool: str = DEFAULT_TOOL
    default_model: str = ""
    suggestion_confidence_rules: dict[str, NodeScoringRules] = field(default_factory=dict)


def _parse_input(raw: dict[str, str]) -> NodeInput:
    if "state" in raw:
        return NodeInput(kind="state", key=raw["state"])
    if "doc" in raw:
        return NodeInput(kind="doc", key=raw["doc"])
    raise ValueError(f"Invalid node input config: {raw}")


def _parse_rule_list(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


def _as_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _pick_str(*candidates: Any) -> str:
    for item in candidates:
        text = _as_str(item)
        if text:
            return text
    return ""


def app_config_dir(app_root: Path) -> Path:
    """业务项目根下的 sdd-loop-workflow-config 目录。"""
    return app_root.resolve() / APP_CONFIG_DIR_NAME


def load_ai_rules_config(app_root: Path) -> tuple[str, dict[str, list[str]]]:
    """从业务根 sdd-loop-workflow-config/ai-rules.yaml 加载扩展规则映射。"""
    path = app_config_dir(app_root) / AI_RULES_CONFIG_FILENAME
    if not path.is_file():
        logger.warning(
            "未找到 %s，各节点将不注入扩展规则"
            "（请在业务项目根执行 sddl init）",
            path,
        )
        return DEFAULT_AI_RULES_SUBDIR, {}

    with open(path, encoding="utf-8") as f:
        data: dict[str, Any] = yaml.safe_load(f) or {}

    ai_rules_dir = (
        str(data.get("ai_rules_dir") or DEFAULT_AI_RULES_SUBDIR).strip()
        or DEFAULT_AI_RULES_SUBDIR
    )

    nodes_raw = data.get("nodes") or {}
    node_rules: dict[str, list[str]] = {}
    if isinstance(nodes_raw, dict):
        for node_id, raw in nodes_raw.items():
            rules = _parse_rule_list(raw)
            if rules:
                node_rules[str(node_id)] = rules

    return ai_rules_dir, node_rules


def _parse_scoring_rule(raw: Any) -> ScoringRule | None:
    if not isinstance(raw, dict):
        return None
    condition = _as_str(raw.get("condition"))
    if not condition:
        return None
    reason = _as_str(raw.get("reason"))
    return ScoringRule(condition=condition, reason=reason)


def _parse_node_scoring_rules(node_id: str, raw: Any) -> NodeScoringRules:
    if not isinstance(raw, dict):
        raw = {}
    high_confidence_rules: list[ScoringRule] = []
    for item in raw.get("high_confidence_rules") or []:
        rule = _parse_scoring_rule(item)
        if rule:
            high_confidence_rules.append(rule)
    low_confidence_rules: list[ScoringRule] = []
    for item in raw.get("low_confidence_rules") or []:
        rule = _parse_scoring_rule(item)
        if rule:
            low_confidence_rules.append(rule)
    return NodeScoringRules(
        node_id=node_id,
        description=_as_str(raw.get("description")),
        high_confidence_rules=high_confidence_rules,
        low_confidence_rules=low_confidence_rules,
    )


def _load_scoring_rules_file(path: Path) -> dict[str, NodeScoringRules]:
    if not path.is_file():
        return {}
    with open(path, encoding="utf-8") as f:
        data: dict[str, Any] = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        return {}
    nodes_raw = data.get("nodes") or {}
    if not isinstance(nodes_raw, dict):
        return {}
    result: dict[str, NodeScoringRules] = {}
    for node_id, raw in nodes_raw.items():
        result[str(node_id)] = _parse_node_scoring_rules(str(node_id), raw)
    return result


def load_suggestion_confidence_rules(
    app_root: Path, workflow_root: Path
) -> dict[str, NodeScoringRules]:
    """加载并合并 suggestion_confidence 把握规则：引擎基线 + 业务扩展。

    合并策略：high_confidence_rules / low_confidence_rules 均叠加到引擎基线
    之后（引擎通用 + 项目扩展）。业务文件缺失时仅用引擎基线。
    """
    engine_path = workflow_root / "config" / SUGGESTION_CONFIDENCE_RULES_FILENAME
    business_path = (
        app_config_dir(app_root) / SUGGESTION_CONFIDENCE_RULES_FILENAME
    )
    engine_rules = _load_scoring_rules_file(engine_path)
    business_rules = _load_scoring_rules_file(business_path)
    if not business_rules:
        return engine_rules

    merged: dict[str, NodeScoringRules] = {}
    all_node_ids = set(engine_rules) | set(business_rules)
    for node_id in all_node_ids:
        engine = engine_rules.get(node_id)
        business = business_rules.get(node_id)
        if engine and business:
            merged[node_id] = NodeScoringRules(
                node_id=node_id,
                description=business.description or engine.description,
                high_confidence_rules=[
                    *engine.high_confidence_rules,
                    *business.high_confidence_rules,
                ],
                low_confidence_rules=[
                    *engine.low_confidence_rules,
                    *business.low_confidence_rules,
                ],
            )
        else:
            merged[node_id] = (business or engine)  # type: ignore[arg-type]
    return merged


def load_app_runtime_settings(app_root: Path) -> dict[str, Any]:
    """从业务根 sdd-loop-workflow-config/workflow.yaml 读取运行时覆盖项。"""
    path = app_config_dir(app_root) / APP_WORKFLOW_CONFIG_FILENAME
    if not path.is_file():
        logger.warning(
            "未找到 %s，将使用引擎 config/workflow.yaml 中的兜底 docs_dir"
            "（请在业务项目根执行 sddl init）",
            path,
        )
        return {}

    with open(path, encoding="utf-8") as f:
        data: dict[str, Any] = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        return {}
    # 兼容误包一层 workflow:（保留顶层 defaults/nodes 以便覆盖）
    if "workflow" in data and isinstance(data["workflow"], dict):
        nested = dict(data["workflow"])
        for key in ("docs_dir", "app_root", "defaults", "nodes"):
            if key not in nested and key in data:
                nested[key] = data[key]
        return nested
    return data


def _resolve_node_tool_model(
    node_id: str,
    engine_cfg: dict[str, Any],
    *,
    engine_defaults: dict[str, Any],
    app_defaults: dict[str, Any],
    app_nodes: dict[str, Any],
) -> tuple[str, str]:
    """业务 nodes > 业务 defaults > 引擎 nodes > 引擎 defaults。"""
    app_node = app_nodes.get(node_id)
    if not isinstance(app_node, dict):
        app_node = {}

    tool = _pick_str(
        app_node.get("tool"),
        app_defaults.get("tool"),
        engine_cfg.get("tool"),
        engine_defaults.get("tool"),
        DEFAULT_TOOL,
    )
    model = _pick_str(
        app_node.get("model"),
        app_defaults.get("model"),
        engine_cfg.get("model"),
        engine_defaults.get("model"),
    )
    return tool, model


def load_workflow_config(config_path: Path) -> WorkflowConfig:
    with open(config_path, encoding="utf-8") as f:
        data: dict[str, Any] = yaml.safe_load(f)

    engine_workflow = data.get("workflow") or {}
    if not isinstance(engine_workflow, dict):
        engine_workflow = {}
    engine_defaults = data.get("defaults") or {}
    if not isinstance(engine_defaults, dict):
        engine_defaults = {}
    nodes_raw: dict[str, Any] = data["nodes"]

    # 先用引擎兜底 + 环境变量定位业务根，再读业务侧运行时配置覆盖
    fallback_app_root = (
        str(engine_workflow.get("app_root") or DEFAULT_APP_ROOT).strip() or DEFAULT_APP_ROOT
    )
    workflow_root = config_path.resolve().parent.parent
    resolved_app = resolve_app_root(workflow_root, fallback_app_root)
    app_settings = load_app_runtime_settings(resolved_app)

    docs_dir = str(
        app_settings.get("docs_dir")
        or engine_workflow.get("docs_dir")
        or DEFAULT_DOCS_DIR
    ).strip() or DEFAULT_DOCS_DIR

    app_defaults = app_settings.get("defaults") or {}
    if not isinstance(app_defaults, dict):
        app_defaults = {}
    app_nodes = app_settings.get("nodes") or {}
    if not isinstance(app_nodes, dict):
        app_nodes = {}

    default_tool = _pick_str(
        app_defaults.get("tool"),
        engine_defaults.get("tool"),
        DEFAULT_TOOL,
    )
    default_model = _pick_str(
        app_defaults.get("model"),
        engine_defaults.get("model"),
    )

    ai_rules_dir, node_extend_rules = load_ai_rules_config(resolved_app)

    suggestion_confidence_rules = load_suggestion_confidence_rules(
        resolved_app, workflow_root
    )

    nodes: dict[str, NodeConfig] = {}
    for node_id, cfg in nodes_raw.items():
        prompt = str(cfg["prompt"]).strip()
        prompt_auto = str(cfg.get("prompt_auto") or "").strip() or prompt
        tool, model = _resolve_node_tool_model(
            node_id,
            cfg,
            engine_defaults=engine_defaults,
            app_defaults=app_defaults,
            app_nodes=app_nodes,
        )
        node_threshold = _resolve_node_recommendation_threshold(
            node_id,
            app_nodes=app_nodes,
            engine_node_cfg=cfg,
        )
        nodes[node_id] = NodeConfig(
            node_id=node_id,
            name=cfg["name"],
            tool=tool,
            model=model,
            prompt_file=prompt,
            prompt_file_auto=prompt_auto,
            output_file=cfg["output"],
            mode=cfg.get("mode", "headless"),
            inputs=[_parse_input(i) for i in cfg.get("inputs", [])],
            extend_rules=node_extend_rules.get(node_id, []),
            recommendation_threshold=node_threshold,
        )

    if app_defaults.get("tool") or app_nodes:
        logger.info(
            "已合并业务侧 tool/model 覆盖（defaults.tool=%s, 节点覆盖数=%s）",
            app_defaults.get("tool") or "(无)",
            sum(
                1
                for nid, raw in app_nodes.items()
                if isinstance(raw, dict) and (raw.get("tool") or raw.get("model"))
            ),
        )

    return WorkflowConfig(
        docs_dir=docs_dir,
        ai_rules_dir=ai_rules_dir,
        # app_root 仍作引擎侧兜底；sddl:start 用环境变量覆盖
        app_root=fallback_app_root,
        nodes=nodes,
        default_tool=default_tool,
        default_model=default_model,
        suggestion_confidence_rules=suggestion_confidence_rules,
    )


def _resolve_node_recommendation_threshold(
    node_id: str,
    *,
    app_nodes: dict[str, Any],
    engine_node_cfg: dict[str, Any],
) -> float:
    """单节点阈值：业务节点 > 引擎节点 > 默认 0.8；clamp 到 [0, 1]。

    全局阈值已取消，每个节点在 ``nodes.<id>.recommendation_threshold`` 单独配置；
    未配置时回退到默认 0.8。
    """
    default = 0.8
    app_node = app_nodes.get(node_id)
    if not isinstance(app_node, dict):
        app_node = {}
    for raw in (app_node.get("recommendation_threshold"), engine_node_cfg.get("recommendation_threshold")):
        if raw is None:
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        return max(0.0, min(1.0, value))
    return default
