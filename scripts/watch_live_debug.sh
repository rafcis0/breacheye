#!/usr/bin/env bash
set -euo pipefail

RUN_ID="${1:-${BREACHEYE_RUN_ID:-latest}}"
LOG_DIR="${BREACHEYE_LOG_DIR:-logs}"
HARNESS_URL="${BREACHEYE_HARNESS_URL:-http://127.0.0.1:8000}"
INTERVAL_S="${BREACHEYE_MONITOR_INTERVAL_S:-1}"
FRAME_INTERVAL_S="${BREACHEYE_MONITOR_FRAME_INTERVAL_S:-2}"

exec breacheye monitor \
  --run-id "${RUN_ID}" \
  --log-dir "${LOG_DIR}" \
  --harness-url "${HARNESS_URL}" \
  --interval-s "${INTERVAL_S}" \
  --frame-interval-s "${FRAME_INTERVAL_S}"
