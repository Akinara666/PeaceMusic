from __future__ import annotations

import unittest
from types import SimpleNamespace

from tests.stub_modules import install_stubs, import_project_package

install_stubs()
embeddings_module = import_project_package("cogs.ai.embeddings")

GeminiEmbeddingService = embeddings_module.GeminiEmbeddingService


class FakeAsyncModels:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def embed_content(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class GeminiEmbeddingServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_embed_document_normalizes_and_sets_task_type(self) -> None:
        models = FakeAsyncModels(
            SimpleNamespace(embedding=SimpleNamespace(values=[3.0, 4.0]))
        )
        client = SimpleNamespace(aio=SimpleNamespace(models=models))
        service = GeminiEmbeddingService(
            client,
            "embed-model",
            output_dimensionality=128,
        )

        vector = await service.embed_document("  hello  ")

        self.assertAlmostEqual(vector.data[0], 0.6, places=4)
        self.assertAlmostEqual(vector.data[1], 0.8, places=4)
        self.assertEqual(models.calls[0]["model"], "embed-model")
        self.assertEqual(models.calls[0]["contents"], "hello")
        self.assertEqual(models.calls[0]["config"].task_type, "RETRIEVAL_DOCUMENT")
        self.assertEqual(models.calls[0]["config"].output_dimensionality, 128)

    async def test_embed_query_supports_embeddings_list_response(self) -> None:
        models = FakeAsyncModels(
            SimpleNamespace(embeddings=[SimpleNamespace(values=[1.0, 0.0])])
        )
        client = SimpleNamespace(aio=SimpleNamespace(models=models))
        service = GeminiEmbeddingService(client, "embed-model")

        vector = await service.embed_query("question")

        self.assertEqual(vector.data, [1.0, 0.0])
        self.assertEqual(models.calls[0]["config"].task_type, "RETRIEVAL_QUERY")

    async def test_embed_rejects_empty_text(self) -> None:
        client = SimpleNamespace(aio=SimpleNamespace(models=FakeAsyncModels(None)))
        service = GeminiEmbeddingService(client, "embed-model")

        with self.assertRaises(ValueError):
            await service.embed_document("   ")

    async def test_embed_rejects_zero_norm_vector(self) -> None:
        models = FakeAsyncModels(
            SimpleNamespace(embedding=SimpleNamespace(values=[0.0, 0.0]))
        )
        client = SimpleNamespace(aio=SimpleNamespace(models=models))
        service = GeminiEmbeddingService(client, "embed-model")

        with self.assertRaises(RuntimeError):
            await service.embed_document("hello")

    def test_extract_values_requires_expected_shape(self) -> None:
        client = SimpleNamespace(aio=SimpleNamespace(models=FakeAsyncModels(None)))
        service = GeminiEmbeddingService(client, "embed-model")

        with self.assertRaises(RuntimeError):
            service._extract_values(SimpleNamespace())
