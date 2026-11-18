#!/usr/bin/env bash
# init_env.sh — 项目 venv + pip install -e .，并把 .venv/bin 写入 shell 配置（免每次 activate）
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV_DIR="${VENV_DIR:-.venv}"
PYTHON_BIN="${PYTHON_BIN:-}"
MIN_PIP="21.3"
FORCE=0
SKIP_PATH=0
MARKER="# ai4se-sddl-collab-harness venv PATH"

usage() {
  cat <<'EOF'
用法:
  ./init_env.sh [--force] [--skip-path]

作用:
  1. 用 Python 3.10～3.14 创建/复用项目 .venv
  2. 升级 pip（≥21.3）并 pip install -e .
  3. 把 .venv/bin 绝对路径写入 ~/.zshrc 或 ~/.bashrc（免每次 source activate）
  4. 同步到当前 shell PATH

选项:
  --force       删除并重建 .venv
  --skip-path   只装环境，不改 shell 配置
  -h, --help
EOF
}

die() { echo "错误: $*" >&2; exit 1; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --force) FORCE=1; shift ;;
    --skip-path) SKIP_PATH=1; shift ;;
    *) die "未知参数: $1" ;;
  esac
done

python_in_range() {
  local bin="$1"
  # 避免在 shell 里写复杂 -c；用 --version 解析
  local out maj min
  out="$("$bin" --version 2>&1 || true)"
  [[ "$out" =~ Python[[:space:]]+([0-9]+)\.([0-9]+) ]] || return 1
  maj="${BASH_REMATCH[1]}"
  min="${BASH_REMATCH[2]}"
  [[ "$maj" == "3" && "$min" -ge 10 && "$min" -le 14 ]]
}

pick_python() {
  local c
  if [[ -n "$PYTHON_BIN" ]]; then
    command -v "$PYTHON_BIN" >/dev/null || die "PYTHON_BIN 不可用: $PYTHON_BIN"
    python_in_range "$PYTHON_BIN" || die "PYTHON_BIN 版本不在 3.10～3.14: $("$PYTHON_BIN" --version 2>&1)"
    echo "$PYTHON_BIN"
    return
  fi
  for c in python3.14 python3.13 python3.12 python3.11 python3.10 python3 python; do
    command -v "$c" >/dev/null 2>&1 || continue
    python_in_range "$c" || continue
    echo "$c"
    return
  done
  die "未找到 Python 3.10～3.14"
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
  [[ -f "$VENV_DIR/bin/activate" || -f "$VENV_DIR/Scripts/activate.bat" ]] || return 1
  "$py" -m pip --version >/dev/null 2>&1
}

PY="$(pick_python)"
PY_VERSION="$("$PY" --version 2>&1)"
echo "==> Python: $PY ($PY_VERSION)（要求 3.10～3.14）"

if [[ "$FORCE" -eq 1 && -e "$VENV_DIR" ]]; then
  echo "==> --force：删除 $VENV_DIR"
  rm -rf "$VENV_DIR"
fi

if venv_is_healthy; then
  echo "==> 复用虚拟环境: $VENV_DIR"
else
  if [[ -e "$VENV_DIR" ]]; then
    echo "==> 虚拟环境不完整，重建: $VENV_DIR"
    rm -rf "$VENV_DIR"
  else
    echo "==> 创建虚拟环境: $VENV_DIR"
  fi
  "$PY" -m venv "$VENV_DIR" || die "创建 venv 失败"
  venv_is_healthy || die "venv 创建后不可用"
fi

VENV_PY="$(venv_python)"
[[ -n "$VENV_PY" ]] || die "未找到 venv python"
python_in_range "$VENV_PY" || die "虚拟环境 Python 不在 3.10～3.14（$("$VENV_PY" --version 2>&1)）。请加 --force 重建"
echo "==> 虚拟环境 Python 版本 OK"

echo "==> 升级 pip / setuptools / wheel"
"$VENV_PY" -m pip install -U "pip>=${MIN_PIP}" setuptools wheel || die "升级 pip 失败"
echo "==> pip install -e ."
"$VENV_PY" -m pip install -e . || die "pip install -e . 失败"

if [[ -d "$VENV_DIR/bin" ]]; then
  BIN_DIR="$(cd "$VENV_DIR/bin" && pwd)"
else
  BIN_DIR="$(cd "$VENV_DIR/Scripts" && pwd)"
fi
command -v "$BIN_DIR/sddl" >/dev/null 2>&1 || [[ -x "$BIN_DIR/sddl" ]] || die "安装后未找到 sddl: $BIN_DIR/sddl"

export PATH="$BIN_DIR:$PATH"
echo "==> 已加入当前 shell PATH"

if [[ "$SKIP_PATH" -eq 0 ]]; then
  RC=""
  if [[ -n "${ZSH_VERSION:-}" ]] || [[ "${SHELL:-}" == *zsh ]]; then
    RC="$HOME/.zshrc"
  elif [[ -n "${BASH_VERSION:-}" ]] || [[ "${SHELL:-}" == *bash ]]; then
    RC="$HOME/.bashrc"
  else
    RC="$HOME/.zshrc"
  fi
  LINE="export PATH=\"$BIN_DIR:\$PATH\"  $MARKER"
  if [[ -f "$RC" ]] && grep -qF "$MARKER" "$RC"; then
    # 更新已有行
    tmp="$(mktemp)"
    grep -vF "$MARKER" "$RC" >"$tmp" || true
    echo "$LINE" >>"$tmp"
    mv "$tmp" "$RC"
    echo "==> 已更新 $RC 中的 venv PATH"
  else
    {
      echo ""
      echo "$LINE"
    } >>"$RC"
    echo "==> 已写入 $RC"
  fi
  echo
  echo "==> 环境就绪（项目 venv + shell PATH）"
  echo "    请执行: source $RC   或新开终端后: sddl init"
else
  echo
  echo "==> 环境就绪（未改 shell 配置，--skip-path）"
  echo "    手动加入 PATH: $BIN_DIR"
fi
