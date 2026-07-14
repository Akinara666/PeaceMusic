from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.stub_modules import install_stubs, load_project_module

install_stubs()


class ConfigTests(unittest.TestCase):
    def test_load_settings_smoke(self) -> None:
        mock_env = {
            "DISCORD_BOT_TOKEN": "test_token",
            "GEMINI_API_KEY": "test_key",
            "GEMINI_RESPONSE_MODEL": "gemini-2.5-flash",
            "GEMINI_SUMMARY_MODEL": "gemini-3.1-flash-lite",
            "GEMINI_EMBEDDING_MODEL": "gemini-embedding-2-preview",
            "MUSIC_DIRECTORY": "test_music_dir",
            "CHAT_MEMORY_DB": "chat_memory.sqlite3",
            "DISCORD_STATUS_MESSAGE": "Test Bot",
        }

        with patch.dict(os.environ, mock_env, clear=True):
            config_module = load_project_module("test_config_module", "config.py")
            settings = config_module.load_settings()

        self.assertEqual(settings.discord.token, "test_token")
        self.assertEqual(settings.gemini.api_key, "test_key")
        self.assertEqual(settings.gemini.response_model, "gemini-2.5-flash")
        self.assertEqual(settings.gemini.summary_model, "gemini-3.1-flash-lite")
        self.assertEqual(settings.gemini.embedding_model, "gemini-embedding-2-preview")
        self.assertEqual(settings.gemini.embedding_dimensions, 768)
        self.assertIsNone(settings.gemini.socks_proxy)
        self.assertEqual(settings.misc.music_directory.name, "test_music_dir")
        self.assertTrue(settings.misc.music_directory.is_absolute())

        self.assertEqual(str(settings.memory.db_file), "chat_memory.sqlite3")
        self.assertEqual(settings.memory.recent_messages_limit, 12)
        self.assertEqual(settings.memory.semantic_results_limit, 6)
        self.assertEqual(settings.memory.summary_trigger_messages, 30)
        self.assertEqual(settings.misc.status_message, "Test Bot")
        self.assertNotIn("cookiefile", settings.audio.ytdl_options)
        self.assertEqual(
            settings.audio.ytdl_options["js_runtimes"],
            {"deno": {}, "node": {}},
        )
        self.assertEqual(settings.audio.stream_buffer_seconds, 20.0)
        self.assertEqual(settings.audio.stream_start_buffer_seconds, 5.0)
        self.assertEqual(settings.audio.stream_stall_timeout_seconds, 10.0)
        self.assertIn(
            "-rw_timeout 8000000",
            settings.audio.ffmpeg_options["before_options_stream"],
        )
        self.assertNotIn("-bufsize", settings.audio.ffmpeg_options["options"])

    def test_load_settings_rejects_start_buffer_larger_than_buffer(self) -> None:
        mock_env = {
            "DISCORD_BOT_TOKEN": "test_token",
            "GEMINI_API_KEY": "test_key",
            "MUSIC_STREAM_BUFFER_SECONDS": "4",
            "MUSIC_STREAM_START_BUFFER_SECONDS": "5",
        }

        with patch.dict(os.environ, mock_env, clear=True):
            with self.assertRaisesRegex(
                RuntimeError, "MUSIC_STREAM_START_BUFFER_SECONDS must be <= 4"
            ):
                load_project_module("test_config_module_invalid_buffer", "config.py")

    def test_load_settings_enables_cookiefile_only_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            cookie_path = Path(temporary_directory) / "cookies.txt"
            cookie_path.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
            mock_env = {
                "DISCORD_BOT_TOKEN": "test_token",
                "GEMINI_API_KEY": "test_key",
                "YTDL_USE_COOKIES": "true",
                "YTDL_COOKIE_FILE": str(cookie_path),
            }

            with patch.dict(os.environ, mock_env, clear=True):
                config_module = load_project_module(
                    "test_config_module_cookies", "config.py"
                )
                settings = config_module.load_settings()

        self.assertIn("cookiefile", settings.audio.ytdl_options)
        self.assertEqual(settings.audio.ytdl_options["cookiefile"], str(cookie_path))

    def test_load_settings_rejects_invalid_cookie_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            cookie_path = Path(temporary_directory) / "cookies.txt"
            cookie_path.write_text("not a cookie jar\n", encoding="utf-8")
            mock_env = {
                "DISCORD_BOT_TOKEN": "test_token",
                "GEMINI_API_KEY": "test_key",
                "YTDL_USE_COOKIES": "true",
                "YTDL_COOKIE_FILE": str(cookie_path),
            }

            with patch.dict(os.environ, mock_env, clear=True):
                with self.assertRaisesRegex(RuntimeError, "Mozilla/Netscape"):
                    load_project_module(
                        "test_config_module_invalid_cookies", "config.py"
                    )

    def test_load_settings_reads_optional_gemini_socks_proxy(self) -> None:
        mock_env = {
            "DISCORD_BOT_TOKEN": "test_token",
            "GEMINI_API_KEY": "test_key",
            "GEMINI_SOCKS_PROXY": "socks5://127.0.0.1:40000",
        }

        with patch.dict(os.environ, mock_env, clear=True):
            config_module = load_project_module("test_config_module_proxy", "config.py")
            settings = config_module.load_settings()

        self.assertEqual(settings.gemini.socks_proxy, "socks5://127.0.0.1:40000")
