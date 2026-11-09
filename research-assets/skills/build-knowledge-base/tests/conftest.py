"""Shared setup for the knowledge-base skill tests.

The skill's modules import each other by bare name (``from utils import ...``),
so the scripts directory has to be on sys.path before any test module imports
them.
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
