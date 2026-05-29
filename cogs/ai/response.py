from __future__ import annotations

import asyncio
import logging
import time
from typing import Awaitable, Callable, List, Optional, TYPE_CHECKING

from google.genai import errors, types

from . import api_logger

if TYPE_CHECKING:  # pragma: no cover - type hints only
    from google import genai

logger = logging.getLogger(__name__)


ToolCallback = Callable[[types.FunctionCall], Awaitable[types.Part]]

# Safety valves for the agentic tool loop: cap total tool executions and the
# number of model<->tool round-trips so a misbehaving model cannot loop forever.
_MAX_TOOL_CALLS_PER_TURN = 20
_MAX_TOOL_ROUNDS = 12


class ResponseGenerator:
    """Generate Gemini responses while handling tool calls."""

    def __init__(
        self,
        client: "genai.Client",
        model_name: str,
        tools: List[types.Tool],
        system_instruction: str,
        temperature: float = 1.0,
        *,
        top_p: Optional[float] = None,
        frequency_penalty: Optional[float] = None,
        presence_penalty: Optional[float] = None,
        thinking_budget: int = 2048,
    ) -> None:
        self._client = client
        self._model_name = model_name
        self._tools = tools
        self._base_instruction = system_instruction
        self._temperature = temperature
        self._top_p = top_p
        self._frequency_penalty = frequency_penalty
        self._presence_penalty = presence_penalty
        self._thinking_budget = thinking_budget

    def _build_config(self, system_instruction: str) -> types.GenerateContentConfig:
        cfg_kwargs = {
            "tools": self._tools,
            "thinking_config": types.ThinkingConfig(
                thinking_budget=self._thinking_budget
            ),
            "system_instruction": system_instruction,
            "temperature": self._temperature,
        }
        if self._top_p is not None:
            cfg_kwargs["top_p"] = self._top_p
        if self._frequency_penalty is not None:
            cfg_kwargs["frequency_penalty"] = self._frequency_penalty
        if self._presence_penalty is not None:
            cfg_kwargs["presence_penalty"] = self._presence_penalty
        return types.GenerateContentConfig(**cfg_kwargs)

    @staticmethod
    def _part_file_uri(part: types.Part) -> Optional[str]:
        file_data = getattr(part, "file_data", None)
        if not file_data:
            return None
        return getattr(file_data, "file_uri", getattr(file_data, "uri", None))

    def _history_has_file_data(self, history: List[types.Content]) -> bool:
        for content in history:
            for part in content.parts or []:
                if self._part_file_uri(part):
                    return True
        return False

    async def _sanitize_history(self, history: List[types.Content]) -> bool:
        """Remove expired file references from history."""
        changed = False

        # Gather all unique file URIs to check
        uris_to_check = set()
        for content in history:
            for part in content.parts or []:
                uri = self._part_file_uri(part)
                if uri:
                    uris_to_check.add(uri)

        if not uris_to_check:
            return False

        # Check validity of each file concurrently, with a limit
        invalid_uris = set()
        sem = asyncio.Semaphore(10)  # Limit concurrent checks to 10

        async def _check_uri(uri: str) -> None:
            async with sem:
                name = uri
                try:
                    if "/files/" in uri:
                        name = "files/" + uri.split("/files/")[-1]
                    else:
                        return
                    await self._client.aio.files.get(name=name)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("File check failed for %s: %s", name, exc)

                    code = getattr(exc, "code", None)
                    if code is None:
                        code = getattr(exc, "status_code", None)

                    err_str = str(exc)
                    if code in {400, 403, 404}:
                        invalid_uris.add(uri)
                    elif (
                        "403" in err_str
                        or "404" in err_str
                        or "PERMISSION_DENIED" in err_str
                        or "NOT_FOUND" in err_str
                    ):
                        invalid_uris.add(uri)

        await asyncio.gather(*(_check_uri(uri) for uri in uris_to_check))

        if not invalid_uris:
            return False

        # Replace invalid files
        for content in history:
            new_parts: List[types.Part] = []
            content_changed = False
            for part in content.parts or []:
                uri = self._part_file_uri(part)
                if uri and uri in invalid_uris:
                    new_parts.append(types.Part.from_text(text="[Expired Attachment]"))
                    content_changed = True
                    changed = True
                else:
                    new_parts.append(part)
            if content_changed:
                content.parts = new_parts

        return changed

    async def generate_reply(
        self,
        history: List[types.Content],
        tool_callback: ToolCallback,
        *,
        system_instruction: Optional[str] = None,
    ) -> Optional[str]:
        active_instruction = system_instruction or self._base_instruction
        tool_rounds = 0
        total_tool_calls = 0
        accumulated_text_parts: list[str] = []

        async def _generate_once() -> Optional[types.GenerateContentResponse]:
            attempts = 3
            delay = 2.0
            config = self._build_config(active_instruction)

            while attempts:
                started = time.monotonic()
                response = None
                try:
                    response = await self._client.aio.models.generate_content(
                        model=self._model_name,
                        contents=history,
                        config=config,
                    )
                except Exception as exc:
                    err_str = str(exc)
                    code = getattr(exc, "code", getattr(exc, "status_code", None))

                    # Only treat this as an expired-file problem when the history
                    # actually carries file references. Otherwise a generic 400
                    # (e.g. a malformed request) would needlessly trigger a file
                    # sweep before being re-raised.
                    looks_like_file_error = (
                        code in {400, 403, 404}
                        or "PERMISSION_DENIED" in err_str
                        or "NOT_FOUND" in err_str
                    )
                    if looks_like_file_error and self._history_has_file_data(history):
                        logger.warning(
                            "Caught file permission error generating reply: %s", err_str
                        )
                        if await self._sanitize_history(history):
                            attempts -= 1
                            if not attempts:
                                raise
                            continue

                    if (
                        isinstance(exc, errors.ServerError)
                        or "503" in err_str
                        or "overloaded" in err_str.lower()
                    ):
                        attempts -= 1
                        if not attempts:
                            raise
                        await asyncio.sleep(delay)
                        delay = min(delay * 1.5, 10.0)
                        continue

                    raise

                api_logger.record_generate(
                    self._model_name,
                    time.monotonic() - started,
                    getattr(response, "usage_metadata", None),
                )

                if response.candidates and response.candidates[0].content:
                    return response
                attempts -= 1
                await asyncio.sleep(delay)
                delay = min(delay * 1.5, 10.0)

            return None

        while True:
            response = await _generate_once()
            if not response or not response.candidates:
                return None

            candidate = response.candidates[0]
            content = candidate.content
            text_parts: list[str] = []
            function_calls: list[types.FunctionCall] = []

            if content:
                history.append(content)

            for part in (content.parts if content and content.parts else []):
                if part.function_call:
                    function_calls.append(part.function_call)
                elif part.text and part.text.strip():
                    text_parts.append(part.text.strip())

            if text_parts:
                accumulated_text_parts.extend(text_parts)

            if not function_calls:
                final_text = "\n".join(accumulated_text_parts).strip()
                return final_text or None

            tool_rounds += 1
            # Every function_call in the appended model turn must receive a
            # matching function_response, otherwise the next generate_content
            # call fails with a 400 (mismatched calls/responses). So we answer
            # all of them and use the limit only to decide whether to loop again.
            limit_reached = False
            for tool_call in function_calls:
                feedback = await tool_callback(tool_call)
                # Function responses are documented to use the "user" role
                # ('user' or 'model' are the only supported producers).
                history.append(types.Content(role="user", parts=[feedback]))
                if tool_call.name != "think":
                    total_tool_calls += 1
                    if total_tool_calls >= _MAX_TOOL_CALLS_PER_TURN:
                        limit_reached = True

            if limit_reached or tool_rounds >= _MAX_TOOL_ROUNDS:
                final_text = "\n".join(accumulated_text_parts).strip()
                return final_text or None
