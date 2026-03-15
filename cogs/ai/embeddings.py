from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np
from google.genai import types

if TYPE_CHECKING:  # pragma: no cover - type hints only
    from google import genai

class GeminiEmbeddingService:
    """Create normalized Gemini embeddings for semantic memory retrieval."""

    def __init__(
        self,
        client: "genai.Client",
        model_name: str,
        *,
        output_dimensionality: int = 768,
    ) -> None:
        self._client = client
        self._model_name = model_name
        self._output_dimensionality = output_dimensionality

    @property
    def model_name(self) -> str:
        return self._model_name

    async def embed_document(self, text: str) -> np.ndarray:
        return await self._embed(text, task_type="RETRIEVAL_DOCUMENT")

    async def embed_query(self, text: str) -> np.ndarray:
        return await self._embed(text, task_type="RETRIEVAL_QUERY")

    async def _embed(self, text: str, *, task_type: str) -> np.ndarray:
        clean_text = text.strip()
        if not clean_text:
            raise ValueError("Cannot embed empty text")

        response = await self._client.aio.models.embed_content(
            model=self._model_name,
            contents=clean_text,
            config=types.EmbedContentConfig(
                task_type=task_type,
                output_dimensionality=self._output_dimensionality,
            ),
        )

        values = self._extract_values(response)
        vector = np.ascontiguousarray(np.asarray(values, dtype=np.float32))
        if vector.size == 0:
            raise RuntimeError("Gemini embedding response was empty")

        norm = float(np.linalg.norm(vector))
        if norm == 0.0:
            raise RuntimeError("Gemini embedding response had zero magnitude")
        return np.ascontiguousarray(vector / norm, dtype=np.float32)

    def _extract_values(self, response: Any) -> list[float]:
        single_embedding = getattr(response, "embedding", None)
        if single_embedding is not None:
            values = getattr(single_embedding, "values", None)
            if values:
                return list(values)

        embeddings = getattr(response, "embeddings", None) or []
        if embeddings:
            values = getattr(embeddings[0], "values", None)
            if values:
                return list(values)

        raise RuntimeError("Unexpected embed_content response shape")
