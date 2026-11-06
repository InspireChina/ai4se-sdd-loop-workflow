#!/usr/bin/env bash
# start.sh — 创建虚拟环境、安装依赖并启动 ai4se-sdd-loop-workflow
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV_DIR="${VENV_DIR:-.venv}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

# ---------- helpers ----------
usage() {
  cat <<'EOF'
用法:
  ./start.sh [选项] [需求描述]
  ./start.sh [选项] --file <需求文件>
  Windows: .\\start.cmd [同样选项]

选项:
  -f, --file PATH     从文件读取需求（推荐）
  -n, --name NAME     需求目录名，产出落在 <应用根>/spec/<NAME>/（docs_dir 可配）
  -t, --tool TOOL     可选，覆盖全部节点 AI 工具: cursor | claude_code | codex | omp | echo
  --model MODEL       可选，覆盖全部节点模型（不支持则降级为 tool 默认）
  -d, --docs-dir DIR  覆盖完整产出目录（相对应用根或绝对路径）
  --skip-clarification  跳过需求澄清 loop（echo 调试 / CI）
  --auto                无人值守：禁止向用户提问，内容就绪后自动过门禁
  --fresh               清除已有产出（保留 00-requirement.md）后重来
  -h, --help          显示帮助

依赖安装请用 ./init_env.sh，本脚本不会执行 pip install。

示例:
  # 调试：不调真实 AI，只跑通编排
  # 产出在 <应用根>/spec/<name>/（非本仓库内；docs_dir 默认 spec）
  ./start.sh --tool echo --skip-clarification --file ../spec/requirements/jwt-login-requirement.md --name jwt-login

  # 指定需求目录名
  ./start.sh --name jwt-login --file ../spec/requirements/jwt-login-requirement.md

  # 续跑：已有 spec/jwt-login/00-requirement.md 时可只传 --name
  ./start.sh --name jwt-login

  # 直接传需求文本
  ./start.sh --tool echo "实现用户登录功能，支持 JWT 认证"
EOF
}

die() {
  echo "错误: $*" >&2
  exit 1
}

venv_python() {
  if [[ -x "$VENV_DIR/bin/python" ]]; then
    echo "$VENV_DIR/bin/python"
  elif [[ -x "$VENV_DIR/Scripts/python.exe" ]]; then
    echo "$VENV_DIR/Scripts/python.exe"
  else
    echo ""
  fi
}

venv_is_healthy() {
  local py
  py="$(venv_python)"
  [[ -n "$py" ]] || return 1
  # activate 缺失或 pip 不可用都视为损坏（常见于中断创建的半成品 .venv）
  if [[ ! -f "$VENV_DIR/bin/activate" && ! -f "$VENV_DIR/Scripts/activate.bat" ]]; then
    return 1
  fi
  "$py" -m pip --version >/dev/null 2>&1
}

ensure_venv() {
  if venv_is_healthy; then
    echo "==> 复用虚拟环境: $VENV_DIR"
    return 0
  fi

  if [[ -e "$VENV_DIR" ]]; then
    echo "==> 虚拟环境不完整，重建: $VENV_DIR"
    rm -rf "$VENV_DIR"
  else
    echo "==> 创建虚拟环境: $VENV_DIR"
  fi

  "$PYTHON_BIN" -m venv "$VENV_DIR" || die "创建虚拟环境失败: $VENV_DIR"
  venv_is_healthy || die "虚拟环境创建后仍不可用（缺少 activate/pip），请检查 Python 是否带 ensurepip"
}

