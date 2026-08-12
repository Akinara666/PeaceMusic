from __future__ import annotations

import pytest

from peacemusic.adapters.discord.cogs.chat import split_message


def test_split_message_respects_discord_limit() -> None:
    chunks = split_message("x" * 4501, limit=2000)
    assert [len(chunk) for chunk in chunks] == [2000, 2000, 501]
    assert split_message("") == []


def test_split_message_rejects_invalid_limit() -> None:
    with pytest.raises(ValueError):
        split_message("text", limit=0)
