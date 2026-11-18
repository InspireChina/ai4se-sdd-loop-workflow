"""router：本地意图 02-intent-local.md 落盘与续跑。"""

from __future__ import annotations

from pathlib import Path

from src.router import (
    INTENT_FILENAME,
    clear_intent_cache,
    determine_start_node,
    intent_dir,
    intent_local_path,
    load_cached_intent,
    persist_intent,
)


def _approved_requirements() -> str:
    body = "\n".join(
        [
            "## 背景",
            "这是一段足够长的需求正文，用来满足阶段门禁对正文长度的要求。" * 3,
            "",
            "## 目标",
            "完成登录与权限相关能力，覆盖前后端协作场景中的关键路径。",
            "",
            "```yaml requirement_metadata",
            "requirement_type: new",
            "requirement_summary: 登录",
            "change_scope: auth",
            "affected_modules:",
            "  - auth",
            "compatibility_risk: low",
            "```",
            "",
            "```yaml requirement_approval",
            "status: approved",
            "confirmed_at: 2026-01-01T00:00:00",
            "user_note: ok",
            "```",
            "",
        ]
    )
    return body


def _intent_text(
    *,
    role: str = "backend",
    branch: str = "feature/login",
    approved: bool = True,
) -> str:
    blocks = (
        ["backend", "frontend"]
        if role == "both"
        else [role if role in ("backend", "frontend") else "backend"]
    )
    block_yaml = "\n".join(f"  - {item}" for item in blocks)
    status = "approved" if approved else "pending"
    return (
        f"```yaml intent_metadata\n"
        f"delivery_role: {role}\n"
        f"delivery_blocks:\n"
        f"{block_yaml}\n"
        f'role_basis: "test"\n'
        f"involved_repos:\n"
        f"  - services/demo\n"
        f"git_base: main\n"
        f"git_branch: {branch}\n"
        f"```\n\n"
        f"```yaml intent_approval\n"
        f"status: {status}\n"
        f"confirmed_at: 2026-01-01T00:00:00\n"
        f'user_note: "ok"\n'
        f"```\n"
    )


def _write_requirements(docs: Path) -> None:
    req = docs / "requirements"
    req.mkdir(parents=True, exist_ok=True)
    (req / "01-requirements.md").write_text(_approved_requirements(), encoding="utf-8")


def test_persist_and_load_cached_intent(tmp_path: Path) -> None:
    docs = tmp_path / "spec" / "demo"
    docs.mkdir(parents=True)
    text = _intent_text(role="backend")
    path = persist_intent(docs, text)
    assert path is not None
    assert path.name == INTENT_FILENAME
    assert path == intent_local_path(docs)
    assert (intent_dir(docs) / ".gitignore").is_file()

    cached = load_cached_intent(docs)
    assert cached is not None
    assert cached["delivery_role"] == "backend"
    assert cached["git_branch"] == "feature/login"
    assert cached["involved_repos"] == ["services/demo"]
    assert cached["intent_approved"] is True


def test_persist_overwrites_same_local_file(tmp_path: Path) -> None:
    docs = tmp_path / "spec" / "demo"
    docs.mkdir(parents=True)
    persist_intent(docs, _intent_text(role="backend", branch="b/be"))
    persist_intent(docs, _intent_text(role="frontend", branch="b/fe"))
    assert intent_local_path(docs).is_file()
    assert list(intent_dir(docs).glob("02-intent-*.md")) == [intent_local_path(docs)]
    cached = load_cached_intent(docs)
    assert cached is not None
    assert cached["delivery_role"] == "frontend"
    assert cached["git_branch"] == "b/fe"


def test_load_cached_intent_rejects_unapproved(tmp_path: Path) -> None:
    docs = tmp_path / "spec" / "demo"
    docs.mkdir(parents=True)
    persist_intent(docs, _intent_text(approved=False))
    assert load_cached_intent(docs) is None


def test_load_cached_intent_rejects_missing_branch(tmp_path: Path) -> None:
    docs = tmp_path / "spec" / "demo"
    docs.mkdir(parents=True)
    persist_intent(docs, _intent_text(branch=""))
    assert load_cached_intent(docs) is None


def test_clear_intent_cache(tmp_path: Path) -> None:
    docs = tmp_path / "spec" / "demo"
    docs.mkdir(parents=True)
    persist_intent(docs, _intent_text())
    clear_intent_cache(docs)
    assert load_cached_intent(docs) is None
    assert (intent_dir(docs) / ".gitignore").is_file()


def test_determine_start_node_uses_cache(tmp_path: Path) -> None:
    docs = tmp_path / "spec" / "demo"
    docs.mkdir(parents=True)
    _write_requirements(docs)
    persist_intent(docs, _intent_text(role="backend"))

    assert determine_start_node(docs, auto=False) == "plan_session"
    assert determine_start_node(docs, auto=True) == "plan_session"


def test_determine_start_node_without_cache(tmp_path: Path) -> None:
    docs = tmp_path / "spec" / "demo"
    docs.mkdir(parents=True)
    _write_requirements(docs)
    assert determine_start_node(docs, auto=False) == "identify_intent"


def test_determine_start_node_invalid_cache_falls_back(tmp_path: Path) -> None:
    docs = tmp_path / "spec" / "demo"
    docs.mkdir(parents=True)
    _write_requirements(docs)
    persist_intent(docs, _intent_text(approved=False))
    assert determine_start_node(docs, auto=False) == "identify_intent"
