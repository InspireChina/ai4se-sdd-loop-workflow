"""把本节点配置、且属于涉及仓库的扩展规则复制到 temp-prompts/references。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

COMMON_RULES_DIRNAME = "common_extend_rules"
REPOS_DIRNAME = "repos"
EXTEND_RULES_DIRNAME = "extend_rules"
TEMP_PROMPT_DIR = "temp-prompts"
REFERENCES_DIRNAME = "references"

PLAN_NODE_ID = "plan_session"


def _involved_matches_repo(repo_name: str, involved_repos: list[str]) -> bool:
    """involved_repos 是相对 app_root 的路径；规则目录名用最后一段匹配。"""
    if not repo_name:
        return False
    for raw in involved_repos:
        text = str(raw).strip().replace("\\", "/").strip("/")
        if not text or text == ".":
            continue
        if text == repo_name or text.endswith("/" + repo_name) or Path(text).name == repo_name:
            return True
    return False


POST_PLAN_NODE_IDS = frozenset(
    {
        "split_tasks",
        "implement_code",
        "verify_tests",
        "ai_review",
        "commit_code",
    }
)


@dataclass(frozen=True)
class RuleReference:
    """一条已复制到 temp-prompts/references 的规则。"""

    relative_path: str
    kind: str
    repo_name: str


def _reference_name(prefix: str, rules_root: Path, src: Path) -> str:
    rel = src.relative_to(rules_root)
    return prefix + "_" + "_".join(rel.parts)


def _classify_rule(project_docs_dir: Path, src: Path) -> tuple[str, str, Path] | None:
    """返回 (引用文件名, kind, repo_name)。不在公共或仓库规则目录里的文件忽略。"""
    common = project_docs_dir / COMMON_RULES_DIRNAME
    repos = project_docs_dir / REPOS_DIRNAME
    try:
        src.relative_to(common)
    except ValueError:
        pass
    else:
        return _reference_name("common", common, src), "common", ""
    try:
        rel = src.relative_to(repos)
    except ValueError:
        return None
    if len(rel.parts) < 3 or rel.parts[1] != EXTEND_RULES_DIRNAME:
        return None
    rules_root = repos / rel.parts[0] / EXTEND_RULES_DIRNAME
    return _reference_name(rel.parts[0], rules_root, src), "repo", rel.parts[0]


def _locate_configured_rule(project_docs_dir: Path, raw: str) -> list[Path]:
    """把 workflow-local.yaml 里的一条扩展规则路径解析成项目文档目录下的文件。"""
    text = raw.strip().lstrip("/")
    if not text:
        return []
    found: list[Path] = []
    direct = project_docs_dir / text
    if direct.is_file():
        found.append(direct)
    parts = Path(text).parts
    if parts and parts[0] == project_docs_dir.name and len(parts) > 1:
        trimmed = project_docs_dir.joinpath(*parts[1:])
        if trimmed.is_file():
            found.append(trimmed)
    for marker in (f"{REPOS_DIRNAME}/", f"{COMMON_RULES_DIRNAME}/"):
        index = text.find(marker)
        if index < 0:
            continue
        suffix = project_docs_dir / text[index:]
        if suffix.is_file():
            found.append(suffix)
    if not found and "/" not in text and "\\" not in text:
        common = project_docs_dir / COMMON_RULES_DIRNAME
        if common.is_dir():
            found.extend(path for path in common.rglob(text) if path.is_file())
        repos = project_docs_dir / REPOS_DIRNAME
        if repos.is_dir():
            for repo_dir in sorted(path for path in repos.iterdir() if path.is_dir()):
                rules = repo_dir / EXTEND_RULES_DIRNAME
                if rules.is_dir():
                    found.extend(path for path in rules.rglob(text) if path.is_file())
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in found:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(path)
    return unique


def select_node_rule_files(
    project_docs_dir: Path,
    configured_paths: list[str],
    *,
    involved_repos: list[str] | None,
    restrict_to_involved: bool,
) -> list[tuple[str, str, str, Path]]:
    """节点配置的规则，计划之后再按涉及仓库过滤。

    公共规则只要配在该节点上就保留。仓库规则在 ``restrict_to_involved`` 时
    还得属于 ``involved_repos``。
    """
    involved = list(involved_repos or [])
    selected: list[tuple[str, str, str, Path]] = []
    seen: set[Path] = set()
    for raw in configured_paths:
        matches = _locate_configured_rule(project_docs_dir, raw)
        if not matches:
            logger.warning("节点扩展规则未找到: %s", raw)
            continue
        for src in matches:
            classified = _classify_rule(project_docs_dir, src)
            if classified is None:
                logger.warning("节点扩展规则不在公共或仓库规则目录: %s", src)
                continue
            name, kind, repo_name = classified
            if kind == "repo" and restrict_to_involved and not _involved_matches_repo(
                repo_name, involved
            ):
                continue
            resolved = src.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            selected.append((name, kind, repo_name, src))
    return selected


def materialize_rule_references(
    docs_dir: Path,
    project_docs_dir: Path,
    configured_paths: list[str],
    *,
    involved_repos: list[str] | None = None,
    restrict_to_involved: bool = False,
) -> list[RuleReference]:
    """只复制本节点要读的规则到 ``temp-prompts/references/``。"""
    ref_dir = docs_dir / TEMP_PROMPT_DIR / REFERENCES_DIRNAME
    ref_dir.mkdir(parents=True, exist_ok=True)

    written: list[RuleReference] = []
    for name, kind, repo_name, src in select_node_rule_files(
        project_docs_dir,
        configured_paths,
        involved_repos=involved_repos,
        restrict_to_involved=restrict_to_involved,
    ):
        dest = ref_dir / name
        dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        written.append(
            RuleReference(
                relative_path=f"{REFERENCES_DIRNAME}/{name}",
                kind=kind,
                repo_name=repo_name,
            )
        )
    return written


def restrict_rules_to_involved(node_id: str, plan_metadata_present: bool) -> bool:
    """意图已确认涉及仓库后：计划及之后的节点，仓库规则还得属于 involved_repos。"""
    if node_id == PLAN_NODE_ID:
        return plan_metadata_present
    if node_id in POST_PLAN_NODE_IDS:
        return True
    return node_id == "design_test_cases" and plan_metadata_present


def rule_catalog_mode(node_id: str, plan_metadata_present: bool) -> str:
    """按节点决定仓库规则目录怎么列。

    discover：计划节点且意图还没写下涉及仓库时的兜底。
    scoped：意图/计划已写明涉及仓库，只列这些仓库。
    unset：还没有涉及仓库名单，后续节点只列公共规则。
    common_only：计划之前的节点，只列公共规则。
    """
    if node_id == PLAN_NODE_ID:
        return "scoped" if plan_metadata_present else "discover"
    if node_id in POST_PLAN_NODE_IDS:
        return "scoped" if plan_metadata_present else "unset"
    if node_id == "design_test_cases" and plan_metadata_present:
        return "scoped"
    return "common_only"


def build_ai_rules_prompt(
    references: list[RuleReference],
    *,
    mode: str = "common_only",
    involved_repos: list[str] | None = None,
    project_docs_dir: Path | str | None = None,
) -> str:
    """主 prompt 里只列出该读的 references 文件，正文不写入。

    ``project_docs_dir`` 应为相对本提示词所在 ``temp-prompts/`` 的路径（如 ``../../..``），
    不要传本机绝对路径。
    """
    involved = list(involved_repos or [])
    if project_docs_dir:
        docs_root = str(project_docs_dir).replace("\\", "/").rstrip("/")
        write_back = (
            f"要修改规则时，写回 `{docs_root}/common_extend_rules/` "
            f"或 `{docs_root}/repos/<仓库名>/extend_rules/`，"
            "不要只改 references 里的副本。"
        )
    else:
        write_back = (
            "要修改规则时，写回项目文档目录下的 `common_extend_rules/` "
            "或 `repos/<仓库名>/extend_rules/`，不要只改 references 里的副本。"
        )
    lines = [
        "扩展规则在本提示词同级的 `references/`，正文没有写进本文件。",
        write_back,
        "",
    ]
    if mode == "discover":
        lines.extend(
            [
                "下面只列出本节点配置的规则。先判断本次要改哪些仓库，再只打开这些仓库的文件。候选不要一次读完。",
                "`common_` 开头是公共规则，遵守项目约束前读取。",
                "定稿时把涉及仓库写入本次计划文件的 `plan_metadata.involved_repos`（相对 `app_root` 的路径，意图已确认则原样透传）。",
                "没有要改的仓库就写空列表。后续节点只在本节点也配置了该规则、且仓库在这份名单里时才读取。",
                "",
            ]
        )
    elif mode == "scoped":
        listed = "、".join(involved) if involved else "（无）"
        lines.extend(
            [
                f"本次涉及的仓库已确认：{listed}。",
                "下面只列出本节点配置、且属于这些仓库的规则。只打开这些文件。",
                "",
            ]
        )
    elif mode == "unset":
        lines.extend(
            [
                "计划还没有 `plan_metadata.involved_repos`。本节点只读取已配置的公共规则。",
                "不要打开仓库规则。",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "下面只列出本节点配置的规则。只打开这些文件。",
                "计划写入 `plan_metadata.involved_repos` 之后，后续节点还要再按涉及仓库过滤。",
                "",
            ]
        )

    commons = [item.relative_path for item in references if item.kind == "common"]
    lines.append("公共规则：")
    if commons:
        lines.extend(f"- `{path}`" for path in commons)
    else:
        lines.append("- （无）")
    lines.append("")

    if mode == "unset":
        return "\n".join(lines)

    repo_paths: dict[str, list[str]] = {}
    for item in references:
        if item.kind == "repo":
            repo_paths.setdefault(item.repo_name, []).append(item.relative_path)

    if mode == "discover":
        lines.append("候选仓库（判定本次要改之前不要打开）：")
        if not repo_paths:
            lines.append("- （无）")
        else:
            for repo_name, paths in repo_paths.items():
                lines.append(f"- {repo_name}：")
                lines.extend(f"  - `{path}`" for path in paths)
        lines.extend(
            [
                "",
                "```yaml plan_metadata",
                "involved_repos:",
                "  - <仓库名>",
                "```",
            ]
        )
        return "\n".join(lines)

    heading = "候选仓库（判定本次要改之前不要打开）：" if mode == "discover" else "本次仓库规则："
    lines.append(heading)
    if not repo_paths:
        lines.append("- （无）")
        return "\n".join(lines)
    for repo_name, paths in repo_paths.items():
        lines.append(f"- {repo_name}：")
        lines.extend(f"  - `{path}`" for path in paths)
    return "\n".join(lines)
