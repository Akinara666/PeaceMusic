from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from tests.stub_modules import import_project_package, install_stubs

install_stubs()

with patch.dict(
    os.environ,
    {
        "DISCORD_BOT_TOKEN": "token",
        "GEMINI_API_KEY": "key",
    },
    clear=True,
):
    cog_module = import_project_package("cogs.ai.cog")

GeminiChatCog = cog_module.GeminiChatCog
PreparedIncomingMessage = cog_module.PreparedIncomingMessage
StoredMessage = cog_module.StoredMessage
ToolExecutionEvent = cog_module.ToolExecutionEvent
types = cog_module.types


class GeminiChatCogTests(unittest.IsolatedAsyncioTestCase):
    async def test_process_tool_call_propagates_tool_notification_flag(self) -> None:
        music_cog = SimpleNamespace(
            play_func=AsyncMock(),
            skip_func=AsyncMock(),
            stop_func=AsyncMock(),
            set_volume_func=AsyncMock(),
            skip_by_name_func=AsyncMock(),
            seek_func=AsyncMock(),
            summon_func=AsyncMock(),
            disconnect_func=AsyncMock(),
            pause_func=AsyncMock(
                return_value=SimpleNamespace(
                    text="Воспроизведение на паузе",
                    user_notified=True,
                )
            ),
            resume_func=AsyncMock(),
            now_playing_func=AsyncMock(),
            get_queue_func=AsyncMock(),
            shuffle_queue_func=AsyncMock(),
            clear_queue_func=AsyncMock(),
            remove_from_queue_func=AsyncMock(),
            set_loop_mode_func=AsyncMock(),
        )
        cog = object.__new__(GeminiChatCog)
        cog.bot = SimpleNamespace(get_cog=lambda name: music_cog if name == "Music" else None)

        feedback = await cog.process_tool_call(
            types.FunctionCall(name="pause_music", args={}),
            SimpleNamespace(channel=SimpleNamespace()),
        )

        self.assertTrue(feedback.user_notified)
        self.assertEqual(
            feedback.part.function_response.response,
            {
                "result": "Воспроизведение на паузе",
                "user_notified": True,
            },
        )
        music_cog.pause_func.assert_awaited_once()

    async def test_on_message_sends_audio_attachment_fallback_when_tool_sends_nothing(self) -> None:
        class _TypingContext:
            async def __aenter__(self):
                return None

            async def __aexit__(self, exc_type, exc, tb):
                return False

        fake_result = SimpleNamespace(
            text="Добавлено в очередь: voice.mp3",
            user_notified=False,
        )
        fake_music_cog = SimpleNamespace(
            play_attachment_func=AsyncMock(return_value=fake_result)
        )
        fake_channel = SimpleNamespace(
            id=77,
            typing=lambda: _TypingContext(),
        )
        attachment = SimpleNamespace(content_type="audio/mpeg", filename="voice.mp3")
        message = SimpleNamespace(
            author=SimpleNamespace(id=10),
            channel=fake_channel,
            attachments=[attachment],
        )

        cog = object.__new__(GeminiChatCog)
        cog.bot = SimpleNamespace(
            user=SimpleNamespace(id=999),
            get_cog=lambda name: fake_music_cog if name == "Music" else None,
            process_commands=AsyncMock(),
        )
        cog._safe_channel_send = AsyncMock(return_value=SimpleNamespace(id=55))

        with patch.object(cog_module, "CHATBOT_CHANNEL_ID", None):
            await cog.on_message(message)

        fake_music_cog.play_attachment_func.assert_awaited_once_with(message, attachment)
        cog._safe_channel_send.assert_awaited_once_with(
            fake_channel,
            "Добавлено в очередь: voice.mp3",
        )
        cog.bot.process_commands.assert_not_awaited()

    def test_attachment_content_type_falls_back_to_filename(self) -> None:
        cog = object.__new__(GeminiChatCog)
        attachment = SimpleNamespace(content_type=None, filename="voice-message.mp3")

        content_type = cog._attachment_content_type(attachment)

        self.assertEqual(content_type, "audio/mpeg")

    async def test_persist_tool_events_stores_tool_rows(self) -> None:
        cog = object.__new__(GeminiChatCog)
        cog._safe_embed_document = AsyncMock(side_effect=["emb-1", "emb-2"])
        stored_messages = []

        async def fake_store_message(**kwargs):
            stored_messages.append(kwargs)
            return SimpleNamespace(**kwargs)

        cog._store_message = fake_store_message

        events = [
            ToolExecutionEvent(
                tool_name="play_music",
                args={"song_name": "Nujabes"},
                response={"result": "queued"},
                created_at="2026-03-15 21:00:00",
            ),
            ToolExecutionEvent(
                tool_name="set_volume",
                args={"level": 0.5},
                response={"error": "Nothing is playing"},
                created_at="2026-03-15 21:00:01",
            ),
        ]

        await cog._persist_tool_events(77, events)

        self.assertEqual(len(stored_messages), 2)
        self.assertEqual(stored_messages[0]["role"], "tool")
        self.assertEqual(stored_messages[0]["author_name"], "tool:play_music")
        self.assertEqual(stored_messages[0]["channel_id"], 77)
        self.assertEqual(stored_messages[0]["embedding"], "emb-1")
        self.assertIn('"song_name": "Nujabes"', stored_messages[0]["content_text"])
        self.assertIn('"result": "queued"', stored_messages[0]["content_text"])
        self.assertEqual(stored_messages[1]["author_name"], "tool:set_volume")
        self.assertIn('error: {"error": "Nothing is playing"}', stored_messages[1]["content_text"])

    def test_build_recent_contents_restores_serialized_file_parts(self) -> None:
        cog = object.__new__(GeminiChatCog)
        stored_message = StoredMessage(
            id=1,
            channel_id=77,
            discord_message_id=10,
            role="user",
            author_id=100,
            author_name="alice",
            content_text="[Image attachment: cat.png]",
            created_at="2026-03-15 21:10:00",
            content_parts=(
                {"type": "file_data", "uri": "uri://image", "mime_type": "image/png"},
                {
                    "type": "text",
                    "text": "[2026-03-15 21:10:00] alice [Image attachment: cat.png]",
                },
            ),
        )
        current_message = PreparedIncomingMessage(
            content=types.Content(
                role="user",
                parts=[types.Part.from_text(text="[2026-03-15 21:11:00] bob: what is this?")],
            ),
            memory_text="what is this?",
            author_name="bob",
            created_at="2026-03-15 21:11:00",
            content_parts=(
                {
                    "type": "text",
                    "text": "[2026-03-15 21:11:00] bob: what is this?",
                },
            ),
        )

        contents = cog._build_recent_contents([stored_message], current_message)

        self.assertEqual(contents[0].parts[0].file_data.uri, "uri://image")
        self.assertEqual(
            contents[0].parts[1].text,
            "[2026-03-15 21:10:00] alice [Image attachment: cat.png]",
        )

    def test_extract_tool_response_payload_and_render_memory_text(self) -> None:
        cog = object.__new__(GeminiChatCog)
        feedback = types.Part.from_function_response(
            name="skip_music",
            response={"result": "skipped"},
        )

        payload = cog._extract_tool_response_payload(feedback)
        text = cog._build_tool_memory_text(
            ToolExecutionEvent(
                tool_name="skip_music",
                args={"index": 1},
                response=payload,
                created_at="2026-03-15 21:00:02",
            )
        )

        self.assertEqual(payload, {"result": "skipped"})
        self.assertIn("[tool] skip_music", text)
        self.assertIn('args: {"index": 1}', text)
        self.assertIn('result: {"result": "skipped"}', text)