# ---------- parse args ----------
TOOL=""
MODEL=""
DOCS_DIR=""
REQ_NAME=""
REQ_FILE=""
REQ_TEXT=()
SKIP_CLARIFICATION=0
AUTO_MODE=0
FRESH=0
REQ_FILE=""
REQ_TEXT=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    --skip-install|--force-install|-skip-install|-force-install)
      # 兼容旧参数：忽略；安装一律走 init_env
      shift
      ;;
    --skip-clarification)
      SKIP_CLARIFICATION=1
      shift
      ;;
    --auto)
      AUTO_MODE=1
      shift
      ;;
    --fresh)
      FRESH=1
      shift
      ;;
    -t|--tool)
      [[ $# -ge 2 ]] || die "--tool 需要参数"
      TOOL="$2"
      shift 2
      ;;
    --model)
      [[ $# -ge 2 ]] || die "--model 需要参数"
      MODEL="$2"
      shift 2
      ;;
    -n|--name)
      [[ $# -ge 2 ]] || die "--name 需要参数"
      REQ_NAME="$2"
      shift 2
      ;;
    -d|--docs-dir)
      [[ $# -ge 2 ]] || die "--docs-dir 需要参数"
      DOCS_DIR="$2"
      shift 2
      ;;
    -f|--file)
      [[ $# -ge 2 ]] || die "--file 需要参数"
      REQ_FILE="$2"
      shift 2
      ;;
    --)
      shift
      REQ_TEXT+=("$@")
      break
      ;;
    -*)
      die "未知选项: $1（用 --help 查看用法）"
      ;;
    *)
      REQ_TEXT+=("$1")
      shift
      ;;
  esac
  done

# 单个 .md 路径参数视为 --file
if [[ -z "$REQ_FILE" && ${#REQ_TEXT[@]} -eq 1 ]]; then
  single="${REQ_TEXT[0]}"
  if [[ "$single" == *.md && -f "$single" ]]; then
    REQ_FILE="$single"
    REQ_TEXT=()
  fi
fi

# ---------- python / venv ----------
command -v "$PYTHON_BIN" >/dev/null 2>&1 || die "未找到 $PYTHON_BIN，请先安装 Python 3.10+"

PY_VERSION="$("$PYTHON_BIN" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
echo "==> Python: $PYTHON_BIN ($PY_VERSION)"

ensure_venv
VENV_PY="$(venv_python)"
[[ -n "$VENV_PY" ]] || die "未找到虚拟环境 Python"

package_installed() {
  "$VENV_PY" -m pip show ai4se-sdd-loop-workflow >/dev/null 2>&1
}

if ! package_installed; then
  die "尚未安装依赖，本启动脚本不会执行 pip install。
请先在引擎目录执行:

  ./init_env.sh

然后再运行 sddl start / ./start.sh"
fi
echo "==> 依赖已安装（安装请用 ./init_env.sh，此处不执行 pip install）"

# ---------- default requirement ----------
if [[ -z "$REQ_FILE" && ${#REQ_TEXT[@]} -eq 0 ]]; then
  DEFAULT_REQ="../spec/requirements/jwt-login-requirement.md"
  if [[ -f "$DEFAULT_REQ" ]]; then
    echo "==> 未传需求，使用默认: $DEFAULT_REQ"
    REQ_FILE="$DEFAULT_REQ"
  else
    die "请提供需求文本或 --file；也可用 --help 查看示例"
  fi
fi

# ---------- build run.py args ----------
RUN_ARGS=()
if [[ -n "$REQ_FILE" ]]; then
  [[ -f "$REQ_FILE" ]] || die "需求文件不存在: $REQ_FILE"
  RUN_ARGS+=(--file "$REQ_FILE")
elif [[ ${#REQ_TEXT[@]} -gt 0 ]]; then
  RUN_ARGS+=("${REQ_TEXT[*]}")
fi

if [[ -n "$TOOL" ]]; then
  RUN_ARGS+=(--tool "$TOOL")
fi
if [[ -n "$MODEL" ]]; then
  RUN_ARGS+=(--model "$MODEL")
fi
if [[ -n "$REQ_NAME" ]]; then
  RUN_ARGS+=(--name "$REQ_NAME")
fi
if [[ -n "$DOCS_DIR" ]]; then
  RUN_ARGS+=(--docs-dir "$DOCS_DIR")
fi
if [[ "$SKIP_CLARIFICATION" -eq 1 ]]; then
  RUN_ARGS+=(--skip-clarification)
fi
if [[ "$AUTO_MODE" -eq 1 ]]; then
  RUN_ARGS+=(--auto)
fi
if [[ "$FRESH" -eq 1 ]]; then
  RUN_ARGS+=(--fresh)
fi
echo "==> 启动 workflow"
echo "    $VENV_PY run.py ${RUN_ARGS[*]}"
echo

exec "$VENV_PY" run.py "${RUN_ARGS[@]}"
