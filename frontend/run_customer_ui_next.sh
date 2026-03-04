#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${ROOT_DIR}/customer-ui-next"
UI_MODE="${QA_UI_MODE:-auto}" # auto|split|full_next
BACKEND_BASE_URL_DEFAULT="${BACKEND_BASE_URL_DEFAULT:-http://127.0.0.1:8787}"

if [[ ! -d "${APP_DIR}" ]]; then
  echo "Missing Next.js app directory: ${APP_DIR}" >&2
  exit 1
fi

cd "${APP_DIR}"

if [[ ! -x "node_modules/.bin/next" ]]; then
  echo "[SETUP] Installing Next.js UI dependencies..."
  npm install
fi

if [[ ! -x "node_modules/.bin/next" ]]; then
  echo "[ERROR] Next.js binary not found after install." >&2
  echo "Try running manually:" >&2
  echo "  cd frontend/customer-ui-next && npm install && npx next --version" >&2
  exit 1
fi

is_port_in_use() {
  local port="$1"
  lsof -nP -iTCP:"${port}" -sTCP:LISTEN >/dev/null 2>&1
}

pick_port() {
  local preferred="$1"
  if ! is_port_in_use "${preferred}"; then
    echo "${preferred}"
    return 0
  fi
  local p
  for p in 3002 3003 3004 3005 3006 3007 3008 3009 3010; do
    if ! is_port_in_use "${p}"; then
      echo "${p}"
      return 0
    fi
  done
  return 1
}

UI_PORT="${UI_PORT:-3001}"
if ! SELECTED_PORT="$(pick_port "${UI_PORT}")"; then
  echo "[ERROR] No available port found in range 3001-3010." >&2
  echo "Free a port or run with explicit UI_PORT, e.g.:" >&2
  echo "  UI_PORT=3011 ./frontend/run_customer_ui_next.sh" >&2
  exit 1
fi

if [[ "${SELECTED_PORT}" != "${UI_PORT}" ]]; then
  echo "[WARN] Port ${UI_PORT} is busy. Using ${SELECTED_PORT}."
fi

detect_backend_mode() {
  if [[ -n "${NEXT_PUBLIC_BACKEND_BASE_URL:-}" ]]; then
    echo "split"
    return 0
  fi
  if [[ "${UI_MODE}" == "split" ]]; then
    echo "split"
    return 0
  fi
  if [[ "${UI_MODE}" == "full_next" ]]; then
    echo "full_next"
    return 0
  fi

  if command -v curl >/dev/null 2>&1; then
    if curl -fsS --max-time 1 "${BACKEND_BASE_URL_DEFAULT}/api/jobs" >/dev/null 2>&1; then
      echo "split"
      return 0
    fi
  fi
  echo "full_next"
}

RUN_MODE="$(detect_backend_mode)"
echo "[RUN] Starting Next.js customer UI at http://localhost:${SELECTED_PORT}"
if [[ "${RUN_MODE}" == "split" ]]; then
  BACKEND_BASE_URL="${NEXT_PUBLIC_BACKEND_BASE_URL:-${BACKEND_BASE_URL_DEFAULT}}"
  echo "[CFG] mode=split_fastapi"
  echo "[CFG] NEXT_PUBLIC_BACKEND_BASE_URL=${BACKEND_BASE_URL}"
  if command -v curl >/dev/null 2>&1; then
    if ! curl -fsS --max-time 1 "${BACKEND_BASE_URL}/api/ping" >/dev/null 2>&1; then
      echo "[WARN] Backend health check failed for ${BACKEND_BASE_URL}/api/ping"
      echo "[WARN] UI may not start jobs until backend is running."
      echo "[TIP] Start backend: ./backend/start-backend.sh"
      echo "[TIP] Or use local proxy mode: QA_UI_MODE=full_next ./frontend/run_customer_ui_next.sh"
    fi
  fi
  NEXT_PUBLIC_BACKEND_BASE_URL="${BACKEND_BASE_URL}" exec npm run dev -- -p "${SELECTED_PORT}"
else
  echo "[CFG] mode=full_next_local"
  echo "[CFG] NEXT_PUBLIC_BACKEND_BASE_URL=<unset>"
  echo "[TIP] For FastAPI mode use: QA_UI_MODE=split ./frontend/run_customer_ui_next.sh"
  exec npm run dev -- -p "${SELECTED_PORT}"
fi
