#!/usr/bin/env bash
# 一键启动：仓库根目录下 .venv，PYTHONPATH=src，运行 python -m yxl_lace
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${SCRIPT_DIR}"

if [[ ! -f "${PROJECT_DIR}/src/yxl_lace/__main__.py" ]]; then
  echo "未找到：${PROJECT_DIR}/src/yxl_lace/__main__.py" >&2
  exit 1
fi

cd "${PROJECT_DIR}"

VENV="${PROJECT_DIR}/.venv"
if [[ ! -d "${VENV}" ]]; then
  echo "创建虚拟环境：${VENV}"
  python3 -m venv "${VENV}"
fi

# shellcheck source=/dev/null
source "${VENV}/bin/activate"

for _v in ALL_PROXY all_proxy HTTP_PROXY HTTPS_PROXY http_proxy https_proxy; do
  unset "${_v}" 2>/dev/null || true
done

if [[ -f "${PROJECT_DIR}/requirements.txt" ]]; then
  pip install -q -r "${PROJECT_DIR}/requirements.txt"
else
  pip install -q cryptography
fi

export PYTHONPATH="${PROJECT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"
exec python -m yxl_lace "$@"
