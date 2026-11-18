"""从测试报告计算 test_passed：优先读编排写入的 Workflow 状态表。"""

from __future__ import annotations

import re

from .approval_parser import read_approval_status
from .workflow_status_parser import parse_workflow_status

STATUS_HEADING = "## Workflow 状态"

_RESULT_HEADERS = frozenset({"结果", "判定", "结论", "result", "status"})
_PASSED_KEYS = frozenset({"testpassed", "测试通过", "测试结论"})

_PASS = frozenset({"pass", "passed", "ok", "yes", "true", "通过", "成功"})
_SKIP = frozenset({"skip", "skipped", "跳过"})
_FAIL = frozenset(
    {"fail", "failed", "false", "no", "失败", "未通过", "blocked", "block", "阻塞"}
)

_SEP = re.compile(r"^:?-{3,}:?$")
_MARKUP = re.compile(r"[*`_✅✔❌]")


def parse_test_passed(content: str) -> bool:
    """优先读文末 Workflow 状态表的 test_passed；尚无该字段时才看用例结果表。"""
    status = parse_workflow_status(content)
    if status is not None and status.test_passed is not None:
        return status.test_passed
    table = last_result_table(content)
    if not table:
        return False
    return _table_passed(table)


def has_test_result_table(content: str) -> bool:
    return last_result_table(content) is not None


def verify_report_ready(content: str) -> bool:
    """阶段 5 定稿完成：``test_report_approval.status == approved``，且有用例结果表。

    引擎以此自动退出交互 CLI 并进入下一节点；不再用字数/章节启发式。
    """
    body = _strip_workflow_status(content)
    if read_approval_status(body, "test_report_approval") != "approved":
        return False
    return has_test_result_table(body)


def last_result_table(content: str) -> list[list[str]] | None:
    tables = extract_markdown_tables(_strip_workflow_status(content))
    if not tables:
        return None
    table = tables[-1]
    if _is_result_table(table):
        return table
    return None


def extract_markdown_tables(content: str) -> list[list[list[str]]]:
    tables: list[list[list[str]]] = []
    current: list[list[str]] = []
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("|"):
            cells = [cell.strip() for cell in stripped.strip("|").split("|")]
            if cells and all(_SEP.match(cell.replace(" ", "") or "") for cell in cells):
                continue
            current.append(cells)
            continue
        if current:
            tables.append(current)
            current = []
    if current:
        tables.append(current)
    return tables


def _strip_workflow_status(content: str) -> str:
    return content.split(STATUS_HEADING, 1)[0]


def _norm_header(text: str) -> str:
    return _MARKUP.sub("", text).strip().lower()


def _norm_key(text: str) -> str:
    return re.sub(r"[\s_]+", "", _norm_header(text))


def _tokens(text: str) -> list[str]:
    cleaned = _MARKUP.sub("", text).strip().lower()
    cleaned = re.split(r"[/（(]", cleaned, 1)[0].strip()
    return [part for part in re.split(r"\s+", cleaned) if part]


def _classify(cell: str) -> str | None:
    raw = cell.strip()
    if not raw or raw in {"-", "—"}:
        return None
    if "❌" in raw:
        return "fail"
    tokens = _tokens(cell)
    joined = "".join(tokens)
    if joined in _FAIL or any(token in _FAIL for token in tokens):
        return "fail"
    if joined in _SKIP or any(token in _SKIP for token in tokens):
        return "skip"
    if joined in _PASS or any(token in _PASS for token in tokens) or "✅" in raw or "✔" in raw:
        return "pass"
    return None


def _header_index(headers: list[str], names: frozenset[str]) -> int | None:
    for idx, header in enumerate(headers):
        if _norm_header(header) in names:
            return idx
    return None


def _is_result_table(table: list[list[str]]) -> bool:
    if len(table) < 2:
        return False
    if _header_index(table[0], _RESULT_HEADERS) is not None:
        return True
    return any(_norm_key(row[0]) in _PASSED_KEYS for row in table[1:] if row)


def _table_passed(table: list[list[str]]) -> bool:
    headers = table[0]
    mapping = _key_value_mapping(table)
    for key in _PASSED_KEYS:
        if key in mapping:
            verdict = _classify(mapping[key])
            return verdict == "pass"

    result_idx = _header_index(headers, _RESULT_HEADERS)
    if result_idx is None:
        return False

    seen = False
    for row in table[1:]:
        if result_idx >= len(row):
            continue
        verdict = _classify(row[result_idx])
        if verdict is None:
            continue
        seen = True
        if verdict == "fail":
            return False
    return seen


def _key_value_mapping(table: list[list[str]]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for row in table[1:]:
        if len(row) < 2:
            continue
        mapping[_norm_key(row[0])] = row[1]
    return mapping
