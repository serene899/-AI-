#!/usr/bin/env bash
# Crypto Sim — Linux / macOS 一键启动
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if command -v python3 >/dev/null 2>&1; then
  PY=python3
elif command -v python >/dev/null 2>&1; then
  PY=python
else
  echo "[ERR] 未找到 python/python3，请先安装 Python 3.10+"
  exit 1
fi

exec "$PY" "$DIR/run.py"
