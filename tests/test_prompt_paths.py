"""提示词文档路径：相对 temp-prompts/（提示词所在目录），不内嵌正文、不用本机绝对路径。"""

from __future__ import annotations

from pathlib import Path

from src.agents.prompt_file import launch_read_prompt, prompt_display_path
from src.ai_rules_loader import build_ai_rules_prompt
from src.nodes.node_runner import _format_doc_ref, _prompt_rel_path


def test_prompt_rel_path_from_temp_prompts(tmp_path: Path) -> None:
    """从 temp-prompts/ 引用 requirements/ → ../requirements/..."""
    temp = tmp_path / "spec" / "demo" / "temp-prompts"
    req = tmp_path / "spec" / "demo" / "requirements" / "01-requirements.md"
    req.parent.mkdir(parents=True)
    temp.mkdir(parents=True)
    req.write_text("x", encoding="utf-8")
    assert _prompt_rel_path(req, temp) == "../requirements/01-requirements.md"


def test_prompt_rel_path_same_dir_is_filename(tmp_path: Path) -> None:
    plan_dir = tmp_path / "plan"
    plan = plan_dir / "02-plan-backend.md"
    plan_dir.mkdir(parents=True)
    plan.write_text("x", encoding="utf-8")
    assert _prompt_rel_path(plan, plan_dir) == "02-plan-backend.md"


def test_format_doc_ref_missing(tmp_path: Path) -> None:
    missing = tmp_path / "nope.md"
    assert _format_doc_ref(missing, tmp_path) == "（尚无此文件）"


def test_format_doc_ref_existing_from_temp_prompts(tmp_path: Path) -> None:
    docs = tmp_path / "spec" / "demo"
    temp = docs / "temp-prompts"
    doc = docs / "requirements" / "01-requirements.md"
    temp.mkdir(parents=True)
    doc.parent.mkdir(parents=True)
    doc.write_text("# req\n" + ("body\n" * 50), encoding="utf-8")
    ref = _format_doc_ref(doc, temp)
    assert ref == "`../requirements/01-requirements.md`"
    assert "body" not in ref


def test_launch_read_prompt_uses_cwd_relative_path(tmp_path: Path) -> None:
    cwd = tmp_path / "app"
    prompt_file = tmp_path / "docs" / "spec" / "demo" / "temp-prompts" / "x.prompt.md"
    prompt_file.parent.mkdir(parents=True)
    cwd.mkdir(parents=True)
    prompt_file.write_text("x", encoding="utf-8")
    text = launch_read_prompt(prompt_file, cwd=cwd)
    expected = prompt_display_path(prompt_file, cwd)
    assert expected in text
    assert "temp-prompts/" in text
    assert str(prompt_file.resolve()) not in text


def test_project_docs_rel_from_temp_prompts(tmp_path: Path) -> None:
    """从 temp-prompts/ 看 project_docs_dir → ../../..（不上本机绝对路径）。"""
    project_docs = tmp_path / "team-docs" / "proj"
    temp = project_docs / "spec" / "demo" / "temp-prompts"
    temp.mkdir(parents=True)
    assert _prompt_rel_path(project_docs, temp) == "../../.."


def test_ai_rules_write_back_uses_relative_project_docs() -> None:
    text = build_ai_rules_prompt([], project_docs_dir="../../..")
    assert "`../../../common_extend_rules/`" in text
    assert "`../../../repos/<仓库名>/extend_rules/`" in text
    assert "/Users/" not in text
    assert "project_docs_dir/common" not in text


def test_all_prompts_declare_temp_prompts_path_anchor() -> None:
    root = Path(__file__).resolve().parents[1] / "prompts"
    missing = [
        p.name
        for p in sorted(root.glob("*.md"))
        if "路径约定（必须遵守）" not in p.read_text(encoding="utf-8")
        or "temp-prompts/" not in p.read_text(encoding="utf-8")
    ]
    assert missing == []
