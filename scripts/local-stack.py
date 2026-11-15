"""Local teacher demo; secrets stay in subprocess environments and ignored config."""
import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
PI = ROOT / "pi-coding-agent"
LOGS = ROOT / ".local/web-stack"


def ready(url):
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(url, timeout=2) as response:
            return response.status == 200
    except (OSError, ValueError):
        return False


def environment():
    env = os.environ.copy()
    config = ROOT / ".env.local"
    if config.exists():
        for line in config.read_text(encoding="utf-8-sig").splitlines():
            if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                env[key.strip()] = value.strip().strip("\"'")
    defaults = {
        "EXAM_CHECKER_DATABASE_URL": "postgresql+asyncpg://qodex:qodex-local@127.0.0.1:5433/qodex",
        "EXAM_ASSEMBLY_DATABASE_URL": "postgresql://qodex:qodex-local@127.0.0.1:5433/qodex",
        "QUESTION_GENERATION_DATABASE_URL": "postgresql://qodex:qodex-local@127.0.0.1:5433/qodex",
        "EXAM_CHECKER_SERVICE_URL": "http://127.0.0.1:8091",
        "QUESTION_BANK_SERVICE_URL": "http://127.0.0.1:8091",
        "EXAM_ASSEMBLY_SERVICE_URL": "http://127.0.0.1:8092",
        "QUESTION_GENERATION_SERVICE_URL": "http://127.0.0.1:8093",
        "EXAM_CHECKER_LLM_BASE_URL": "https://api.deepseek.com",
        "EXAM_CHECKER_LLM_MODEL": "deepseek-flash",
        "PI_PROVIDER": "deepseek", "PI_MODEL_ID": "deepseek-flash",
    }
    for key, value in defaults.items():
        env.setdefault(key, value)
    env["PYTHONPATH"] = os.pathsep.join(map(str, [ROOT, PI / "services/exam-checker/src", PI / "services/exam-assembly/src"]))
    env["PI_WORKSPACE_PATH"] = str(ROOT)
    env["PYTHONUTF8"] = "1"
    env["NEXT_TELEMETRY_DISABLED"] = "1"
    return env


def prepare_database(env):
    compose = ["docker", "compose", "-f", str(PI / "services/exam-checker/compose.yaml")]
    subprocess.run([*compose, "up", "-d", "postgres"], env=env, check=True)
    for _ in range(60):
        try:
            with socket.create_connection(("127.0.0.1", 5433), timeout=1):
                break
        except OSError:
            time.sleep(1)
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=PI / "services/exam-checker", env=env, check=True)
    with (ROOT / "question_generation/sql/001_pending_questions.sql").open("rb") as stream:
        subprocess.run([*compose, "exec", "-T", "postgres", "psql", "-v", "ON_ERROR_STOP=1", "-U", env.get("EXAM_CHECKER_POSTGRES_USER", "qodex"), "-d", env.get("EXAM_CHECKER_POSTGRES_DB", "qodex")], stdin=stream, env=env, check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--web-port", type=int, default=3000)
    parser.add_argument("--no-web", action="store_true")
    parser.add_argument("--skip-database", action="store_true")
    args = parser.parse_args()
    env = environment()
    if not env.get("DEEPSEEK_API_KEY"):
        print("Model key is not configured: bank/history/assembly still work; Pi and AI review require scripts/configure-local.ps1.", flush=True)
    if not args.skip_database:
        prepare_database(env)
    LOGS.mkdir(parents=True, exist_ok=True)
    processes, handles = [], []
    def start(name, command, port, cwd=ROOT, health="/health"):
        url = f"http://127.0.0.1:{port}{health}"
        if ready(url):
            raise RuntimeError(f"Port {port} is already serving. Close its old service or select a different web port; no process was stopped.")
        handle = (LOGS / f"{name}.log").open("w", encoding="utf-8")
        handles.append(handle)
        process = subprocess.Popen(command, cwd=cwd, env=env, stdout=handle, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        processes.append(process)
        return name, process, url
    try:
        pending = []
        for name, module, port in [("checker", "exam_checker.api.app:app", 8091), ("assembly", "exam_assembly_service.app:app", 8092), ("generation", "question_generation.service:app", 8093)]:
            pending.append(start(name, [sys.executable, "-m", "uvicorn", module, "--host", "127.0.0.1", "--port", str(port)], port))
        if not args.no_web:
            web = PI / "apps/qodex-web"
            pending.append(start("web", [shutil.which("node") or "node", str(web / "node_modules/next/dist/bin/next"), "dev", "-H", "127.0.0.1", "-p", str(args.web_port)], args.web_port, web, "/api/pi/handshake"))
        for name, process, url in pending:
            for _ in range(120):
                if process.poll() is not None:
                    raise RuntimeError(f"{name} stopped; read {LOGS / (name + '.log')}")
                if ready(url):
                    print(f"{name}: ready", flush=True)
                    break
                time.sleep(1)
            else:
                raise RuntimeError(f"{name} timed out; inspect its log")
        print(f"Open http://127.0.0.1:{args.web_port}. Keep this window open. Ctrl+C stops only these processes, preserving database data.", flush=True)
        while all(p.poll() is None for p in processes):
            time.sleep(1)
        raise RuntimeError("A service stopped. Check .local/web-stack logs.")
    except KeyboardInterrupt:
        print("Stopping this local run…", flush=True)
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
        for handle in handles:
            handle.close()


if __name__ == "__main__":
    main()
