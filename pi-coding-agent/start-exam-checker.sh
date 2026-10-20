#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_DIR="$ROOT_DIR/services/exam-checker"
ENV_FILE="$ROOT_DIR/.env"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing $ENV_FILE" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

required_variables=(
  EXAM_CHECKER_DATABASE_URL
  EXAM_CHECKER_LLM_API_KEY
  EXAM_CHECKER_JEV_API_KEY
)

for variable in "${required_variables[@]}"; do
  if [[ -z "${!variable:-}" ]]; then
    echo "Missing $variable in $ENV_FILE" >&2
    exit 1
  fi
done

if [[ ! -x "$SERVICE_DIR/.venv/bin/exam-checker-service" ]]; then
  echo "Missing exam-checker virtual environment at $SERVICE_DIR/.venv" >&2
  echo "Create it and install the service before starting." >&2
  exit 1
fi

cd "$SERVICE_DIR"
"$SERVICE_DIR/.venv/bin/alembic" upgrade head
exec "$SERVICE_DIR/.venv/bin/exam-checker-service"
