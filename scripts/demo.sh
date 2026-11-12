#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PI_DIR="$ROOT_DIR/pi-coding-agent"
CHECKER_DIR="$PI_DIR/services/exam-checker"
WEB_DIR="$PI_DIR/apps/qodex-web"
COMPOSE_FILE="$CHECKER_DIR/compose.yaml"
ENV_FILE="$PI_DIR/.env"
LOG_DIR="$ROOT_DIR/.local/demo"
ROOT_PYTHON="${QODEX_PYTHON:-$ROOT_DIR/.venv/bin/python}"
CHECKER_PYTHON="$CHECKER_DIR/.venv/bin/python"
MODE="${1:-demo}"
STARTED_PIDS=""

log() {
	printf '[qodex] %s\n' "$*"
}

service_ready() {
	curl --silent --show-error --fail --max-time 2 "$1/health" >/dev/null 2>&1
}

web_ready() {
	curl --silent --show-error --fail --max-time 2 "$1" >/dev/null 2>&1
}

show_status() {
	local failed=0
	for entry in \
		"exam-checker|http://127.0.0.1:8091" \
		"exam-assembly|http://127.0.0.1:8092" \
		"question-generation|http://127.0.0.1:8093"; do
		local name="${entry%%|*}"
		local url="${entry#*|}"
		if service_ready "$url"; then
			printf '%-22s ready    %s\n' "$name" "$url"
		else
			printf '%-22s stopped  %s\n' "$name" "$url"
			failed=1
		fi
	done
	if web_ready "http://127.0.0.1:3000"; then
		printf '%-22s ready    %s\n' "qodex-web" "http://127.0.0.1:3000"
	else
		printf '%-22s stopped  %s\n' "qodex-web" "http://127.0.0.1:3000"
		failed=1
	fi
	return "$failed"
}

cleanup() {
	local exit_code=$?
	trap - EXIT INT TERM
	if [[ -n "$STARTED_PIDS" ]]; then
		log "Stopping services started by this demo run"
		for pid in $STARTED_PIDS; do
			kill -TERM "$pid" 2>/dev/null || true
		done
		for pid in $STARTED_PIDS; do
			wait "$pid" 2>/dev/null || true
		done
	fi
	exit "$exit_code"
}

require_file() {
	[[ -f "$1" ]] || { printf 'Missing %s\n' "$1" >&2; exit 1; }
}

require_command() {
	command -v "$1" >/dev/null 2>&1 || { printf '%s is required\n' "$1" >&2; exit 1; }
}

load_environment() {
	require_file "$ENV_FILE"
	set -a
	# shellcheck disable=SC1090
	source "$ENV_FILE"
	set +a

	if [[ -z "${EXAM_CHECKER_LLM_API_KEY:-}" ]]; then
		echo "EXAM_CHECKER_LLM_API_KEY is missing in $ENV_FILE" >&2
		exit 1
	fi
	if [[ -z "${EXAM_CHECKER_JEV_API_KEY:-}" ]]; then
		echo "EXAM_CHECKER_JEV_API_KEY is missing in $ENV_FILE" >&2
		exit 1
	fi
	if [[ -z "${DEEPSEEK_API_KEY:-}" ]]; then
		echo "DEEPSEEK_API_KEY is missing in $ENV_FILE" >&2
		exit 1
	fi

	local db_user="${EXAM_CHECKER_POSTGRES_USER:-qodex}"
	local db_password="${EXAM_CHECKER_POSTGRES_PASSWORD:-qodex-local}"
	local db_name="${EXAM_CHECKER_POSTGRES_DB:-qodex}"
	local db_port="${EXAM_CHECKER_POSTGRES_PORT:-5433}"
	export QUESTION_GENERATION_DATABASE_URL="${QUESTION_GENERATION_DATABASE_URL:-postgresql://$db_user:$db_password@127.0.0.1:$db_port/$db_name}"
	export EXAM_ASSEMBLY_DATABASE_URL="${EXAM_ASSEMBLY_DATABASE_URL:-${EXAM_CHECKER_DATABASE_URL:-$QUESTION_GENERATION_DATABASE_URL}}"
	export EXAM_CHECKER_SERVICE_URL="${EXAM_CHECKER_SERVICE_URL:-http://127.0.0.1:8091}"
	export EXAM_ASSEMBLY_SERVICE_URL="${EXAM_ASSEMBLY_SERVICE_URL:-http://127.0.0.1:8092}"
	export QUESTION_GENERATION_SERVICE_URL="${QUESTION_GENERATION_SERVICE_URL:-http://127.0.0.1:8093}"
	export PI_PROVIDER="${PI_PROVIDER:-${QODEX_PI_PROVIDER:-deepseek}}"
	export PI_MODEL_ID="${PI_MODEL_ID:-${QODEX_PI_MODEL:-deepseek-flash}}"
	export PI_WORKSPACE_PATH="${PI_WORKSPACE_PATH:-$ROOT_DIR}"
}

