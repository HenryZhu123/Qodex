#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="$ROOT_DIR/services/exam-checker/compose.yaml"
ENV_FILE="$ROOT_DIR/.env"

compose_args=(-f "$COMPOSE_FILE")
if [[ -f "$ENV_FILE" ]]; then
  compose_args=(--env-file "$ENV_FILE" "${compose_args[@]}")
fi

docker compose "${compose_args[@]}" up -d --wait
docker compose "${compose_args[@]}" run --rm migrate
docker compose "${compose_args[@]}" ps
