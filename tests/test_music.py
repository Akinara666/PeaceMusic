from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from tests.stub_modules import import_project_package, install_stubs

install_stubs()

with patch.dict(
    os.environ,
    {"DISCORD_BOT_TOKEN": "token", "GEMINI_API_KEY": "key"},
    clear=True,
):
    music_module = import_project_package("cogs.music_cog")


class MusicHelperTests(unittest.TestCase):
    def test_duration_and_time_parsing(self) -> None:
        self.assertEqual(music_module.format_duration(65), "01:05")
        self.assertEqual(music_module.format_duration(3661), "01:01:01")
        self.assertEqual(music_module.format_duration("bad"), "00:00")
        self.assertEqual(music_module.parse_time("1:02:03"), 3723)
        with self.assertRaises(ValueError):
            music_module.parse_time("1:bad")
        with self.assertRaises(ValueError):
            music_module.parse_time("-1")

    def test_query_normalization_and_domain_allowlist(self) -> None:
        self.assertEqual(
            music_module.normalize_audio_query("sc: artist song"),
            "scsearch1:artist song",
        )
        self.assertTrue(
            music_module.is_soundcloud_query(
                music_module.normalize_audio_query("sc song")
            )
        )
        self.assertTrue(
            music_module._is_allowed_media_url("https://music.youtube.com/watch?v=x")
        )
        self.assertFalse(
            music_module._is_allowed_media_url("http://127.0.0.1/private")
        )
        self.assertFalse(
            music_module._is_allowed_media_url("https://youtube.com@example.org/x")
        )

    def test_ffmpeg_options_include_seek(self) -> None:
        options = music_module.build_ffmpeg_options(stream=False, seek=12)
        self.assertIn("-ss 12", options["before_options"])

    def test_player_state_is_isolated_per_guild(self) -> None:
        root = music_module.Music(SimpleNamespace())
        first_message = SimpleNamespace(guild=SimpleNamespace(id=1))
        second_message = SimpleNamespace(guild=SimpleNamespace(id=2))

        first = root._player_for_message(first_message)
        first_again = root._player_for_message(first_message)
        second = root._player_for_message(second_message)
        first.loop_mode = "track"

        self.assertIs(first, first_again)
        self.assertIsNot(first, second)
        self.assertEqual(second.loop_mode, "off")
        self.assertEqual(root.loop_mode, "off")

    def test_deferred_source_does_not_spawn_ffmpeg(self) -> None:
        source = music_module._DeferredAudioSource()
        self.assertEqual(source.read(), b"")
