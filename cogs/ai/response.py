from __future__ import annotations

import asyncio
import random
from typing import Awaitable, Callable, List, Optional, Sequence, TYPE_CHECKING

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
        max_temperature: Optional[float] = None,
        style_instructions: Optional[Sequence[str]] = None,
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
        self._max_temperature = max_temperature if max_temperature is not None else min(
            temperature + 0.4,
            1.4,
        )
        self._style_variants = list(style_instructions or [])
        self._last_style_index: Optional[int] = None
        self._thinking_budget = thinking_budget

    def build_generation_config(self, history_length: int) -> types.GenerateContentConfig:
        cfg_kwargs = {
            "tools": self._tools,
            "thinking_config": types.ThinkingConfig(thinking_budget=self._thinking_budget),
            "system_instruction": self._compose_system_instruction(),
            "temperature": self._compute_temperature(history_length),
        }
        if self._top_p is not None:
            cfg_kwargs["top_p"] = self._top_p
        if self._frequency_penalty is not None:
            cfg_kwargs["frequency_penalty"] = self._frequency_penalty
        if self._presence_penalty is not None:
            cfg_kwargs["presence_penalty"] = self._presence_penalty
        return types.GenerateContentConfig(**cfg_kwargs)

    def _compose_system_instruction(self) -> str:
        if not self._style_variants:
            return self._base_instruction
        if len(self._style_variants) == 1:
            return f"{self._base_instruction}\n\n{self._style_variants[0]}"

        available_indexes = [
            idx for idx in range(len(self._style_variants)) if idx != self._last_style_index
        ]
        chosen_index = random.choice(available_indexes) if available_indexes else 0
        self._last_style_index = chosen_index
        modifier = self._style_variants[chosen_index].strip()
        if not modifier:
            return self._base_instruction
        return f"{self._base_instruction}\n\n{modifier}"

    def _compute_temperature(self, history_length: int) -> float:
        if history_length <= 15:
            return self._temperature

        ramp = max(self._max_temperature - self._temperature, 0.0)
        if ramp == 0.0:
            return self._temperature

        factor = min(1.0, (history_length - 15) / 40)
        return self._temperature + ramp * factor

    async def generate_reply(
        self,
        history: List[types.Content],
        user_text: str,
        tool_callback: ToolCallback,
    ) -> Optional[str]:
        config = self.build_generation_config(len(history))
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
                if getattr(exc, "status_code", None) == 503 or "overloaded" in str(exc).lower():
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
