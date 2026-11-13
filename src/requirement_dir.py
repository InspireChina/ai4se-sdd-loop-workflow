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
    base_docs_dir: str,
    requirement: str,
    *,
    docs_dir: str | None = None,
    name: str | None = None,
    source_file: Path | None = None,
) -> tuple[str, str]:
    """
    解析本次需求的产出目录。

    返回 (相对 app_root 的路径, requirement_slug)。
    默认结构: <app_root>/docs/<requirement-slug>/
    """
    app_root = app_root.resolve()

    if docs_dir:
        path = Path(docs_dir)
        if not path.is_absolute():
            path = app_root / path
        path.mkdir(parents=True, exist_ok=True)
        try:
            relative = str(path.relative_to(app_root))
        except ValueError:
            relative = str(path)
        slug = path.name
        return relative, slug

    slug = make_requirement_slug(
        requirement, name=name, source_file=source_file
    )
    base = Path(base_docs_dir)
    if base.is_absolute():
        target = base / slug
        relative = str(target)
    else:
        target = app_root / base / slug
        relative = str(base / slug)
    target.mkdir(parents=True, exist_ok=True)
    return relative, slug


def resolve_docs_path(app_root: Path, docs_dir: str) -> Path:
    """将 state/config 中的 docs_dir 解析为绝对路径。"""
    app_root = app_root.resolve()
    path = Path(docs_dir)
    if path.is_absolute():
        return path
    return (app_root / path).resolve()


def save_original_requirement(docs_dir: Path, requirement: str) -> Path:
    """将原始需求写入需求目录，便于追溯。"""
    docs_dir.mkdir(parents=True, exist_ok=True)
    path = docs_dir / "00-requirement.md"
    if not path.exists():
        path.write_text(requirement, encoding="utf-8")
    return path
