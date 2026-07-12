from __future__ import annotations

import unittest
from types import SimpleNamespace

from tests.stub_modules import install_stubs, import_project_package

install_stubs()
response_module = import_project_package("cogs.ai.response")

ResponseGenerator = response_module.ResponseGenerator
types = response_module.types


class FakeApiError(Exception):
    def __init__(self, message: str, *, status_code=None, code=None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


class FakeAsyncModels:
    def __init__(self, sequence):
        self.sequence = list(sequence)
        self.calls = []

    async def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        item = self.sequence.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeAsyncFiles:
    def __init__(self, invalid_names=None):
        self.invalid_names = set(invalid_names or [])

    async def get(self, name: str):
        if name in self.invalid_names:
            raise FakeApiError("404 NOT_FOUND", status_code=404)
        return SimpleNamespace(name=name)


def make_response(parts):
    content = types.Content(role="model", parts=parts)
    return types.GenerateContentResponse(
        candidates=[types.Candidate(content=content)],
        text=None,
    )


class ResponseGeneratorTests(unittest.IsolatedAsyncioTestCase):
    async def test_generate_reply_returns_plain_text(self) -> None:
        models = FakeAsyncModels([make_response([types.Part.from_text(text="ready")])])
        client = SimpleNamespace(
            aio=SimpleNamespace(models=models, files=FakeAsyncFiles())
        )
        generator = ResponseGenerator(
            client=client,
            model_name="reply-model",
            tools=[],
            system_instruction="base prompt",
            thinking_budget=32,
        )
        history = [types.Content(role="user", parts=[types.Part.from_text("hello")])]

        result = await generator.generate_reply(history, self._tool_callback)

        self.assertEqual(result, "ready")
        self.assertEqual(len(history), 2)
        self.assertEqual(
            models.calls[0]["config"].system_instruction,
            "base prompt",
        )

    async def test_generate_reply_runs_tool_callback_and_continues(self) -> None:
        first = make_response(
            [types.Part.from_function_call(name="react", args={"emoji": "🔥"})]
        )
        second = make_response([types.Part.from_text(text="done")])
        models = FakeAsyncModels([first, second])
        client = SimpleNamespace(
            aio=SimpleNamespace(models=models, files=FakeAsyncFiles())
        )
        generator = ResponseGenerator(
            client=client,
            model_name="reply-model",
            tools=[],
            system_instruction="base prompt",
        )
        history = [types.Content(role="user", parts=[types.Part.from_text("hello")])]
        seen_calls = []

        async def tool_callback(function_call):
            seen_calls.append((function_call.name, function_call.args))
            return types.Part.from_function_response(
                name=function_call.name,
                response={"ok": True},
            )

        result = await generator.generate_reply(
            history,
            tool_callback,
            system_instruction="override prompt",
        )

        self.assertEqual(result, "done")
        self.assertEqual(seen_calls, [("react", {"emoji": "🔥"})])
        self.assertEqual(
            models.calls[0]["config"].system_instruction, "override prompt"
        )
        self.assertEqual(len(history), 4)

    async def test_generate_reply_sanitizes_expired_files_and_retries(self) -> None:
        history = [
            types.Content(
                role="user",
                parts=[types.Part.from_uri(file_uri="https://example.com/files/123")],
            )
        ]
        models = FakeAsyncModels(
            [
                FakeApiError("404 NOT_FOUND", status_code=404),
                make_response([types.Part.from_text(text="recovered")]),
            ]
        )
        client = SimpleNamespace(
            aio=SimpleNamespace(models=models, files=FakeAsyncFiles({"files/123"}))
        )
        generator = ResponseGenerator(
            client=client,
            model_name="reply-model",
            tools=[],
            system_instruction="base prompt",
        )

        result = await generator.generate_reply(history, self._tool_callback)

        self.assertEqual(result, "recovered")
        self.assertEqual(history[0].parts[0].text, "[Expired Attachment]")

    async def test_parallel_tool_responses_share_turn_and_preserve_ids(self) -> None:
        first_call = types.Part.from_function_call(name="first", args={})
        first_call.function_call.id = "call-1"
        second_call = types.Part.from_function_call(name="second", args={})
        second_call.function_call.id = "call-2"
        models = FakeAsyncModels(
            [
                make_response([first_call, second_call]),
                make_response([types.Part.from_text(text="done")]),
            ]
        )
        client = SimpleNamespace(
            aio=SimpleNamespace(models=models, files=FakeAsyncFiles())
        )
        generator = ResponseGenerator(
            client=client,
            model_name="reply-model",
            tools=[],
            system_instruction="base prompt",
        )
        history = [types.Content(role="user", parts=[types.Part.from_text("go")])]

        result = await generator.generate_reply(history, self._tool_callback)

        self.assertEqual(result, "done")
        tool_turn = history[2]
        self.assertEqual(tool_turn.role, "user")
        self.assertEqual(len(tool_turn.parts), 2)
        self.assertEqual(
            [part.function_response.id for part in tool_turn.parts],
            ["call-1", "call-2"],
        )

    async def _tool_callback(self, function_call):
        return types.Part.from_function_response(
            name=function_call.name,
            response={"ok": True},
        )
