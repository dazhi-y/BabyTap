#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVER_DIR="${BABYTAP_SERVER_DIR:-${PROJECT_DIR}/../babytap-server}"
SERVER_DB="${BABYTAP_SERVER_DB:-${SERVER_DIR}/data/db.sqlite3}"
SERVER_HOST="127.0.0.1"
SERVER_PORT="${BABYTAP_SERVER_PORT:-8000}"
APP_HOST="127.0.0.1"
APP_PORT="${BABYTAP_APP_PORT:-8765}"
DEFAULT_SERVER_URL="http://${SERVER_HOST}:${SERVER_PORT}"

SERVER_PID=""
APP_PID=""

cleanup() {
  local pid
  for pid in "${APP_PID}" "${SERVER_PID}"; do
    if [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null; then
      kill "${pid}" 2>/dev/null || true
      wait "${pid}" 2>/dev/null || true
    fi
  done
}
trap cleanup EXIT INT TERM

if [[ ! -f "${SERVER_DB}" ]]; then
  echo "找不到 BabyTap Server 数据库：${SERVER_DB}" >&2
  exit 1
fi
if [[ ! -x "${SERVER_DIR}/.venv/bin/python" ]]; then
  echo "找不到 BabyTap Server Python 环境：${SERVER_DIR}/.venv/bin/python" >&2
  exit 1
fi
if [[ ! -x "${PROJECT_DIR}/app/.venv/bin/uvicorn" ]]; then
  echo "找不到 BabyTap Python 环境，请先安装 app 依赖。" >&2
  exit 1
fi

if [[ -z "${BABYTAP_BABYBUDDY_TOKEN:-}" ]]; then
  BABYTAP_BABYBUDDY_TOKEN="$(sqlite3 "${SERVER_DB}" "SELECT key FROM authtoken_token WHERE user_id=1 LIMIT 1;")"
fi
if [[ -z "${BABYTAP_BABYBUDDY_CHILD_ID:-}" ]]; then
  echo "Set BABYTAP_BABYBUDDY_CHILD_ID." >&2
  exit 1
fi

if [[ -z "${BABYTAP_BABYBUDDY_TOKEN}" || -z "${BABYTAP_BABYBUDDY_CHILD_ID}" ]]; then
  echo "Baby Buddy Token or child ID is missing." >&2
  exit 1
fi

export BABYTAP_BABYBUDDY_URL="${BABYTAP_BABYBUDDY_URL:-${DEFAULT_SERVER_URL}}"
export BABYTAP_BABYBUDDY_TOKEN
export BABYTAP_BABYBUDDY_CHILD_ID
export BABYTAP_BOTTLE_TYPE="${BABYTAP_BOTTLE_TYPE:-breast milk}"
export BABYTAP_ENABLE_HID="${BABYTAP_ENABLE_HID:-0}"
export BABYTAP_ENABLE_BLE_FEEDBACK="${BABYTAP_ENABLE_BLE_FEEDBACK:-1}"
# BabyTap 日常接管 EasyInput 板载麦克风；官方程序仅在维护设备配置时
# 临时使用该端口，配置完成后退出并释放 UDP 17333。
export BABYTAP_ENABLE_AUDIO="${BABYTAP_ENABLE_AUDIO:-1}"

server_is_healthy() {
  curl --silent --fail --max-time 2 \
    --header "Authorization: Token ${BABYTAP_BABYBUDDY_TOKEN}" \
    "${BABYTAP_BABYBUDDY_URL}/api/children/?limit=1" >/dev/null
}

app_is_healthy() {
  curl --silent --fail --max-time 2 \
    "http://${APP_HOST}:${APP_PORT}/health" >/dev/null
}

wait_for_server() {
  local attempt
  for attempt in {1..20}; do
    if server_is_healthy; then
      return 0
    fi
    sleep 0.5
  done
  return 1
}

wait_for_app() {
  local attempt
  for attempt in {1..20}; do
    if app_is_healthy; then
      return 0
    fi
    sleep 0.5
  done
  return 1
}

if server_is_healthy; then
  echo "Baby Buddy 已运行：${BABYTAP_BABYBUDDY_URL}"
else
  if [[ "${BABYTAP_BABYBUDDY_URL}" != "${DEFAULT_SERVER_URL}" ]]; then
    echo "外部 Baby Buddy 不可用：${BABYTAP_BABYBUDDY_URL}" >&2
    exit 1
  fi

  echo "正在启动 Baby Buddy：${DEFAULT_SERVER_URL}"
  (
    cd "${SERVER_DIR}"
    DJANGO_SETTINGS_MODULE=babybuddy.settings.development \
      .venv/bin/python manage.py migrate --noinput
    DJANGO_SETTINGS_MODULE=babybuddy.settings.development \
      exec .venv/bin/python manage.py runserver "${SERVER_HOST}:${SERVER_PORT}" --noreload
  ) &
  SERVER_PID=$!

  if ! wait_for_server; then
    echo "Baby Buddy 启动失败，请查看上方日志。" >&2
    exit 1
  fi
  echo "Baby Buddy 已就绪：${DEFAULT_SERVER_URL}"
fi

if app_is_healthy; then
  echo "BabyTap 已运行：http://${APP_HOST}:${APP_PORT}"
else
  if [[ "$(uname -s)" == "Darwin" && ! -x "${PROJECT_DIR}/app/.native/BabyTapTranscriber.app/Contents/MacOS/BabyTapTranscriber" ]]; then
    "${PROJECT_DIR}/scripts/build-macos-transcriber.sh" >/dev/null
  fi

  echo "正在启动 BabyTap：http://${APP_HOST}:${APP_PORT}"
  "${PROJECT_DIR}/app/.venv/bin/uvicorn" babytap.main:app \
    --app-dir "${PROJECT_DIR}/app/src" \
    --host "${APP_HOST}" \
    --port "${APP_PORT}" \
    --no-access-log &
  APP_PID=$!

  if ! wait_for_app; then
    echo "BabyTap 启动失败，请查看上方日志。" >&2
    exit 1
  fi
  echo "BabyTap 已就绪：http://${APP_HOST}:${APP_PORT}"
fi

if [[ -z "${SERVER_PID}" && -z "${APP_PID}" ]]; then
  echo "两个服务均已健康，无需重复启动。"
  exit 0
fi

echo "按 Ctrl+C 停止本脚本启动的服务。"
while true; do
  if [[ -n "${SERVER_PID}" ]] && ! kill -0 "${SERVER_PID}" 2>/dev/null; then
    wait "${SERVER_PID}" || true
    SERVER_PID=""
    echo "Baby Buddy 已退出。" >&2
    exit 1
  fi
  if [[ -n "${APP_PID}" ]] && ! kill -0 "${APP_PID}" 2>/dev/null; then
    wait "${APP_PID}" || true
    APP_PID=""
    echo "BabyTap 已退出。" >&2
    exit 1
  fi
  sleep 1
done
