"""Structured logging setup without import-time global side effects."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

_STRUCTURED_FIELDS = (
    "request_id",
    "guild_id",
    "channel_id",
    "user_id",
    "tool_name",
    "tool_category",
    "tool_call_number",
    "tool_context",
    "tool_arguments",
    "tool_ok",
    "tool_code",
    "tool_result",
    "tool_duration_ms",
    "agent_thread_id",
)


class JsonFormatter(logging.Formatter):
    """Render log records as compact JSON suitable for container logs."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        for field in _STRUCTURED_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        return json.dumps(payload, ensure_ascii=False, default=str)


class ContextFormatter(logging.Formatter):
    """Render structured fields in human-readable development logs."""

    def format(self, record: logging.LogRecord) -> str:
        message = super().format(record)
        fields = []
        for field in _STRUCTURED_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                fields.append(
                    f"{field}={json.dumps(value, ensure_ascii=False, default=str)}"
                )
        return f"{message} {' '.join(fields)}" if fields else message


def configure_logging(level: str = "INFO", *, json_logs: bool = True) -> None:
    """Configure the root handler once from the composition root."""

    normalized_level = getattr(logging, level.upper(), None)
    if not isinstance(normalized_level, int):
        raise ValueError(f"Unknown log level: {level!r}")

    root = logging.getLogger()
    root.setLevel(normalized_level)
    if root.handlers:
        for handler in root.handlers:
            handler.setLevel(normalized_level)
            handler.setFormatter(
                JsonFormatter()
                if json_logs
                else ContextFormatter(
                    "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
                )
            )
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(normalized_level)
    handler.setFormatter(
        JsonFormatter()
        if json_logs
        else ContextFormatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    root.addHandler(handler)
