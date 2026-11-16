"""路径解析：应用项目根、docs 产出目录。"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path


def sanitize_slug(text: str, max_len: int = 60) -> str:
    """生成适合目录名的 slug（保留中文）。"""
    text = text.strip()
    text = re.sub(r"^#+\s*", "", text)
    text = text.lower()
    text = re.sub(r'[\\/:*?"<>|\s]+', "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-._")
    return text[:max_len].rstrip("-._")


def make_requirement_slug(
    requirement: str,
    *,
    name: str | None = None,
    source_file: Path | None = None,
) -> str:
    """推导本次运行对应的需求目录名。"""
    if name:
        slug = sanitize_slug(name)
        if slug:
            return slug

    if source_file is not None:
        stem = source_file.stem
        for suffix in ("-requirement", "_requirement", "-req", "_req"):
            if stem.lower().endswith(suffix):
                stem = stem[: -len(suffix)]
                break
        slug = sanitize_slug(stem)
        if slug:
            return slug

    for line in requirement.splitlines():
        line = line.strip()
        if not line:
            continue
        slug = sanitize_slug(line)
        if slug:
            return slug

    digest = hashlib.sha1(requirement.encode("utf-8")).hexdigest()[:8]
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"req-{stamp}-{digest}"


ORIGIN_REQUIREMENTS_DIRNAME = "origin_requirements"
SPEC_DIRNAME = "spec"


def workflow_local_config_file(app_root: Path) -> Path:
    return app_root.resolve() / "sdd-loop-workflow-config" / "workflow-local.yaml"


def locate_project_docs_dir(app_root: Path, project_docs_dir: str | None) -> Path | None:
    """把 project_docs_dir 解析成绝对路径。为空时返回 None，不检查目录是否存在。"""
    raw = (project_docs_dir or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = app_root.resolve() / path
    return path.resolve()


def project_docs_dir_with_legacy_project(project_docs_dir: str, project_name: str | None) -> str:
    """旧配置把项目目录拆在 project_name 时，拼回 project_docs_dir。"""
    root = (project_docs_dir or "").strip()
    name = (project_name or "").strip()
    if not name or name in {".", ".."} or "/" in name or "\\" in name:
        return root
    if not root or Path(root).name == name:
        return root
    return str(Path(root) / name)


def resolve_project_docs_dir(app_root: Path, project_docs_dir: str | None = None) -> Path:
    """项目文档目录，即团队共同文档仓下的 ``{project_name}``。

    相对路径相对业务根；绝对路径直接使用。为空或目录不存在时失败。
    """
    app_root = app_root.resolve()
    config_file = workflow_local_config_file(app_root)
    resolved = locate_project_docs_dir(app_root, project_docs_dir)
    if resolved is None:
        raise SystemExit(
            f"错误: {config_file} 的 project_docs_dir 为空。"
            "请填写团队共同文档仓下的项目目录（相对业务根或绝对路径），并确保该目录已存在。"
        )
    if not resolved.is_dir():
        raise SystemExit(
            f"错误: project_docs_dir 指向的目录不存在: {resolved}（配置于 {config_file}）"
        )
    return resolved


def origin_requirements_dir(project_docs_dir: Path) -> Path:
    return project_docs_dir / ORIGIN_REQUIREMENTS_DIRNAME


def spec_dir(project_docs_dir: Path) -> Path:
    return project_docs_dir / SPEC_DIRNAME


def path_for_state(path: Path, base: Path) -> str:
    """能落在 base 内就存相对路径，否则存绝对路径。"""
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(base.resolve()))
    except ValueError:
        return str(resolved)


def resolve_app_root(workflow_root: Path, app_root: str | None = None) -> Path:
    """
    应用项目根目录（业务代码与 docs 产出所在仓库根）。

    workflow_root: 编排仓库根目录（本仓库）
    app_root: 配置值，相对 workflow_root 或绝对路径；默认 ``..``（上级目录）

    若设置了环境变量 ``SDD_LOOP_WORKFLOW_APP_ROOT``（sddl:start 会写入运行时 cwd），
    则优先用它，便于在任意目录启动并绑定到当前业务项目。
    """
    import os

    override = (os.environ.get("SDD_LOOP_WORKFLOW_APP_ROOT") or "").strip()
    if override:
        return Path(override).expanduser().resolve()

    workflow_root = workflow_root.resolve()
    raw = (app_root or "..").strip() or ".."
    path = Path(raw)
    if not path.is_absolute():
        path = workflow_root / path
    return path.resolve()


def resolve_requirement_docs_dir(
    app_root: Path,
    requirement: str,
    *,
    docs_dir: str | None = None,
    name: str | None = None,
    source_file: Path | None = None,
    project_docs_dir: str | None = None,
) -> tuple[str, str]:
    """
    解析本次需求的产出目录。

    返回 (相对 project_docs_dir 的路径, requirement_slug)。
    默认结构: <project_docs_dir>/spec/<requirement-slug>/
    ``docs_dir`` 仅用于本次运行覆盖完整产出目录。
    """
    base_root = resolve_project_docs_dir(app_root, project_docs_dir)

    if docs_dir:
        path = Path(docs_dir).expanduser()
        if not path.is_absolute():
            path = base_root / path
        path.mkdir(parents=True, exist_ok=True)
        return path_for_state(path, base_root), path.name

    slug = make_requirement_slug(
        requirement, name=name, source_file=source_file
    )
    target = spec_dir(base_root) / slug
    target.mkdir(parents=True, exist_ok=True)
    return f"{SPEC_DIRNAME}/{slug}", slug


def resolve_docs_path(content_base: Path, docs_dir: str) -> Path:
    """将 state/config 中的 docs_dir 解析为绝对路径。

    ``content_base`` 是已解析的 ``project_docs_dir``。
    """
    content_base = content_base.resolve()
    path = Path(docs_dir).expanduser()
    if path.is_absolute():
        return path
    return (content_base / path).resolve()


def save_original_requirement(docs_dir: Path, requirement: str) -> Path:
    """将原始需求写入需求目录，便于追溯。"""
    docs_dir.mkdir(parents=True, exist_ok=True)
    path = docs_dir / "00-requirement.md"
    if not path.exists():
        path.write_text(requirement, encoding="utf-8")
    return path
