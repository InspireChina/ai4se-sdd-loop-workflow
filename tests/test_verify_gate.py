"""测试节点定稿门禁：认 test_report_approval，不认字数启发式。"""

from __future__ import annotations

from pathlib import Path

from src.parsers.test_report_parser import verify_report_ready
from src.phase_gate import phase_complete
from src.role_output import write_output_path


def _report_body(*, approved: bool) -> str:
    status = "approved" if approved else "pending"
    return f"""# 测试报告

## 执行环境
pytest

## 结果

| 用例编号 | 结果 |
|----------|------|
| TC-01 | pass |

```yaml test_report_approval
status: {status}
confirmed_at: "2026-01-01T00:00:00Z"
user_note: "stage5"
```
"""


def test_verify_report_ready_requires_approved_block() -> None:
    assert not verify_report_ready(_report_body(approved=False))
    assert verify_report_ready(_report_body(approved=True))


def test_verify_report_ready_requires_result_table() -> None:
    text = """# 测试报告

只有概述，没有结果表。

```yaml test_report_approval
status: approved
confirmed_at: "2026-01-01T00:00:00Z"
user_note: "stage5"
```
"""
    assert not verify_report_ready(text)


def test_phase_complete_verify_tests(tmp_path: Path) -> None:
    docs = tmp_path / "spec" / "demo"
    path = write_output_path(docs, "05-test-report.md", "backend")
    path.parent.mkdir(parents=True, exist_ok=True)
    state = {"delivery_role": "backend", "auto": False}

    path.write_text(_report_body(approved=False), encoding="utf-8")
    assert not phase_complete(docs, "verify_tests", state)

    path.write_text(_report_body(approved=True), encoding="utf-8")
    assert phase_complete(docs, "verify_tests", state)
