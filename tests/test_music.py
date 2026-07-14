from __future__ import annotations

import asyncio
import os
import threading
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
        self.assertIsInstance(track.source, music_module._BufferedAudioSource)
        self.assertEqual(track.source.source.original.source, track.stream_url)
        track.source.volume = 0.5
        self.assertEqual(track.source.source.volume, 0.5)
        track.source.cleanup()

    def test_buffered_source_masks_a_temporary_input_stall(self) -> None:
        release_second_frame = threading.Event()
        first_frame_read = threading.Event()
        second_frame = b"b" * music_module.PCM_FRAME_BYTES

        class ControlledSource:
            def __init__(self) -> None:
                self.read_count = 0

            def read(self) -> bytes:
                self.read_count += 1
                if self.read_count == 1:
                    first_frame_read.set()
                    return b"a" * music_module.PCM_FRAME_BYTES
                if self.read_count == 2:
                    release_second_frame.wait(timeout=1)
                    return second_frame
                return b""

            def cleanup(self) -> None:
                release_second_frame.set()

        played_frames: list[bytes] = []
        source = music_module._BufferedAudioSource(
            ControlledSource(),
            label="test",
            max_buffer_seconds=0.1,
            start_buffer_seconds=0,
            start_timeout_seconds=0.1,
            underrun_grace_seconds=1,
            on_played_frame=played_frames.append,
        )
        self.assertTrue(first_frame_read.wait(timeout=1))
        self.assertEqual(source.read(), b"a" * music_module.PCM_FRAME_BYTES)
        self.assertEqual(source.read(), music_module.PCM_SILENCE_FRAME)
        self.assertEqual(played_frames, [b"a" * music_module.PCM_FRAME_BYTES])

        release_second_frame.set()
        for _ in range(10):
            recovered = source.read()
            if recovered == second_frame:
                break
        self.assertEqual(recovered, second_frame)
        self.assertEqual(source.underrun_count, 1)
        source.cleanup()

    def test_progress_counts_real_pcm_instead_of_wall_clock(self) -> None:
        player = music_module.Music(SimpleNamespace())
        player._mark_playback_started(start_at=30)

        with patch.object(music_module.time_module, "monotonic", return_value=99999):
            player._record_played_audio_frame(
                b"x" * int(music_module.PCM_BYTES_PER_SECOND * 2.5)
            )

        self.assertEqual(player._current_progress_seconds(), 32)

    def test_monitor_distinguishes_natural_and_early_buffered_eof(self) -> None:
        class FiniteSource:
            def __init__(self) -> None:
                self.finished = False

            def read(self) -> bytes:
                if self.finished:
                    return b""
                self.finished = True
                return b"x" * music_module.PCM_FRAME_BYTES

            def cleanup(self) -> None:
                return None

        source = music_module._BufferedAudioSource(
            FiniteSource(),
            label="finite",
            max_buffer_seconds=0.1,
            start_buffer_seconds=0,
            start_timeout_seconds=0.1,
            underrun_grace_seconds=1,
        )
        self.assertTrue(source._source_ended.wait(timeout=1))
        player = music_module.Music(SimpleNamespace())
        player.voice_client = SimpleNamespace(is_playing=Mock(return_value=True))
        player.current = music_module.QueuedTrack(
            source=source,
            title="Track",
            requester=SimpleNamespace(),
            stream_url="https://example.test/audio.webm",
            duration=1,
            should_stream=True,
        )

        with patch.object(
            player,
            "_restart_current_stream",
            new=AsyncMock(),
        ) as restart:
            asyncio.run(player._monitor_stalled_playback_once())
            restart.assert_not_awaited()

            player.current.duration = 100
            asyncio.run(player._monitor_stalled_playback_once())
            restart.assert_awaited_once()
        source.cleanup()

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

    def test_stream_refresh_seeks_from_progress_after_extraction(self) -> None:
        player = music_module.Music(SimpleNamespace(loop=object()))
        old_source = Mock()
        prepared_source = Mock()
        track = music_module.QueuedTrack(
            source=old_source,
            title="Track",
            requester=SimpleNamespace(),
            stream_url="https://example.test/old.webm",
            reload_query="https://example.test/watch",
            should_stream=True,
        )
        metadata_source = SimpleNamespace(
            title="Track",
            url="https://example.test/new.webm",
            is_stream=True,
            webpage_url="https://example.test/watch",
            thumbnail="",
            uploader="Uploader",
            duration=600,
            local_path=None,
            is_youtube_hls=False,
            user_agent="test-agent",
        )

        with (
            patch.object(
                music_module.YTDLSource,
                "from_url",
                new=AsyncMock(return_value=[metadata_source]),
            ),
            patch.object(
                player,
                "_current_progress_seconds",
                return_value=42,
            ),
            patch.object(
                player,
                "_create_stream_track_source",
                return_value=prepared_source,
            ) as create_source,
        ):
            refreshed = asyncio.run(
                player._refresh_track_source(
                    track,
                    force_extract=True,
                    cleanup_existing=False,
                    follow_playback_progress=True,
                )
            )

        self.assertTrue(refreshed)
        create_source.assert_called_once_with(track, seek=40)
        self.assertIs(track.source, prepared_source)
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
