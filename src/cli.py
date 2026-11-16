"""sddl 命令入口（macOS / Windows / Linux）。

  通用: sddl init | sddl start | sddl-init | sddl-start
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

SKILL_NAME = "start-workflow"
APP_CONFIG_DIR_NAME = "sdd-loop-workflow-config"
AI_RULES_SUBDIR = "ai-rules"
APP_WORKFLOW_CONFIG_FILENAME = "workflow-local.yaml"
SUGGESTION_CONFIDENCE_RULES_FILENAME = "suggestion-confidence-rules.yaml"

# 相对业务项目根 → (目录, --tool 取值)
AGENT_SKILL_DIRS = {
    "cursor": (".cursor/skills", "cursor"),
    "claude_code": (".claude/skills", "claude_code"),
    "codex": (".codex/skills", "codex"),
    "omp": (".omp/skills", "omp"),
}

USAGE = """\
用法（macOS / Windows / Linux 通用）:
  sddl init [--app-root DIR] [--workflow-root DIR]
  sddl start [start 脚本同样的选项...]
  sddl-init ...
  sddl-start ...
"""


def _engine_root() -> Path:
    return Path(__file__).resolve().parent.parent


def skill_template_path(engine: Path) -> Path:
    path = engine / "skills" / SKILL_NAME / "SKILL.md"
    if not path.is_file():
        raise SystemExit(f"错误: 找不到 skill 模板: {path}")
    return path


ENGINE_DIR_NAME = "ai4se-sdd-loop-workflow"


def _is_engine(path: Path) -> bool:
    return (path / "start.sh").is_file() and (path / "config" / "workflow.yaml").is_file()


def _pick_engine_among(candidates: list[Path]) -> Path | None:
    """从候选目录里选出唯一引擎；同名优先；多个无名冲突则报错。"""
    engines = [p.resolve() for p in candidates if p.is_dir() and _is_engine(p)]
    if not engines:
        return None
    if len(engines) == 1:
        return engines[0]
    preferred = [p for p in engines if p.name == ENGINE_DIR_NAME]
    if len(preferred) == 1:
        return preferred[0]
    listed = "\n".join(f"  - {p}" for p in engines)
    raise SystemExit(f"错误: 多个引擎目录，请用 --workflow-root:\n{listed}")


def find_engine_root(explicit: Path | None) -> Path:
    if explicit is not None:
        engine = explicit.expanduser().resolve()
        if not _is_engine(engine):
            raise SystemExit(f"错误: 不是 workflow 引擎目录: {engine}")
        return engine

    # editable / 源码运行：__file__ 就在引擎仓库内
    source = _engine_root()
    if _is_engine(source):
        return source

    cwd = Path.cwd().resolve()
    if _is_engine(cwd):
        return cwd

    # 业务项目根下嵌套 clone：<app>/ai4se-sdd-loop-workflow/
    found = _pick_engine_among(list(cwd.iterdir()))
    if found:
        return found

    # 与业务项目同级：<parent>/ai4se-sdd-loop-workflow/
    parent = cwd.parent
    sibling = parent / ENGINE_DIR_NAME
    if _is_engine(sibling):
        return sibling.resolve()
    found = _pick_engine_among(list(parent.iterdir()) if parent.is_dir() else [])
    if found:
        return found

    for ancestor in cwd.parents:
        if _is_engine(ancestor):
            return ancestor.resolve()
        named = ancestor / ENGINE_DIR_NAME
        if _is_engine(named):
            return named.resolve()

    raise SystemExit(
        "错误: 找不到 workflow 引擎，请传入 --workflow-root。\n"
        f"  例如: sddl init --workflow-root /path/to/{ENGINE_DIR_NAME}\n"
        "  提示: 若用 pip 非 editable 安装，代码在 site-packages，不会自动带上引擎仓库；"
        "请把引擎 clone 到业务项目内/同级，或显式指定路径。"
    )


def resolve_app_root(engine: Path, explicit: Path | None) -> Path:
    if explicit is not None:
        app_root = explicit.expanduser().resolve()
    else:
        # 与 start 一致：默认绑定运行时当前目录（业务项目根）
        app_root = Path.cwd().resolve()
    if not app_root.is_dir():
        raise SystemExit(f"错误: 业务项目根不存在: {app_root}")
    return app_root


def install_skills(engine: Path, app_root: Path) -> list[Path]:
    template = skill_template_path(engine).read_text(encoding="utf-8")
    written: list[Path] = []
    for _agent, (relative_dir, tool) in AGENT_SKILL_DIRS.items():
        dest = app_root / relative_dir / SKILL_NAME
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True)
        skill_file = dest / "SKILL.md"
        skill_file.write_text(template.format(tool=tool), encoding="utf-8")
        written.append(skill_file)
    return written


def _engine_app_config_template(engine: Path) -> Path:
    path = engine / "config" / APP_CONFIG_DIR_NAME
    if not path.is_dir():
        raise SystemExit(f"错误: 找不到配置模板目录: {path}")
    return path


def _load_yaml_mapping(path: Path) -> dict:
    if not path.is_file():
        return {}
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        return {}
    nested = data.get("workflow")
    if isinstance(nested, dict):
        merged = dict(nested)
        for key, value in data.items():
            if key not in merged:
                merged[key] = value
        return merged
    return data


def _is_ai_rules_markdown(rel: Path) -> bool:
    return bool(rel.parts) and rel.parts[0] == AI_RULES_SUBDIR


def _restore_yaml_scalar(path: Path, key: str, value: str) -> None:
    """把标量写回 workflow-local.yaml。"""
    text = path.read_text(encoding="utf-8")
    line = f"{key}: {json.dumps(value, ensure_ascii=False)}"
    if re.search(rf"(?m)^{re.escape(key)}\s*:", text):
        text = re.sub(rf"(?m)^{re.escape(key)}\s*:.*$", line, text, count=1)
    else:
        text = line + "\n" + text
    path.write_text(text, encoding="utf-8")


def _format_extend_rules_block(rules: list[str]) -> str:
    if not rules:
        return "    extend_rules: []"
    lines = ["    extend_rules:"]
    for item in rules:
        lines.append(f"      - {json.dumps(item, ensure_ascii=False)}")
    return "\n".join(lines)


def _restore_node_extend_rules(text: str, node_id: str, rules: list[str]) -> str:
    """把一个节点的 extend_rules 写回模板文本，保留文件里的注释。"""
    block = _format_extend_rules_block(rules)
    pattern = (
        rf"(?m)^(  {re.escape(node_id)}:\n(?:    (?!extend_rules:).*\n)*)"
        rf"    extend_rules:(?: \[])?(?:\n      - .*)*"
    )
    if re.search(pattern, text):
        return re.sub(pattern, rf"\g<1>{block}", text, count=1)
    insert_at = rf"(?m)^(  {re.escape(node_id)}:\n(?:    .*\n)*)"
    if re.search(insert_at, text):
        return re.sub(insert_at, rf"\g<1>{block}\n", text, count=1)
    return text


def _collect_extend_rules(current: dict) -> dict[str, list[str]]:
    """读出现有 workflow-local.yaml 里各节点的扩展规则路径。"""
    from .config_loader import node_extend_rules

    found: dict[str, list[str]] = {}
    nodes = current.get("nodes") or {}
    if not isinstance(nodes, dict):
        return found
    for node_id, raw in nodes.items():
        rules = node_extend_rules(raw)
        if rules:
            found[str(node_id)] = rules
    return found


def install_app_config(engine: Path, app_root: Path) -> list[str]:
    """在业务根同步 sdd-loop-workflow-config。

    ``suggestion-confidence-rules.yaml`` 保留不覆盖。
    规则 markdown 不写入业务项目。``workflow-local.yaml`` 覆盖为模板后，
    再写回 ``project_docs_dir`` 和各节点 ``extend_rules``。
    """
    src_root = _engine_app_config_template(engine)
    dest_root = app_root / APP_CONFIG_DIR_NAME
    dest_root.mkdir(parents=True, exist_ok=True)
    actions: list[str] = []
    preserve_names = {SUGGESTION_CONFIDENCE_RULES_FILENAME}

    for src in sorted(src_root.rglob("*")):
        if not src.is_file():
            continue
        rel = src.relative_to(src_root)
        if _is_ai_rules_markdown(rel):
            continue
        dest = dest_root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists() and dest.name in preserve_names:
            actions.append(f"跳过(保留项目配置): {dest}")
            continue
        existed = dest.exists()
        shutil.copy2(src, dest)
        actions.append(f"{'已覆盖' if existed else '已创建'}: {dest}")

    if not any(dest_root.rglob("*")):
        actions.append(f"已创建目录: {dest_root}")
    return actions


def _ask(prompt: str) -> str | None:
    if not sys.stdin.isatty():
        return None
    try:
        return input(prompt).strip()
    except EOFError:
        return None


def _workflow_local_path(app_root: Path) -> Path:
    return app_root / APP_CONFIG_DIR_NAME / APP_WORKFLOW_CONFIG_FILENAME


def configure_project_docs(app_root: Path, saved_project_docs_dir: str = "") -> list[str]:
    """只记录用户给出的 project_docs_dir，不创建文档目录。"""
    from .requirement_dir import locate_project_docs_dir

    workflow_path = _workflow_local_path(app_root)
    location = _ask(
        "请输入 project_docs_dir 地址（团队共享目录中的项目目录，不是共享目录本身）: "
    )
    if not location:
        if location is None and saved_project_docs_dir:
            _restore_yaml_scalar(workflow_path, "project_docs_dir", saved_project_docs_dir)
            return [f"已写回 project_docs_dir: {saved_project_docs_dir}"]
        if location is None:
            return ["提醒: 当前不是交互终端，project_docs_dir 为空，sddl start 会失败。"]
        if saved_project_docs_dir:
            _restore_yaml_scalar(workflow_path, "project_docs_dir", saved_project_docs_dir)
            return [f"已写回 project_docs_dir: {saved_project_docs_dir}"]
        return ["提醒: 未输入地址，project_docs_dir 为空，sddl start 会失败。"]

    _restore_yaml_scalar(workflow_path, "project_docs_dir", location)
    actions = [f"已写入 project_docs_dir: {location}"]
    path = locate_project_docs_dir(app_root, location)
    if path is not None and not path.is_dir():
        actions.append(f"提醒: 目录尚不存在: {path}。sddl start 前需要该目录已存在。")
    return actions


def command_init(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="sddl init",
        description=(
            "安装 start-workflow skill，并同步业务根 sdd-loop-workflow-config。"
            "并记录 project_docs_dir 地址"
        ),
    )
    parser.add_argument("--app-root", type=Path, default=None, help="业务项目根")
    parser.add_argument("--workflow-root", type=Path, default=None, help="引擎目录（含 start.sh）")
    args = parser.parse_args(argv)

    engine = find_engine_root(args.workflow_root)
    app_root = resolve_app_root(engine, args.app_root)
    from .requirement_dir import project_docs_dir_with_legacy_project

    workflow_path = _workflow_local_path(app_root)
    saved = _load_yaml_mapping(workflow_path)
    saved_rules = _collect_extend_rules(saved)
    saved_docs = str(saved.get("project_docs_dir") or saved.get("team_docs_dir") or "")
    saved_project_docs_dir = project_docs_dir_with_legacy_project(
        saved_docs,
        str(saved.get("project_name") or ""),
    )
    written = install_skills(engine, app_root)
    config_actions = install_app_config(engine, app_root)

    print(f"==> 引擎目录: {engine}")
    print(f"==> 业务项目根: {app_root}")
    for path in written:
        print(f"==> 已安装: {path}")
    for line in config_actions:
        print(f"==> {line}")

    for line in configure_project_docs(app_root, saved_project_docs_dir):
        print(f"==> {line}")
    if saved_rules and workflow_path.is_file():
        text = workflow_path.read_text(encoding="utf-8")
        for node_id, rules in saved_rules.items():
            text = _restore_node_extend_rules(text, node_id, rules)
        workflow_path.write_text(text, encoding="utf-8")
        print("==> 已写回各节点 extend_rules")
    return 0


def command_start(argv: list[str]) -> int:
    """转调引擎目录里的 start.sh / start.cmd。

    启动前把运行时 cwd 写入 SDD_LOOP_WORKFLOW_APP_ROOT，docs 产出落到该目录。

    依赖须已由 ``init_env`` 安装；start 脚本不会执行 pip install。
    """
    engine = find_engine_root(None)
    os.environ["SDD_LOOP_WORKFLOW_APP_ROOT"] = str(Path.cwd().resolve())

    if sys.platform == "win32":
        script = engine / "start.cmd"
        if not script.is_file():
            raise SystemExit(f"错误: 找不到 {script}")
        return subprocess.call(
            [str(script), *argv],
            cwd=str(engine),
            env=os.environ.copy(),
        )

    script = engine / "start.sh"
    if not script.is_file():
        raise SystemExit(f"错误: 找不到 {script}")
    if not os.access(script, os.X_OK):
        script.chmod(script.stat().st_mode | 0o111)
    os.execv(str(script), [str(script), *argv])
    return 1  # pragma: no cover


def main(argv: list[str] | None = None) -> None:
    if argv is None:
        argv = sys.argv[1:]
        invoked = Path(sys.argv[0]).name
    else:
        invoked = ""

    # 仅识别连字符入口（sddl-init.exe）；冒号入口已从 pyproject 移除（Windows 无法安装）
    if invoked.endswith("-init"):
        raise SystemExit(command_init(argv))
    if invoked.endswith("-start"):
        raise SystemExit(command_start(argv))

    if not argv or argv[0] in {"-h", "--help"}:
        print(USAGE, end="")
        raise SystemExit(0)

    if argv[0] == "init":
        raise SystemExit(command_init(argv[1:]))
    if argv[0] == "start":
        raise SystemExit(command_start(argv[1:]))

    print(f"错误: 未知命令 {argv[0]}\n", file=sys.stderr)
    print(USAGE, file=sys.stderr, end="")
    raise SystemExit(2)


if __name__ == "__main__":
    main()
