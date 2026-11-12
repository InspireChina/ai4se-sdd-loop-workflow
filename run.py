#!/usr/bin/env python3
"""运行 ai4se-sdd-loop-workflow 的 CLI 入口。"""

import argparse
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from src.workflow import DevWorkflow  # noqa: E402
from src.config_loader import load_workflow_config  # noqa: E402
from src.requirement_dir import resolve_app_root, resolve_docs_path  # noqa: E402


def main():
    load_dotenv(PROJECT_ROOT / ".env")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )

    parser = argparse.ArgumentParser(description="需求 → 代码 → 测试 工程化 Workflow")
    parser.add_argument(
        "requirement",
        nargs="?",
        help="原始需求描述（也可用 --file 传入）",
    )
    parser.add_argument(
        "--file", "-f",
        type=Path,
        help="从文件读取需求",
    )
    parser.add_argument(
        "--name", "-n",
        default=None,
        help="需求目录名（默认从文件名或需求首行推导），产出落在 <应用根>/<docs_dir>/<name>/",
    )
    parser.add_argument(
        "--docs-dir",
        default=None,
        help="覆盖完整产出目录（相对应用根或绝对路径；默认 <应用根>/<docs_dir>/<需求名>/）",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=PROJECT_ROOT / "config" / "workflow.yaml",
        help="workflow 配置文件路径",
    )
    parser.add_argument(
        "--tool",
        choices=["cursor", "claude_code", "codex", "oh_my_pi", "omp", "echo"],
        default=None,
        help=(
            "可选：覆盖所有节点的 AI 工具。"
            "不传则使用 sdd-loop-workflow-config/workflow.yaml 与引擎配置合并结果"
        ),
    )
    parser.add_argument(
        "--model",
        default=None,
        help=(
            "可选：覆盖所有节点的模型。"
            "不传则使用配置；配置的 model 若该 tool 不支持则降级为 tool 默认"
        ),
    )
    parser.add_argument(
        "--skip-clarification",
        action="store_true",
        help="跳过需求澄清 loop（适用于 echo 调试或非交互场景）",
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="无人值守：禁止向用户提问，内容就绪后自动过审批门禁（隐含 --skip-clarification）",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="清除该需求目录下已有产出（保留 00-requirement.md），从头开始",
    )
    args = parser.parse_args()
    wf_cfg = load_workflow_config(args.config)
    app_root = resolve_app_root(PROJECT_ROOT, wf_cfg.app_root)

    source_file = None
    requirement = None

    if args.file:
        source_file = args.file.resolve()
        requirement = source_file.read_text(encoding="utf-8")
    elif args.requirement:
        requirement = args.requirement
    elif args.name:
        existing = resolve_docs_path(
            app_root, f"{wf_cfg.docs_dir.strip('/')}/{args.name}"
        ) / "00-requirement.md"
        if existing.is_file():
            source_file = existing
            requirement = existing.read_text(encoding="utf-8")
            logging.info("从已有产出读取需求: %s", existing)

    if requirement is None:
        if args.name:
            named_sample = (
                app_root / wf_cfg.docs_dir / "requirements" / f"{args.name}-requirement.md"
            )
            if named_sample.is_file():
                source_file = named_sample
                requirement = named_sample.read_text(encoding="utf-8")
                logging.info("从 %s/requirements 读取需求: %s", wf_cfg.docs_dir, named_sample)

    if requirement is None:
        default_sample = app_root / wf_cfg.docs_dir / "requirements" / "jwt-login-requirement.md"
        if default_sample.is_file():
            source_file = default_sample
            requirement = default_sample.read_text(encoding="utf-8")
            logging.info("未传需求，使用默认: %s", default_sample)
        else:
            parser.error(
                "请提供 requirement、--file，或 --name"
                f"（且 {wf_cfg.docs_dir}/<name>/00-requirement.md 已存在）"
            )

    workflow = DevWorkflow(PROJECT_ROOT, args.config)

    if args.tool:
        for node in workflow.workflow_config.nodes.values():
            node.tool = args.tool
        logging.info("CLI --tool=%s 已覆盖全部节点", args.tool)
    if args.model is not None:
        model = args.model.strip()
        for node in workflow.workflow_config.nodes.values():
            node.model = model
        logging.info(
            "CLI --model=%s 已覆盖全部节点",
            model or "(空=各 tool 默认)",
        )

    result = workflow.run(
        requirement=requirement,
        docs_dir=args.docs_dir,
        name=args.name,
        source_file=source_file,
        skip_clarification=args.skip_clarification,
        auto=args.auto,
        fresh=args.fresh,
    )

    if not result.get("resume_from_node") and result.get("test_passed"):
        print("\n=== Workflow 已完成（无需续跑）===")
        print(f"需求目录: {result.get('docs_dir', '')}")
        return

    print("\n=== Workflow 完成 ===")
    print(f"需求目录: {result.get('docs_dir', '')}")
    print(f"需求 slug: {result.get('requirement_slug', '')}")
    print(f"启动节点: {result.get('resume_from_node', '')}")
    print(f"澄清轮次: {result.get('clarification_round', 0)}")
    print(f"澄清完成: {result.get('clarification_resolved', False)}")
    print(f"需求类型: {result.get('requirement_type', 'unknown')}")
    print(f"需求摘要: {result.get('requirement_summary', '')}")
    print(f"变更范围: {result.get('change_scope', '')}")
    print(f"影响模块: {result.get('affected_modules', [])}")
    print(f"兼容风险: {result.get('compatibility_risk', 'unknown')}")
    print(f"测试通过: {result.get('test_passed', False)}")
    print("产出文档:")
    for node_id, path in result.get("node_outputs", {}).items():
        print(f"  - [{node_id}] {path}")
    if result.get("last_error"):
        print(f"最后错误: {result['last_error']}")


if __name__ == "__main__":
    main()
