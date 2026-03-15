import sys
from pathlib import Path
from unittest.mock import patch

# Add project root to sys.path to allow importing config
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import load_settings  # noqa: E402


def test_load_settings_smoke():
    """Test that settings load correctly with mocked environment variables."""
    mock_env = {
        "DISCORD_BOT_TOKEN": "test_token",
        "GEMINI_API_KEY": "test_key",
        "MUSIC_DIRECTORY": "test_music_dir",
        "CONTEXT_FILE": "test_context.json",
        "DISCORD_STATUS_MESSAGE": "Test Bot",
    }

    with patch.dict("os.environ", mock_env):
        settings = load_settings()

        assert settings.discord.token == "test_token"
        assert settings.gemini.api_key == "test_key"
        assert settings.gemini.response_model == "gemini-2.5-flash"
        assert settings.gemini.summary_model == "gemini-3.1-flash-lite"
        assert settings.gemini.embedding_model == "gemini-embedding-2-preview"
        assert settings.gemini.embedding_dimensions == 768
        assert str(settings.misc.music_directory) == "test_music_dir"
        assert str(settings.misc.context_file) == "test_context.json"
        assert str(settings.memory.db_file) == "chat_memory.sqlite3"
        assert settings.memory.recent_messages_limit == 12
        assert settings.memory.semantic_results_limit == 6
        assert settings.memory.summary_trigger_messages == 30
        assert settings.misc.status_message == "Test Bot"
