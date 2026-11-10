#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${QODEX_PYTHON:-python3}"
HOST="${EXAM_ASSEMBLY_HOST:-127.0.0.1}"
PORT="${EXAM_ASSEMBLY_PORT:-8092}"
SERVICE_SRC="$ROOT_DIR/pi-coding-agent/services/exam-assembly/src"

export PYTHONPATH="$ROOT_DIR:$SERVICE_SRC${PYTHONPATH:+:$PYTHONPATH}"
cd "$ROOT_DIR"
exec "$PYTHON_BIN" -m uvicorn exam_assembly_service.app:app --host "$HOST" --port "$PORT"
