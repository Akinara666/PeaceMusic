"""Lightweight Gemini API usage tracking.

A :class:`ContextVar` holds an :class:`ApiUsage` accumulator for the duration
of a logical request (a Discord message turn, a summary refresh, etc.). Open a
scope with the :func:`track_usage` context manager; every embedding and generate
call made inside it records its own timing/tokens into the active accumulator and
emits a DEBUG line. On exit an INFO summary is written for the whole cycle.
"""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Iterator, Optional

logger = logging.getLogger(__name__)


@dataclass
class ApiUsage:
    generate_calls: int = 0
    embed_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    thoughts_tokens: int = 0
    total_api_seconds: float = 0.0


_current: ContextVar[Optional[ApiUsage]] = ContextVar("peace_music_api_usage", default=None)


def _log_usage(label: str, usage: ApiUsage, wall_elapsed: float) -> None:
    logger.info(
        "%s: generate=%d embed=%d tokens(in/out/thoughts)=%d/%d/%d "
        "api=%.2fs wall=%.2fs",
        label,
        usage.generate_calls,
        usage.embed_calls,
        usage.input_tokens,
        usage.output_tokens,
        usage.thoughts_tokens,
        usage.total_api_seconds,
        wall_elapsed,
    )


@contextmanager
def track_usage(label: str) -> Iterator[ApiUsage]:
    """Open a usage accumulator for the duration of a logical request.

    The label appears in the INFO summary line emitted on exit.
    """
    usage = ApiUsage()
    token = _current.set(usage)
    wall_started = time.monotonic()
    try:
        yield usage
    finally:
        _current.reset(token)
        _log_usage(label, usage, time.monotonic() - wall_started)


def _extract_token_counts(usage_meta: Optional[Any]) -> tuple[int, int, int]:
    if usage_meta is None:
        return 0, 0, 0
    return (
        int(getattr(usage_meta, "prompt_token_count", 0) or 0),
        int(getattr(usage_meta, "candidates_token_count", 0) or 0),
        int(getattr(usage_meta, "thoughts_token_count", 0) or 0),
    )


def record_generate(
    model: str, elapsed: float, usage_meta: Optional[Any] = None
) -> None:
    in_tokens, out_tokens, thoughts = _extract_token_counts(usage_meta)
    counter = _current.get()
    if counter is not None:
        counter.generate_calls += 1
        counter.input_tokens += in_tokens
        counter.output_tokens += out_tokens
        counter.thoughts_tokens += thoughts
        counter.total_api_seconds += elapsed
    logger.debug(
        "generate: model=%s elapsed=%.2fs in=%d out=%d thoughts=%d",
        model,
        elapsed,
        in_tokens,
        out_tokens,
        thoughts,
    )


def record_embed(model: str, task: str, elapsed: float) -> None:
    counter = _current.get()
    if counter is not None:
        counter.embed_calls += 1
        counter.total_api_seconds += elapsed
    logger.debug("embed: model=%s task=%s elapsed=%.2fs", model, task, elapsed)
