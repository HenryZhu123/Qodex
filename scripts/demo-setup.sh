#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PI_DIR="$ROOT_DIR/pi-coding-agent"
CHECKER_DIR="$PI_DIR/services/exam-checker"

if command -v python3.11 >/dev/null 2>&1; then
	PYTHON_BIN="${QODEX_BOOTSTRAP_PYTHON:-python3.11}"
else
	PYTHON_BIN="${QODEX_BOOTSTRAP_PYTHON:-python3}"
fi

"$PYTHON_BIN" -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11 or newer is required"'
command -v npm >/dev/null 2>&1 || { echo "npm is required" >&2; exit 1; }

if [[ ! -x "$ROOT_DIR/.venv/bin/python" ]]; then
	"$PYTHON_BIN" -m venv "$ROOT_DIR/.venv"
fi
"$ROOT_DIR/.venv/bin/python" -m pip install -e "$ROOT_DIR" -e "$PI_DIR/services/exam-assembly[pdf]"
"$ROOT_DIR/.venv/bin/python" -m pip install -r "$ROOT_DIR/question_generation/service-requirements.txt"

if [[ ! -x "$CHECKER_DIR/.venv/bin/python" ]]; then
	"$PYTHON_BIN" -m venv "$CHECKER_DIR/.venv"
fi
"$CHECKER_DIR/.venv/bin/python" -m pip install -e "$CHECKER_DIR[dev]"

(
	cd "$PI_DIR"
	npm ci --ignore-scripts
	npm run hydrate:model-data:release
)

if [[ ! -f "$PI_DIR/.env" ]]; then
	cp "$CHECKER_DIR/.env.example" "$PI_DIR/.env"
	printf '\nCreated %s\n' "$PI_DIR/.env"
fi

printf '\nSetup complete. Fill model and MinerU settings in %s, then run: npm run demo\n' "$PI_DIR/.env"
