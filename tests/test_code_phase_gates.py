"""编码 → 测试 → AI Review → 提交：定稿 YAML 门禁。"""

from __future__ import annotations

from pathlib import Path

from src.phase_gate import phase_complete
from src.role_output import write_output_path
from src.router import _clamp_code_target


def _body(block: str, *, approved: bool) -> str:
    status = "approved" if approved else "pending"
    return f"""# Report

## Summary
done enough lines for gate

## Details
more detail here for length

```yaml {block}
status: {status}
confirmed_at: "2026-01-01T00:00:00Z"
user_note: "done"
```
"""


def _write(docs: Path, logical: str, block: str, *, approved: bool) -> None:
    path = write_output_path(docs, logical, "backend")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_body(block, approved=approved), encoding="utf-8")


def test_implement_ai_review_commit_gates(tmp_path: Path) -> None:
    docs = tmp_path / "spec" / "demo"
    state = {"delivery_role": "backend"}

    _write(docs, "04-implementation.md", "implementation_approval", approved=False)
    assert not phase_complete(docs, "implement_code", state)
    _write(docs, "04-implementation.md", "implementation_approval", approved=True)
    assert phase_complete(docs, "implement_code", state)

    _write(docs, "06-ai-review.md", "ai_review_approval", approved=False)
    assert not phase_complete(docs, "ai_review", state)
    _write(docs, "06-ai-review.md", "ai_review_approval", approved=True)
    assert phase_complete(docs, "ai_review", state)

    _write(docs, "07-commit.md", "commit_approval", approved=False)
    assert not phase_complete(docs, "commit_code", state)
    _write(docs, "07-commit.md", "commit_approval", approved=True)
    assert phase_complete(docs, "commit_code", state)


def test_clamp_blocks_skip_ahead(tmp_path: Path) -> None:
    docs = tmp_path / "spec" / "demo"
    _write(docs, "04-implementation.md", "implementation_approval", approved=False)
    assert _clamp_code_target(docs, "backend", "verify_tests") == "implement_code"
    assert _clamp_code_target(docs, "backend", "ai_review") == "implement_code"

    _write(docs, "04-implementation.md", "implementation_approval", approved=True)
    assert _clamp_code_target(docs, "backend", "verify_tests") == "verify_tests"
