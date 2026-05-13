"""Lightweight Gemini API usage tracking.

A :class:`ContextVar` holds an :class:`ApiUsage` accumulator for the duration
of a logical request (a Discord message turn, a summary refresh, etc.). Every
embedding and generate call records its own timing/tokens into the active
accumulator and emits a DEBUG line. When the accumulator is closed via
:func:`track_usage`, an INFO summary is written for the whole cycle.
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


def current_usage() -> Optional[ApiUsage]:
    return _current.get()


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
        wall_elapsed = time.monotonic() - wall_started
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


def open_usage(label: str) -> tuple[ApiUsage, Any, float]:
    """Manual scope opener for sites where `with` is awkward (e.g. wrapping
    a long async-with body without re-indenting). Pair with :func:`close_usage`.

    The label is captured here and replayed at close time.
    """
    usage = ApiUsage()
    token = _current.set(usage)
    return usage, token, time.monotonic()


def close_usage(
    usage: ApiUsage, token: Any, wall_started: float, label: str
) -> None:
    """Counterpart to :func:`open_usage`. Emits the INFO summary line."""
    try:
        _current.reset(token)
    except (ValueError, LookupError):
        # Token was set in a different context (e.g. nested misuse); fall back
        # to clearing globally.
        _current.set(None)
    wall_elapsed = time.monotonic() - wall_started
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
