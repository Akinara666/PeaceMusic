"""Gemini embedding callable for LangGraph Store semantic indexing."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence


class GeminiEmbeddingFunction:
    """Create normalized Gemini text embeddings without blocking asyncio."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "gemini-embedding-001",
        dimensions: int = 768,
    ) -> None:
        if not api_key or dimensions < 1:
            raise ValueError("A Gemini API key and positive dimensions are required")
        self._api_key = api_key
        self._model = model
        self._dimensions = dimensions

    async def __call__(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=self._api_key)

        def embed() -> list[list[float]]:
            response = client.models.embed_content(
                model=self._model,
                contents=list(texts),
                config=types.EmbedContentConfig(
                    output_dimensionality=self._dimensions,
                ),
            )
            return [list(item.values) for item in (response.embeddings or [])]

        return await asyncio.to_thread(embed)
