#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${QODEX_PYTHON:-python3}"
HOST="${QUESTION_GENERATION_HOST:-127.0.0.1}"
PORT="${QUESTION_GENERATION_PORT:-8093}"

if [[ -z "${QUESTION_GENERATION_DATABASE_URL:-}" ]]; then
	echo "QUESTION_GENERATION_DATABASE_URL is required" >&2
	exit 1
fi

cd "$ROOT_DIR"
exec "$PYTHON_BIN" -m uvicorn question_generation.service:app --host "$HOST" --port "$PORT"
