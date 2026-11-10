"""Shared setup for the knowledge-base skill tests.

The skill's modules import each other by bare name (``from utils import ...``),
so the scripts directory has to be on sys.path before any test module imports
them.

pytest's own ``tmp_path`` lands under the OS temp directory, which the Windows
sandbox denies; ``tmp_dir`` creates scratch directories inside the repository
instead and removes them afterwards.
"""

from __future__ import annotations

import shutil
import sys
import uuid
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
SCRIPTS = TESTS.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

SCRATCH = TESTS / ".tmp"


@pytest.fixture()
def tmp_dir() -> Path:
    SCRATCH.mkdir(parents=True, exist_ok=True)
    path = SCRATCH / uuid.uuid4().hex[:8]
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
