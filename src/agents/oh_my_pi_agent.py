"""Oh My Pi (omp) AI 编程工具适配器。

CLI: https://omp.sh/
Headless: omp -p --auto-approve --no-session
Interactive: omp（可选初始 prompt）

Prompt 与 Cursor / Claude 相同：写入
`<应用根>/docs/<需求名>/temp-prompts/<node_id>.prompt.md`，
启动时只用短指令让工具 read 该文件（禁止 `@` 内联，以免超 Windows argv 上限）。
"""

from __future__ import annotations

import logging
import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path

from .base import AITool, AIToolResult, CompletionCheck
from .interactive_runner import run_interactive_subprocess
from .prompt_file import launch_read_prompt, save_node_prompt

logger = logging.getLogger(__name__)

_EXTRA_BIN_DIRS = (Path.home() / ".local" / "bin",)
_WORKING_LINE = re.compile(r"^Working\.+$")
_MIN_NODE_MAJOR = 18


class OhMyPiTool(AITool):
    name = "oh_my_pi"

    def run(
        self,
        prompt: str,
        cwd: str,
        *,
        node_id: str | None = None,
        prompt_dir: str | Path | None = None,
        model: str | None = None,
    ) -> AIToolResult:
        prompt_file = save_node_prompt(
            prompt, cwd, node_id=node_id, prompt_dir=prompt_dir
        )
        binary = self._resolve_binary()
        if not binary:
            return AIToolResult(
                content=self._fallback_content(prompt),
                tool_name=self.name,
                success=False,
                message=f"Oh My Pi CLI (omp) 不可用，prompt 已保存至 {prompt_file}",
            )

        cmd = self._build_cmd(
            binary, prompt_file, headless=True, cwd=cwd, model=model
        )
        self._log_launch_cmd(cmd)
        try:
            logger.info("调用 Oh My Pi CLI (headless): %s", binary)
            proc = subprocess.run(
                cmd,
                cwd=cwd,
                env=self._subprocess_env(),
                capture_output=True,
                text=True,
                timeout=620,
                check=False,
            )
            content = self._extract_content(proc.stdout)
            if proc.returncode == 0 and content:
                return AIToolResult(
                    content=content,
                    tool_name=self.name,
                    success=True,
                )
            stderr = (proc.stderr or "").strip()
            if stderr:
                logger.warning("Oh My Pi CLI stderr: %s", stderr[:500])
            message = stderr or f"Oh My Pi CLI 退出码 {proc.returncode}"
            return AIToolResult(
                content=content or self._fallback_content(prompt),
                tool_name=self.name,
                success=False,
                message=message,
            )
        except subprocess.TimeoutExpired:
            return AIToolResult(
                content="",
                tool_name=self.name,
                success=False,
                message="Oh My Pi CLI 执行超时",
            )

    def run_interactive(
        self,
        prompt: str,
        cwd: str,
        *,
        completion_check: CompletionCheck | None = None,
        node_id: str | None = None,
        prompt_dir: str | Path | None = None,
        model: str | None = None,
    ) -> AIToolResult:
        prompt_file = save_node_prompt(
            prompt, cwd, node_id=node_id, prompt_dir=prompt_dir
        )
        binary = self._resolve_binary()
        if not binary:
            return AIToolResult(
                content="",
                tool_name=self.name,
                success=False,
                message=f"Oh My Pi CLI (omp) 不可用，prompt 已保存至 {prompt_file}",
            )

        cmd = self._build_cmd(
            binary, prompt_file, headless=False, cwd=cwd, model=model
        )
        self._log_launch_cmd(cmd)
        try:
            logger.info("交互调用 Oh My Pi CLI: %s", binary)
            return run_interactive_subprocess(
                cmd,
                cwd,
                tool_name=self.name,
                banner_title="进入 Oh My Pi (omp) 交互会话",
                completion_hint="产出文件写入后将自动退出并继续 workflow",
                completion_check=completion_check,
                env=self._subprocess_env(),
            )
        except FileNotFoundError:
            return AIToolResult(
                content="",
                tool_name=self.name,
                success=False,
                message=f"Oh My Pi CLI (omp) 不可用，prompt 已保存至 {prompt_file}",
            )

    @classmethod
    def _build_cmd(
        cls,
        binary: str,
        prompt_file: Path,
        *,
        headless: bool,
        cwd: str,
        model: str | None = None,
    ) -> list[str]:
        cmd: list[str] = [binary]
        project_root = cls._resolve_omp_project_root(cwd)
        if project_root is not None:
            cmd.extend(["--cwd", str(project_root)])
        config_overlay = cls._resolve_omp_config_overlay(cwd, project_root)
        if config_overlay:
            cmd.extend(["--config", config_overlay])
        if headless:
            cmd.extend(
                [
                    "-p",
                    "--auto-approve",
                    "--no-session",
                    "--mode",
                    "text",
                    "--max-time",
                    "600",
                ]
            )
        else:
            cmd.append("--auto-approve")
        cmd.extend(cls.model_cli_flags(model))
        cmd.append(cls._launch_prompt(prompt_file))
        return cmd

    @staticmethod
    def _launch_prompt(prompt_file: Path) -> str:
        return launch_read_prompt(prompt_file)

    @staticmethod
    def _log_launch_cmd(cmd: list[str]) -> None:
        rendered = " ".join(shlex.quote(part) for part in cmd)
        logger.info("Oh My Pi 启动命令: %s", rendered)
        print(f"[omp] 启动命令:\n  {rendered}\n", flush=True)

    @classmethod
    def _resolve_omp_project_root(cls, cwd: str) -> Path | None:
        for candidate in cls._omp_search_roots(Path(cwd).resolve()):
            if (candidate / ".omp" / "mcp.json").is_file():
                return candidate.resolve()
        return None

    @classmethod
    def _resolve_omp_config_overlay(
        cls, cwd: str, project_root: Path | None = None
    ) -> str | None:
        roots: list[Path] = []
        if project_root is not None:
            roots.append(project_root)
        roots.extend(cls._omp_search_roots(Path(cwd).resolve()))
        seen: set[str] = set()
        for root in roots:
            root_key = str(root)
            if root_key in seen:
                continue
            seen.add(root_key)
            for candidate in (
                root / ".omp" / "config.yml",
                root / "config" / "omp-workflow.yaml",
            ):
                if candidate.is_file():
                    return str(candidate.resolve())
        return None

    @staticmethod
    def _omp_search_roots(base: Path) -> list[Path]:
        """cwd、一层子目录、再向上，不依赖编排目录的固定名字。"""
        roots: list[Path] = [base]
        if base.is_dir():
            for child in sorted(base.iterdir()):
                if child.is_dir() and not child.name.startswith("."):
                    roots.append(child)
        roots.extend(base.parents)
        return roots

    @classmethod
    def _subprocess_env(cls) -> dict[str, str]:
        env = os.environ.copy()
        env.setdefault("OMP_MCP_TIMEOUT_MS", "120000")
        node_bin = cls._resolve_node_bin_dir()
        if node_bin:
            env["PATH"] = f"{node_bin}{os.pathsep}{env.get('PATH', '')}"
        return env

    @classmethod
    def _resolve_node_bin_dir(cls) -> str | None:
        major = cls._node_major_version()
        if major >= _MIN_NODE_MAJOR:
            node = shutil.which("node")
            return str(Path(node).parent) if node else None

        nvm_sh = Path.home() / ".nvm" / "nvm.sh"
        if not nvm_sh.is_file():
            return None
        try:
            proc = subprocess.run(
                ["bash", "-lc", f"source {nvm_sh} && nvm use 20 >/dev/null 2>&1 || nvm use 18 >/dev/null 2>&1; dirname \"$(command -v node)\""],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None
        path = (proc.stdout or "").strip().splitlines()
        if not path:
            return None
        node_dir = path[-1].strip()
        return node_dir or None

    @staticmethod
    def _node_major_version() -> int:
        if not shutil.which("node"):
            return 0
        try:
            proc = subprocess.run(
                ["node", "-p", "process.versions.node.split('.')[0]"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            return int((proc.stdout or "0").strip() or "0")
        except (ValueError, subprocess.TimeoutExpired):
            return 0

    @classmethod
    def _resolve_binary(cls) -> str | None:
        search_path = os.environ.get("PATH", "")
        for extra in _EXTRA_BIN_DIRS:
            if extra.is_dir():
                search_path = f"{extra}{os.pathsep}{search_path}"
        for name in ("omp", "oh-my-pi"):
            path = shutil.which(name, path=search_path)
            if path:
                return path
        return None

    @classmethod
    def _extract_content(cls, stdout: str) -> str:
        lines: list[str] = []
        for line in stdout.splitlines():
            stripped = line.strip()
            if not stripped or _WORKING_LINE.match(stripped):
                continue
            lines.append(line.rstrip())
        return "\n".join(lines).strip()

    @staticmethod
    def _fallback_content(prompt: str) -> str:
        return (
            "# Oh My Pi 工具未就绪\n\n"
            "> 请安装 omp CLI（https://omp.sh/）并配置认证后重试，或手动执行以下 prompt。\n\n"
            "---\n\n"
            f"{prompt}"
        )
