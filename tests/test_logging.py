from __future__ import annotations

import json
import logging

from peacemusic.core.logging import ContextFormatter, JsonFormatter


def _record() -> logging.LogRecord:
    return logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="Agent tool call completed",
        args=(),
        exc_info=None,
    )


def test_json_formatter_includes_tool_diagnostics() -> None:
    record = _record()
    record.tool_name = "play_music"
    record.tool_arguments = {"query": "jazz"}
    record.tool_code = "OK"

    payload = json.loads(JsonFormatter().format(record))

    assert payload["tool_name"] == "play_music"
    assert payload["tool_arguments"] == {"query": "jazz"}
    assert payload["tool_code"] == "OK"


def test_context_formatter_includes_tool_diagnostics() -> None:
    record = _record()
    record.tool_name = "play_music"
    record.tool_arguments = {"query": "jazz"}

    formatted = ContextFormatter("%(message)s").format(record)

    assert 'tool_name="play_music"' in formatted
    assert 'tool_arguments={"query": "jazz"}' in formatted
