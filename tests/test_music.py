from __future__ import annotations

import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

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
        self.assertFalse(music_module._is_allowed_media_url("http://127.0.0.1/private"))
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

    def test_fresh_deferred_stream_reuses_extracted_url(self) -> None:
        player = music_module.Music(SimpleNamespace())
        track = music_module.QueuedTrack(
            source=music_module._DeferredAudioSource(),
            title="Track",
            requester=SimpleNamespace(),
            stream_url="https://example.test/audio.webm",
            should_stream=True,
            source_prepared=False,
        )

        refreshed = asyncio.run(player._refresh_track_source(track))

        self.assertTrue(refreshed)
        self.assertTrue(track.source_prepared)
        self.assertEqual(track.source.original.source, track.stream_url)

    def test_active_stream_refresh_leaves_old_source_for_player_cleanup(self) -> None:
        player = music_module.Music(SimpleNamespace())
        old_source = Mock()
        new_source = Mock()
        track = music_module.QueuedTrack(
            source=old_source,
            title="Track",
            requester=SimpleNamespace(),
            stream_url="https://example.test/audio.webm",
            should_stream=True,
        )

        with patch.object(
            player,
            "_create_stream_track_source",
            return_value=new_source,
        ):
            refreshed = asyncio.run(
                player._refresh_track_source(track, cleanup_existing=False)
            )

        self.assertTrue(refreshed)
        self.assertIs(track.source, new_source)
        old_source.cleanup.assert_not_called()

    def test_transient_voice_disconnect_preserves_playback_source(self) -> None:
        player = music_module.Music(SimpleNamespace())
        source = Mock()
        track = music_module.QueuedTrack(
            source=source,
            title="Track",
            requester=SimpleNamespace(),
        )
        voice_client = SimpleNamespace(
            is_connected=Mock(return_value=False),
            is_playing=Mock(return_value=True),
            is_paused=Mock(return_value=False),
            stop=Mock(),
        )
        guild = SimpleNamespace(voice_client=voice_client)
        player.voice_client = voice_client
        player.current = track

        with patch.object(music_module.asyncio, "sleep", new=AsyncMock()):
            asyncio.run(player._handle_voice_disconnect_event(guild))

        self.assertIs(player.voice_client, voice_client)
        self.assertIs(player.current, track)
        source.cleanup.assert_not_called()
        voice_client.stop.assert_not_called()

    def test_permanent_voice_disconnect_stops_without_racing_source(self) -> None:
        player = music_module.Music(SimpleNamespace())
        source = Mock()
        queued_source = Mock()
        player.current = music_module.QueuedTrack(
            source=source,
            title="Current",
            requester=SimpleNamespace(),
        )
        player.queue.append(
            music_module.QueuedTrack(
                source=queued_source,
                title="Queued",
                requester=SimpleNamespace(),
            )
        )
        voice_client = SimpleNamespace(
            is_connected=Mock(return_value=False),
            is_playing=Mock(return_value=True),
            is_paused=Mock(return_value=False),
            stop=Mock(),
        )
        player.voice_client = voice_client
        guild = SimpleNamespace(voice_client=None)

        with patch.object(music_module.asyncio, "sleep", new=AsyncMock()):
            asyncio.run(player._handle_voice_disconnect_event(guild))

        self.assertIsNone(player.voice_client)
        self.assertIsNone(player.current)
        self.assertFalse(player.queue)
        voice_client.stop.assert_called_once_with()
        source.cleanup.assert_not_called()
        queued_source.cleanup.assert_called_once_with()
