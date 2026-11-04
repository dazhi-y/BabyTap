#!/usr/bin/env bash
set -euo pipefail

CONFIG_DIR="${HOME}/Library/Application Support/BabyTap"
TARGET="${CONFIG_DIR}/dashscope.env"

if [[ -e "${TARGET}" ]]; then
  echo "DashScope 已配置；如需更换，请先单独处理现有私有配置。"
  exit 1
fi

read -r -s -p "请输入阿里云百炼北京区 DASHSCOPE_API_KEY（输入不会显示）: " DASH_KEY
printf '\n'
if [[ -z "${DASH_KEY}" || "${DASH_KEY}" == *$'\n'* || "${DASH_KEY}" == *$'\r'* ]]; then
  echo "API Key 为空或格式无效。" >&2
  unset DASH_KEY
  exit 1
fi

umask 077
mkdir -p "${CONFIG_DIR}"
TEMP_FILE="$(mktemp "${CONFIG_DIR}/.dashscope.env.XXXXXX")"
printf 'DASHSCOPE_API_KEY=%s\n' "${DASH_KEY}" > "${TEMP_FILE}"
chmod 600 "${TEMP_FILE}"
mv "${TEMP_FILE}" "${TARGET}"
unset DASH_KEY

echo "DashScope Key 已保存到 BabyTap 私有配置，文件权限为 600。"
