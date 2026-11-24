#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Entry point for deterministic factual guards.

The guards themselves are subject knowledge, so none of them live here. This module
only dispatches to a profile that configuration selects:

    EXAM_CHECKER_GUARD_PROFILE=computer_science

With no profile configured the function returns None, and factual/logical review
falls to the model alone. That default is deliberate: the neutral pipeline must not
carry one discipline's invariants for every subject. A new subject is supported by
writing a profile module (see ``guards/``) rather than by editing the pipeline.
"""

from __future__ import annotations

import os

from ..domain.models import SpecialistReviewResult
from .guards import resolve

PROFILE_ENV = "EXAM_CHECKER_GUARD_PROFILE"


def active_profile() -> str:
    """The configured profile name, or an empty string when guards are off."""
    return os.environ.get(PROFILE_ENV, "").strip()


def check_factual_guards(
    full_text: str,
    profile: str | None = None,
) -> SpecialistReviewResult | None:
    """Run the configured subject guard over the question text.

    ``profile`` overrides configuration; it exists so tests and offline tools can
    pin a profile without touching the environment.
    """
    name = profile if profile is not None else active_profile()
    module = resolve(name)
    if module is None or not full_text:
        return None
    return module.check(full_text)
