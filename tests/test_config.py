from __future__ import annotations

import os
import unittest
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
        self.assertEqual(
            settings.gemini.embedding_model, "gemini-embedding-2-preview"
        )
        self.assertEqual(settings.gemini.embedding_dimensions, 768)
        self.assertEqual(str(settings.misc.music_directory), "test_music_dir")

        self.assertEqual(str(settings.memory.db_file), "chat_memory.sqlite3")
        self.assertEqual(settings.memory.recent_messages_limit, 12)
        self.assertEqual(settings.memory.semantic_results_limit, 6)
        self.assertEqual(settings.memory.summary_trigger_messages, 30)
        self.assertEqual(settings.misc.status_message, "Test Bot")
        self.assertNotIn("cookiefile", settings.audio.ytdl_options)

    def test_load_settings_enables_cookiefile_only_when_requested(self) -> None:
        mock_env = {
            "DISCORD_BOT_TOKEN": "test_token",
            "GEMINI_API_KEY": "test_key",
            "YTDL_USE_COOKIES": "true",
            "YTDL_COOKIE_FILE": "custom/cookies.txt",
        }

        with patch.dict(os.environ, mock_env, clear=True):
            config_module = load_project_module("test_config_module_cookies", "config.py")
            settings = config_module.load_settings()

        self.assertIn("cookiefile", settings.audio.ytdl_options)
        self.assertTrue(
            settings.audio.ytdl_options["cookiefile"].endswith("custom/cookies.txt")
        )
