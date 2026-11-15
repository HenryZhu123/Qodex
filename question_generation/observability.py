"""Structured JSON logging and in-process counters for question generation.

Only the standard library is used. ``configure()`` installs one JSON-lines
handler on stderr; ``event()`` also keeps counters that ``snapshot()`` exposes
for lightweight operational inspection. Unknown fields are serialized with
``str`` so a log call can never change a request's outcome.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from collections import Counter
from contextvars import ContextVar

LOGGER_NAME = "question_generation"
LOG_LEVEL_ENV = "QUESTION_GENERATION_LOG_LEVEL"

trace_id: ContextVar[str | None] = ContextVar("question_generation_trace_id", default=None)
_COUNTERS: Counter[str] = Counter()
_COUNTERS_LOCK = threading.Lock()
_HANDLER_FLAG = "_question_generation_json_handler"


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)),
            "level": record.levelname,
            "event": record.getMessage(),
        }
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            payload.update(fields)
        return json.dumps(payload, ensure_ascii=False, default=str)


def _json_handlers(logger: logging.Logger) -> list[logging.Handler]:
    return [handler for handler in logger.handlers if getattr(handler, _HANDLER_FLAG, False)]


def configure(level: str | None = None) -> logging.Logger:
    """Install the JSON handler once and apply ``QUESTION_GENERATION_LOG_LEVEL``."""
    name = (level or os.environ.get(LOG_LEVEL_ENV) or "INFO").strip().upper()
    numeric = getattr(logging, name, None)
    if not isinstance(numeric, int):
        numeric = logging.INFO
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(numeric)
    logger.propagate = False
    if not _json_handlers(logger):
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(_JsonFormatter())
        setattr(handler, _HANDLER_FLAG, True)
        logger.addHandler(handler)
    return logger


def new_trace_id() -> str:
    """Start a new trace in the current context and return its identifier."""
    value = os.urandom(8).hex()
    trace_id.set(value)
    return value


def event(name: str, **fields: object) -> None:
    """Record one structured event. Payloads, answers and materials are not logged."""
    with _COUNTERS_LOCK:
        _COUNTERS[name] += 1
    logger = logging.getLogger(LOGGER_NAME)
    # Without a handler and without a log-level env the module stays silent
    # (counters still work). Services call configure() during startup; tests may
    # attach their own handler (for example assertLogs).
    if not logger.handlers:
        if not os.environ.get(LOG_LEVEL_ENV):
            return
        try:
            configure()
        except Exception:  # pragma: no cover - logging must never break a request
            return
    record = dict(fields)
    current = trace_id.get()
    if current is not None:
        record.setdefault("trace_id", current)
    try:
        logger.info(name, extra={"fields": record})
    except Exception:  # pragma: no cover - logging must never break a request
        pass


def snapshot() -> Counter[str]:
    """Return a copy of the event-name counters."""
    with _COUNTERS_LOCK:
        return Counter(_COUNTERS)
