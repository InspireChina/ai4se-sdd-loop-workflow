"""按意图已确认的分支名，在业务仓库里检出工作分支。

不内置 feature/bugfix/hotfix 等推荐策略；分支名和基线由用户确认
（或项目 extend_rules 约定）后写入 state，这里只负责 checkout。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from .parsers.approval_parser import parse_plan_git_branch
from .role_output import find_output, list_role_outputs

_TRACK_ROLES = frozenset({"backend", "frontend", "both"})


class WorkBranchError(Exception):
    """工作分支没能检出。"""


def load_recorded_branch(docs_dir: Path, role: str = "") -> str:
    """续跑时读计划里已写下的工作分支。"""
    plans: list[Path] = []
    if role in _TRACK_ROLES:
        plan = find_output(docs_dir, "02-plan.md", role)
        if plan is not None:
            plans.append(plan)
    else:
        plans.extend(list_role_outputs(docs_dir, "02-plan.md"))
    for plan in plans:
        branch = parse_plan_git_branch(plan.read_text(encoding="utf-8"))
        if branch:
            return branch
    return ""


def normalize_work_branch(branch: str) -> str:
    """校验分支名可当作 git 引用，不做前缀策略限制。"""
    name = branch.strip().strip("/")
    if not name or name in {".", "..", "@"} or name.startswith("-"):
        raise WorkBranchError(f"工作分支名无效：{branch or '（空）'}")
    if any(token in name for token in ("..", "@{", " ", "~", "^", ":", "?", "*", "[", "\\")):
        raise WorkBranchError(f"工作分支名无效：{branch}")
    return name


def checkout_work_branch(repo: Path, branch: str, *, base: str = "") -> str:
    """检出分支。本地或 origin 已有就切过去，没有就按 base（若有）新建。

    返回 switched / created / current。
    """
    if _git(repo, "rev-parse", "--is-inside-work-tree").returncode != 0:
        raise WorkBranchError(f"业务项目根不是 git 仓库，没法检出工作分支 {branch}：{repo}")

    current = _git(repo, "branch", "--show-current").stdout.strip()
    if current == branch:
        return "current"

    if _has_ref(repo, f"refs/heads/{branch}"):
        _checkout(repo, branch, ["checkout", branch])
        return "switched"
    if _has_ref(repo, f"refs/remotes/origin/{branch}"):
        _checkout(repo, branch, ["checkout", "-b", branch, "--track", f"origin/{branch}"])
        return "switched"

    start_point = _resolve_start_point(repo, base)
    if start_point:
        _checkout(repo, branch, ["checkout", "-b", branch, start_point])
    else:
        _checkout(repo, branch, ["checkout", "-b", branch])
    return "created"


def _resolve_start_point(repo: Path, base: str) -> str:
    cleaned = base.strip().strip("/")
    if not cleaned:
        return ""
    if _has_ref(repo, f"refs/heads/{cleaned}"):
        return cleaned
    remote = f"origin/{cleaned}"
    if _has_ref(repo, f"refs/remotes/{remote}"):
        return remote
    return ""


def _has_ref(repo: Path, ref: str) -> bool:
    return _git(repo, "rev-parse", "--verify", "--quiet", ref).returncode == 0


def _checkout(repo: Path, branch: str, args: list[str]) -> None:
    proc = _git(repo, *args)
    if proc.returncode == 0:
        return
    detail = (proc.stderr or proc.stdout).strip()
    if "would be overwritten" in detail or "local changes" in detail or "Please commit" in detail:
        raise WorkBranchError(
            f"工作区有未提交改动，没法切到 {branch}。请先处理这些改动后再继续。"
        )
    raise WorkBranchError(f"没法检出工作分支 {branch}。{detail}")


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
