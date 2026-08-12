"""Deterministic outer routing helpers around the agent subgraph."""

from __future__ import annotations

from enum import StrEnum
from collections.abc import Sequence

from langgraph.graph import END, START, StateGraph

from peacemusic.modules.agent.context import AgentRequestContext
from peacemusic.modules.agent.state import AttachmentRef
from peacemusic.modules.agent.state import PeaceMusicState


class InputRoute(StrEnum):
    DIRECT_AUDIO = "direct_audio"
    AI_AGENT = "ai_agent"


def normalize_input(text: str) -> str:
    """Normalize user text without interpreting it as system instructions."""

    return " ".join(text.split())


def route_input(attachments: list[AttachmentRef]) -> InputRoute:
    """Route standalone audio attachments directly to music handling."""

    if any(
        attachment.content_type and attachment.content_type.lower().startswith("audio/")
        for attachment in attachments
    ):
        return InputRoute.DIRECT_AUDIO
    return InputRoute.AI_AGENT


class OuterAgentWorkflow:
    """Checkpoint-safe outer workflow around the provider agent subgraph.

    The workflow deliberately passes only validated state and plain values to
    the model boundary. Runtime handles such as agents, Discord objects, and
    repositories never enter ``PeaceMusicState``.
    """

    def __init__(self) -> None:
        graph = StateGraph(PeaceMusicState)
        graph.add_node("normalize_input", self._normalize_node)
        graph.add_node("load_context", self._identity_node)
        graph.add_node("policy_check", self._identity_node)
        graph.add_node("route", self._identity_node)
        graph.add_node("direct_audio", self._identity_node)
        graph.add_node("ai_agent", self._identity_node)
        graph.add_node("finalize", self._identity_node)
        graph.add_edge(START, "normalize_input")
        graph.add_edge("normalize_input", "load_context")
        graph.add_edge("load_context", "policy_check")
        graph.add_edge("policy_check", "route")
        graph.add_conditional_edges(
            "route",
            lambda state: state.input_route,
            {
                InputRoute.DIRECT_AUDIO.value: "direct_audio",
                InputRoute.AI_AGENT.value: "ai_agent",
            },
        )
        graph.add_edge("direct_audio", "finalize")
        graph.add_edge("ai_agent", "finalize")
        graph.add_edge("finalize", END)
        self._graph = graph.compile()

    @staticmethod
    def _normalize_node(state: PeaceMusicState) -> dict[str, str]:
        return {"normalized_input": normalize_input(state.input_text)}

    @staticmethod
    def _identity_node(_state: PeaceMusicState) -> dict[str, object]:
        return {}

    def run(self, state: PeaceMusicState) -> PeaceMusicState:
        """Run deterministic lifecycle nodes through the compiled outer graph."""

        result = self._graph.invoke(state.model_dump(mode="json"))
        return PeaceMusicState.model_validate(result)

    def initialize(
        self,
        context: AgentRequestContext,
        text: str,
        *,
        attachments: Sequence[AttachmentRef] = (),
    ) -> PeaceMusicState:
        route = route_input(list(attachments))
        state = PeaceMusicState(
            request_id=context.request_id,
            guild_id=context.guild_id,
            channel_id=context.channel_id,
            user_id=context.user_id,
            input_text=text,
            normalized_input="",
            input_route=route.value,
            attachments=list(attachments),
        )
        return self.run(state)

    def apply_policy(
        self, state: PeaceMusicState, *, ai_enabled: bool
    ) -> PeaceMusicState:
        if not ai_enabled and state.input_route != InputRoute.DIRECT_AUDIO:
            return state.model_copy(
                update={"final_response": "AI assistant is disabled for this server."}
            )
        if not state.normalized_input and state.input_route == InputRoute.AI_AGENT:
            return state.model_copy(
                update={"final_response": "Please provide a message to process."}
            )
        return state

    @staticmethod
    def finalize(state: PeaceMusicState, response: str) -> PeaceMusicState:
        return state.model_copy(update={"final_response": response})
