"""Subject guard profiles.

The review pipeline carries no subject knowledge of its own: deterministic factual
checks are optional profiles, and a profile is used only when configuration names
it. A profile decides which contradictions count as wrong in one discipline; it
does not change how a question is reviewed.

Enable one with:

    EXAM_CHECKER_GUARD_PROFILE=computer_science

Leave it unset (the default) and factual review is model-only, which is the
behaviour for any subject without a profile.
"""

from __future__ import annotations

from types import ModuleType

from exam_checker.parsing.guards import computer_science

PROFILES: dict[str, ModuleType] = {
    "computer_science": computer_science,
}


def resolve(name: str) -> ModuleType | None:
    """Return the profile module for a configured name, or None when unknown."""
    return PROFILES.get(name.strip())


def available_profiles() -> tuple[str, ...]:
    return tuple(sorted(PROFILES))