preflight() {
	require_command docker
	require_command curl
	require_command npm
	require_file "$ROOT_DIR/package.json"
	require_file "$ROOT_DIR/question_generation/sql/001_pending_questions.sql"
	[[ -x "$ROOT_PYTHON" ]] || { echo "Missing $ROOT_PYTHON; run npm run demo:setup" >&2; exit 1; }
	[[ -x "$CHECKER_PYTHON" ]] || { echo "Missing $CHECKER_PYTHON; run npm run demo:setup" >&2; exit 1; }
	[[ -d "$PI_DIR/node_modules" ]] || { echo "Missing Pi node_modules; run npm run demo:setup" >&2; exit 1; }
	[[ -d "$WEB_DIR/node_modules" ]] || { echo "Missing Qodex Web node_modules; run npm run demo:setup" >&2; exit 1; }
	load_environment
	"$ROOT_PYTHON" -c 'import asyncpg, uvicorn, exam_assembly_agent, question_generation'
	PYTHONPATH="$CHECKER_DIR/src" "$CHECKER_PYTHON" -c 'import exam_checker'
	docker info >/dev/null 2>&1 || { echo "Docker is not running" >&2; exit 1; }
}

compose_args() {
	COMPOSE_ARGS=(-f "$COMPOSE_FILE")
	if [[ -f "$ENV_FILE" ]]; then
		COMPOSE_ARGS=(--env-file "$ENV_FILE" "${COMPOSE_ARGS[@]}")
	fi
}

prepare_database() {
	log "Starting PostgreSQL and applying exam-checker migrations"
	(
		cd "$PI_DIR"
		./start-exam-checker-db.sh
	)

	compose_args
	local db_user="${EXAM_CHECKER_POSTGRES_USER:-qodex}"
	local db_name="${EXAM_CHECKER_POSTGRES_DB:-qodex}"
	log "Applying question-generation schema"
	docker compose "${COMPOSE_ARGS[@]}" exec -T postgres \
		psql -v ON_ERROR_STOP=1 -U "$db_user" -d "$db_name" \
		< "$ROOT_DIR/question_generation/sql/001_pending_questions.sql"
}

start_checker() {
	if service_ready "http://127.0.0.1:8091"; then
		log "Reusing exam-checker already running on 8091"
		return
	fi
	(
		cd "$PI_DIR"
		exec ./start-exam-checker.sh
	) >"$LOG_DIR/exam-checker.log" 2>&1 &
	STARTED_PIDS="$STARTED_PIDS $!"
}

start_assembly() {
	if service_ready "http://127.0.0.1:8092"; then
		log "Reusing exam-assembly already running on 8092"
		return
	fi
	QODEX_PYTHON="$ROOT_PYTHON" "$ROOT_DIR/scripts/start-exam-assembly.sh" \
		>"$LOG_DIR/exam-assembly.log" 2>&1 &
	STARTED_PIDS="$STARTED_PIDS $!"
}

start_generation() {
	if service_ready "http://127.0.0.1:8093"; then
		log "Reusing question-generation already running on 8093"
		return
	fi
	QODEX_PYTHON="$ROOT_PYTHON" "$ROOT_DIR/scripts/start-question-generation.sh" \
		>"$LOG_DIR/question-generation.log" 2>&1 &
	STARTED_PIDS="$STARTED_PIDS $!"
}

start_web() {
	if web_ready "http://127.0.0.1:3000"; then
		log "Reusing Qodex Web already running on 3000"
		return
	fi
	(
		cd "$WEB_DIR"
		exec npm run dev
	) >"$LOG_DIR/qodex-web.log" 2>&1 &
	STARTED_PIDS="$STARTED_PIDS $!"
}

wait_for_service() {
	local name="$1"
	local url="$2"
	local logfile="$3"
	local attempt
	for attempt in $(seq 1 180); do
		if service_ready "$url"; then
			log "$name is ready at $url"
			return
		fi
		sleep 1
	done
	echo "$name did not become healthy; recent log output:" >&2
	tail -n 80 "$logfile" >&2 || true
	exit 1
}

wait_for_web() {
	local attempt
	for attempt in $(seq 1 180); do
		if web_ready "http://127.0.0.1:3000"; then
			log "Qodex Web is ready at http://127.0.0.1:3000"
			return
		fi
		sleep 1
	done
	echo "Qodex Web did not become ready; recent log output:" >&2
	tail -n 80 "$LOG_DIR/qodex-web.log" >&2 || true
	exit 1
}

start_services() {
	mkdir -p "$LOG_DIR"
	start_checker
	start_assembly
	start_generation
	wait_for_service "exam-checker" "http://127.0.0.1:8091" "$LOG_DIR/exam-checker.log"
	wait_for_service "exam-assembly" "http://127.0.0.1:8092" "$LOG_DIR/exam-assembly.log"
	wait_for_service "question-generation" "http://127.0.0.1:8093" "$LOG_DIR/question-generation.log"
}

if [[ "$MODE" == "status" ]]; then
	show_status
	exit $?
fi

if [[ "$MODE" == "db" ]]; then
	require_command docker
	if [[ -f "$ENV_FILE" ]]; then
		set -a
		# shellcheck disable=SC1090
		source "$ENV_FILE"
		set +a
	fi
	docker info >/dev/null 2>&1 || { echo "Docker is not running" >&2; exit 1; }
	prepare_database
	log "Database is ready"
	exit 0
fi

preflight
prepare_database

trap cleanup EXIT INT TERM
start_services

if [[ "$MODE" == "services" ]]; then
	log "All services are ready; press Ctrl+C to stop them"
	wait
	exit 0
fi

if [[ "$MODE" == "cli" ]]; then
	log "All services are healthy; starting Pi CLI"
	(
		cd "$PI_DIR"
		exec ./pi-test.sh \
			--provider "$PI_PROVIDER" \
			--model "$PI_MODEL_ID"
	)
	exit 0
fi

start_web
wait_for_web
log "Complete demo is running at http://127.0.0.1:3000; press Ctrl+C to stop it"
wait
