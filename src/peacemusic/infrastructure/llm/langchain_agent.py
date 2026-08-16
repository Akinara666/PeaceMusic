"""Lazy Gemini/LangChain agent factory."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any


class LangChainAgentFactory:
    """Create the standard model/tool loop through LangChain's public API."""

    def __init__(
        self,
        *,
        api_key: str,
        model_name: str,
        temperature: float = 1.0,
        system_prompt: str = "",
    ) -> None:
        self.api_key = api_key
        self.model_name = model_name
        self.temperature = temperature
        self.system_prompt = system_prompt
        self._checkpointer: Any | None = None
        self._store: Any | None = None

    def attach_persistence(self, *, checkpointer: Any, store: Any) -> None:
        """Attach started LangGraph persistence resources before agent creation."""

        self._checkpointer = checkpointer
        self._store = store

    def create(self, tools: Sequence[Any], *, system_prompt: str | None = None) -> Any:
        try:
            from langchain.agents import create_agent
            from langchain_google_genai import ChatGoogleGenerativeAI
        except ImportError as exc:  # pragma: no cover - optional provider boundary
            raise RuntimeError(
                "LangChain Gemini support requires langchain, langchain-core, "
                "and langchain-google-genai."
            ) from exc

        model = ChatGoogleGenerativeAI(
            model=self.model_name,
            google_api_key=self.api_key,
            temperature=self.temperature,
        )
        kwargs: dict[str, Any] = {
            "model": model,
            "tools": list(tools),
            "system_prompt": system_prompt or self.system_prompt or None,
        }
        if self._checkpointer is not None:
            kwargs["checkpointer"] = self._checkpointer
        if self._store is not None:
            kwargs["store"] = self._store
        return create_agent(**kwargs)
