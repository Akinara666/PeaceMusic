from __future__ import annotations

import asyncio
from types import SimpleNamespace

from peacemusic.infrastructure.llm.embeddings import GeminiEmbeddingFunction


def test_gemini_embedding_function_handles_empty_and_provider_vectors(
    monkeypatch,
) -> None:
    from google import genai

    response = SimpleNamespace(
        embeddings=[SimpleNamespace(values=[0.1, 0.2]), SimpleNamespace(values=[0.3])]
    )
    models = SimpleNamespace(embed_content=lambda **_kwargs: response)
    monkeypatch.setattr(
        genai,
        "Client",
        lambda **_kwargs: SimpleNamespace(models=models),
    )

    async def immediate_to_thread(function, *args):
        return function(*args)

    monkeypatch.setattr(
        "peacemusic.infrastructure.llm.embeddings.asyncio.to_thread",
        immediate_to_thread,
    )

    async def scenario() -> None:
        embed = GeminiEmbeddingFunction(api_key="secret", dimensions=2)
        assert await embed(()) == []
        assert await embed(("one", "two")) == [[0.1, 0.2], [0.3]]

    asyncio.run(scenario())
