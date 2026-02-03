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
        assert str(settings.misc.music_directory) == "test_music_dir"
        assert str(settings.misc.context_file) == "test_context.json"
        assert settings.misc.status_message == "Test Bot"
