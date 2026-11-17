"""提示词文档路径：相对当前产出目录（可含 ..），不内嵌正文、不用本机绝对路径。"""

from __future__ import annotations

from pathlib import Path

from src.agents.prompt_file import launch_read_prompt
from src.ai_rules_loader import build_ai_rules_prompt
from src.nodes.node_runner import _format_doc_ref, _prompt_rel_path


def test_prompt_rel_path_sibling_stage(tmp_path: Path) -> None:
    """从 plan/ 引用 requirements/ → ../requirements/..."""
    plan_dir = tmp_path / "spec" / "demo" / "plan"
    req = tmp_path / "spec" / "demo" / "requirements" / "01-requirements.md"
    req.parent.mkdir(parents=True)
    plan_dir.mkdir(parents=True)
    req.write_text("x", encoding="utf-8")
    assert _prompt_rel_path(req, plan_dir) == "../requirements/01-requirements.md"


def test_prompt_rel_path_same_dir_is_filename(tmp_path: Path) -> None:
    plan_dir = tmp_path / "plan"
    plan = plan_dir / "02-plan-backend.md"
    plan_dir.mkdir(parents=True)
    plan.write_text("x", encoding="utf-8")
    assert _prompt_rel_path(plan, plan_dir) == "02-plan-backend.md"


def test_format_doc_ref_missing(tmp_path: Path) -> None:
    missing = tmp_path / "nope.md"
    assert _format_doc_ref(missing, tmp_path) == "（尚无此文件）"


def test_format_doc_ref_existing_from_plan(tmp_path: Path) -> None:
    docs = tmp_path / "spec" / "demo"
    plan_dir = docs / "plan"
    doc = docs / "requirements" / "01-requirements.md"
    plan_dir.mkdir(parents=True)
    doc.parent.mkdir(parents=True)
    doc.write_text("# req\n" + ("body\n" * 50), encoding="utf-8")
    ref = _format_doc_ref(doc, plan_dir)
    assert ref == "`../requirements/01-requirements.md`"
    assert "body" not in ref


def test_launch_read_prompt_uses_display_path(tmp_path: Path) -> None:
    prompt_file = tmp_path / "design_test_cases.prompt.md"
    prompt_file.write_text("x", encoding="utf-8")
    text = launch_read_prompt(
        prompt_file, display_path="../temp-prompts/design_test_cases.prompt.md"
    )
    assert "../temp-prompts/design_test_cases.prompt.md" in text
    assert str(prompt_file.resolve()) not in text


def test_project_docs_rel_from_plan_stage(tmp_path: Path) -> None:
    """从 plan/ 看 project_docs_dir → ../../..（不上本机绝对路径）。"""
    project_docs = tmp_path / "team-docs" / "proj"
    plan_dir = project_docs / "spec" / "demo" / "plan"
    plan_dir.mkdir(parents=True)
    assert _prompt_rel_path(project_docs, plan_dir) == "../../.."


def test_ai_rules_write_back_uses_relative_project_docs() -> None:
    text = build_ai_rules_prompt([], project_docs_dir="../../..")
    assert "`../../../common_extend_rules/`" in text
    assert "`../../../repos/<仓库名>/extend_rules/`" in text
    assert "/Users/" not in text
    assert "project_docs_dir/common" not in text
