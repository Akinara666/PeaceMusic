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

    async def generate_reply(
        self,
        history: List[types.Content],
        user_text: str,
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

        history[-1].parts = [types.Part.from_text(text=user_text)]

        candidate = response.candidates[0]
        content = candidate.content
        final_text = ""

        if content:
            history.append(content)

        for part in content.parts if content else []:
            if part.function_call:
                feedback = await tool_callback(part.function_call)
                history.append(types.Content(role="user", parts=[feedback]))
            elif part.text:
                final_text = part.text

        return final_text.strip() or None
