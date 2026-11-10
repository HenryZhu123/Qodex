import os
from pathlib import Path

from exam_checker.config import _load_env_file, _load_local_environment


def test_env_file_loads_values_without_overriding_process_env(
    tmp_path: Path, monkeypatch
) -> None:
    env_file = tmp_path / ".env.local"
    env_file.write_text(
        "# local config\n"
        "EXAM_CHECKER_REVIEW_LLM_BASE_URL=https://relay.example/v1\n"
        "EXAM_CHECKER_JEV_API_KEY='file-secret'\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("EXAM_CHECKER_JEV_API_KEY", "process-secret")
    monkeypatch.delenv("EXAM_CHECKER_REVIEW_LLM_BASE_URL", raising=False)

    assert _load_env_file(env_file) is True
    assert os.environ["EXAM_CHECKER_REVIEW_LLM_BASE_URL"] == "https://relay.example/v1"
    assert os.environ["EXAM_CHECKER_JEV_API_KEY"] == "process-secret"


def test_explicit_env_file_has_priority(monkeypatch, tmp_path: Path) -> None:
    explicit = tmp_path / "custom.env"
    explicit.write_text("EXAM_CHECKER_JEV_BASE_URL=https://jev.example/api\n", encoding="utf-8")
    monkeypatch.setenv("EXAM_CHECKER_ENV_FILE", str(explicit))
    monkeypatch.delenv("EXAM_CHECKER_JEV_BASE_URL", raising=False)

    assert _load_local_environment(tmp_path) == [explicit.resolve()]
    assert os.environ["EXAM_CHECKER_JEV_BASE_URL"] == "https://jev.example/api"
