from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path


_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _load_env_file(path: Path) -> bool:
    """Load a small dotenv-compatible file without overriding process env."""
    if not path.is_file():
        return False
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8-sig").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise ValueError(f"Invalid env entry at {path}:{line_number}")
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip()
        if not _ENV_NAME.fullmatch(name):
            raise ValueError(f"Invalid env name at {path}:{line_number}: {name!r}")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(name, value)
    return True


def _load_local_environment(service_root: Path) -> list[Path]:
    """Load an explicit file or the service-local .env.local/.env pair."""
    explicit = os.getenv("EXAM_CHECKER_ENV_FILE", "").strip()
    candidates = (
        [Path(explicit).expanduser()]
        if explicit
        else [service_root / ".env.local", service_root / ".env"]
    )
    loaded: list[Path] = []
    for candidate in candidates:
        resolved = candidate.resolve()
        if _load_env_file(resolved):
            loaded.append(resolved)
    return loaded


def _positive_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    value = float(raw) if raw else default
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def _positive_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    value = int(raw) if raw else default
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    host: str
    port: int
    database_url: str
    mineru_base_url: str
    mineru_timeout_seconds: float
    mineru_poll_interval_seconds: float
    mineru_max_retries: int
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    llm_timeout_seconds: float
    review_llm_base_url: str
    review_llm_api_key: str
    review_llm_model: str
    review_llm_timeout_seconds: float
    review_llm_max_concurrency: int
    review_llm_max_attempts: int
    review_reasoning_effort: str
    review_max_tokens: int
    agentic_logic_prompt_path: str
    review_prompt_root: str
    jev_base_url: str
    jev_endpoint: str
    jev_api_key: str
    jev_model: str
    jev_timeout_seconds: float
    jev_max_concurrency: int
    jev_prompt_root: str
    workflow_llm_base_url: str
    workflow_llm_api_key: str
    workflow_llm_model: str
    workflow_llm_timeout_seconds: float
    workflow_llm_max_concurrency: int
    revision_prompt_root: str
    metadata_prompt_root: str
    knowledge_base_dir: str = ""
    prefer_embedded_pdf_text: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        service_root = Path(__file__).resolve().parents[2]
        _load_local_environment(service_root)
        packaged_prompt_root = Path(__file__).resolve().parent / "assets" / "prompts"
        default_prompt_root = (
            packaged_prompt_root
            if packaged_prompt_root.is_dir()
            else service_root / "prompts"
        )
        llm_base_url = os.getenv("EXAM_CHECKER_LLM_BASE_URL", "").strip().rstrip("/")
        llm_api_key = os.getenv("EXAM_CHECKER_LLM_API_KEY", "").strip()
        llm_model = os.getenv("EXAM_CHECKER_LLM_MODEL", "").strip()
        embedded_text_flag = (
            os.getenv("EXAM_CHECKER_PREFER_EMBEDDED_PDF_TEXT", "false")
            .strip()
            .lower()
        )
        if embedded_text_flag not in {"true", "false", "1", "0"}:
            raise ValueError("EXAM_CHECKER_PREFER_EMBEDDED_PDF_TEXT must be true or false")
        return cls(
            prefer_embedded_pdf_text=embedded_text_flag in {"true", "1"},
            host=os.getenv("EXAM_CHECKER_HOST", "127.0.0.1").strip() or "127.0.0.1",
            port=_positive_int("EXAM_CHECKER_PORT", 8091),
            database_url=os.getenv("EXAM_CHECKER_DATABASE_URL", "").strip(),
            mineru_base_url=(
                os.getenv("MINERU_AGENT_BASE_URL", "https://mineru.net/api/v1/agent")
                .strip()
                .rstrip("/")
            ),
            mineru_timeout_seconds=_positive_float("MINERU_TIMEOUT_SECONDS", 300),
            mineru_poll_interval_seconds=_positive_float(
                "MINERU_POLL_INTERVAL_SECONDS", 3
            ),
            mineru_max_retries=_positive_int("MINERU_MAX_RETRIES", 4),
            llm_base_url=llm_base_url,
            llm_api_key=llm_api_key,
            llm_model=llm_model,
            llm_timeout_seconds=_positive_float(
                "EXAM_CHECKER_LLM_TIMEOUT_SECONDS", 180
            ),
            review_llm_base_url=(
                os.getenv("EXAM_CHECKER_REVIEW_LLM_BASE_URL", llm_base_url)
                .strip()
                .rstrip("/")
            ),
            review_llm_api_key=os.getenv(
                "EXAM_CHECKER_REVIEW_LLM_API_KEY", llm_api_key
            ).strip(),
            review_llm_model=os.getenv(
                "EXAM_CHECKER_REVIEW_LLM_MODEL", llm_model
            ).strip(),
            review_llm_timeout_seconds=_positive_float(
                "EXAM_CHECKER_REVIEW_LLM_TIMEOUT_SECONDS", 180
            ),
            review_llm_max_concurrency=_positive_int(
                "EXAM_CHECKER_REVIEW_LLM_MAX_CONCURRENCY", 8
            ),
            review_llm_max_attempts=_positive_int(
                "EXAM_CHECKER_REVIEW_LLM_MAX_ATTEMPTS", 3
            ),
            review_reasoning_effort=os.getenv(
                "EXAM_CHECKER_REVIEW_REASONING_EFFORT", ""
            ).strip(),
            review_max_tokens=_positive_int("EXAM_CHECKER_REVIEW_MAX_TOKENS", 2048),
            agentic_logic_prompt_path=os.getenv(
                "EXAM_CHECKER_AGENTIC_LOGIC_PROMPT_PATH", ""
            ).strip(),
            review_prompt_root=os.getenv(
                "EXAM_CHECKER_REVIEW_PROMPT_ROOT",
                str(default_prompt_root / "reviewer-prompt" / "qwen38_27b"),
            ).strip(),
            jev_base_url=(
                os.getenv(
                    "EXAM_CHECKER_JEV_BASE_URL",
                    "https://openrouter.ai/api/alpha",
                )
                .strip()
                .rstrip("/")
            ),
            jev_endpoint=os.getenv("EXAM_CHECKER_JEV_ENDPOINT", "").strip().rstrip("/"),
            jev_api_key=(
                os.getenv("EXAM_CHECKER_JEV_API_KEY", "").strip()
                or os.getenv("OPENROUTER_API_KEY", "").strip()
            ),
            jev_model=os.getenv("EXAM_CHECKER_JEV_MODEL", "typesafe/jev-1.13").strip(),
            jev_timeout_seconds=_positive_float("EXAM_CHECKER_JEV_TIMEOUT_SECONDS", 30),
            jev_max_concurrency=_positive_int("EXAM_CHECKER_JEV_MAX_CONCURRENCY", 8),
            jev_prompt_root=os.getenv(
                "EXAM_CHECKER_JEV_PROMPT_ROOT",
                str(default_prompt_root / "jev-prompt"),
            ).strip(),
            workflow_llm_base_url=(
                os.getenv("EXAM_CHECKER_WORKFLOW_LLM_BASE_URL", llm_base_url)
                .strip()
                .rstrip("/")
            ),
            workflow_llm_api_key=os.getenv(
                "EXAM_CHECKER_WORKFLOW_LLM_API_KEY", llm_api_key
            ).strip(),
            workflow_llm_model=os.getenv(
                "EXAM_CHECKER_WORKFLOW_LLM_MODEL", llm_model
            ).strip(),
            workflow_llm_timeout_seconds=_positive_float(
                "EXAM_CHECKER_WORKFLOW_LLM_TIMEOUT_SECONDS", 180
            ),
            workflow_llm_max_concurrency=_positive_int(
                "EXAM_CHECKER_WORKFLOW_LLM_MAX_CONCURRENCY", 8
            ),
            revision_prompt_root=os.getenv(
                "EXAM_CHECKER_REVISION_PROMPT_ROOT",
                str(default_prompt_root / "question-revision-prompt"),
            ).strip(),
            metadata_prompt_root=os.getenv(
                "EXAM_CHECKER_METADATA_PROMPT_ROOT",
                str(default_prompt_root / "question-metadata-prompt"),
            ).strip(),
            knowledge_base_dir=os.getenv(
                "EXAM_CHECKER_KB_DIR",
                "",
            ).strip(),
        )
