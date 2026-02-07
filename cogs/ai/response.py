from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, List, Optional, TYPE_CHECKING

from google.genai import errors, types

if TYPE_CHECKING:  # pragma: no cover - type hints only
    from google import genai

ToolCallback = Callable[[types.FunctionCall], Awaitable[types.Part]]


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

    def build_generation_config(self) -> types.GenerateContentConfig:
        cfg_kwargs = {
            "tools": self._tools,
            "thinking_config": types.ThinkingConfig(
                thinking_budget=self._thinking_budget
            ),
            "system_instruction": self._base_instruction,
            "temperature": self._temperature,
        }
        if self._top_p is not None:
            cfg_kwargs["top_p"] = self._top_p
        if self._frequency_penalty is not None:
            cfg_kwargs["frequency_penalty"] = self._frequency_penalty
        if self._presence_penalty is not None:
            cfg_kwargs["presence_penalty"] = self._presence_penalty
        return types.GenerateContentConfig(**cfg_kwargs)

    async def _sanitize_history(self, history: List[types.Content]) -> bool:
        """Remove expired file references from history."""
        changed = False

        # Gather all unique file URIs to check
        uris_to_check = set()
        for content in history:
            for part in content.parts:
                file_data = getattr(part, "file_data", None)
                uri = getattr(file_data, "uri", None)
                if uri:
                    uris_to_check.add(uri)

        if not uris_to_check:
            return False

        # Check validity of each file concurrently, with a limit
        invalid_uris = set()
        sem = asyncio.Semaphore(10)  # Limit concurrent checks to 10

        async def _check_uri(uri: str) -> None:
            async with sem:
                try:
                    if "/files/" in uri:
                        name = "files/" + uri.split("/files/")[-1]
                    else:
                        return
                    await self._client.aio.files.get(name=name)
                except errors.ClientError as exc:
                    if exc.code in {403, 404}:
                        invalid_uris.add(uri)
                except Exception:  # noqa: BLE001
                    # Do not remove on unknown errors (like network issues/429)
                    pass

        await asyncio.gather(*(_check_uri(uri) for uri in uris_to_check))

        if not invalid_uris:
            return False

        # Replace invalid files
        for content in history:
            new_parts: List[types.Part] = []
            content_changed = False
            for part in content.parts:
                file_data = getattr(part, "file_data", None)
                uri = getattr(file_data, "uri", None)
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
    ) -> Optional[str]:
        config = self.build_generation_config()
        attempts = 3
        response: Optional[types.GenerateContentResponse] = None

        delay = 2.0
        while attempts:
            try:
                response = await self._client.aio.models.generate_content(
                    model=self._model_name,
                    contents=history,
                    config=config,
                )
            except errors.ClientError:
                # If we get a client error (like 400/404 on a file URI), try sanitize history
                if await self._sanitize_history(history):
                    attempts -= 1
                    if not attempts:
                        raise
                    continue
                raise
            except errors.ServerError as exc:
                if (
                    getattr(exc, "status_code", None) == 503
                    or "overloaded" in str(exc).lower()
                ):
                    attempts -= 1
                    if not attempts:
                        raise
                    await asyncio.sleep(delay)
                    delay = min(delay * 1.5, 10.0)
                    continue
                raise

            if response.candidates and response.candidates[0].content:
                break
            attempts -= 1
            await asyncio.sleep(delay)
            delay = min(delay * 1.5, 10.0)

        if not response or not response.candidates:
            return None



        candidate = response.candidates[0]
        content = candidate.content
        final_text = ""

        if content:
            history.append(content)

        tool_calls_count = 0
        for part in content.parts if content else []:
            if part.function_call:
                if tool_calls_count >= 2:
                    continue
                tool_calls_count += 1
                feedback = await tool_callback(part.function_call)
                history.append(types.Content(role="user", parts=[feedback]))
            elif part.text:
                final_text = part.text

        return final_text.strip() or None
