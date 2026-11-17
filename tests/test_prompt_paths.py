"""提示词文档占位：已有文件只给相对路径，不内嵌正文。"""

from __future__ import annotations

from pathlib import Path

from src.nodes.node_runner import _format_doc_ref, _prompt_rel_path


def test_prompt_rel_path_under_cwd(tmp_path: Path) -> None:
    cwd = tmp_path / "app"
    target = cwd / "spec" / "demo" / "requirements" / "01-requirements.md"
    target.parent.mkdir(parents=True)
    target.write_text("x", encoding="utf-8")
    assert _prompt_rel_path(target, cwd) == "spec/demo/requirements/01-requirements.md"


def test_prompt_rel_path_outside_cwd_falls_back_to_absolute(tmp_path: Path) -> None:
    cwd = tmp_path / "app"
    cwd.mkdir()
    other = tmp_path / "elsewhere" / "file.md"
    other.parent.mkdir(parents=True)
    other.write_text("x", encoding="utf-8")
    assert _prompt_rel_path(other, cwd) == str(other.resolve())


def test_format_doc_ref_missing(tmp_path: Path) -> None:
    missing = tmp_path / "nope.md"
    assert _format_doc_ref(missing, tmp_path) == "（尚无此文件）"


def test_format_doc_ref_existing(tmp_path: Path) -> None:
    cwd = tmp_path / "app"
    doc = cwd / "plan" / "02-plan-backend.md"
    doc.parent.mkdir(parents=True)
    doc.write_text("# plan\n" + ("body\n" * 50), encoding="utf-8")
    ref = _format_doc_ref(doc, cwd)
    assert ref == "`plan/02-plan-backend.md`"
    assert "body" not in ref
