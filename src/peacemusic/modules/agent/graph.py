"""Deterministic outer routing helpers around the agent subgraph."""

from __future__ import annotations

from enum import StrEnum
from collections.abc import Sequence

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

    def initialize(
        self,
        context: AgentRequestContext,
        text: str,
        *,
        attachments: Sequence[AttachmentRef] = (),
    ) -> PeaceMusicState:
        normalized = normalize_input(text)
        route = route_input(list(attachments))
        return PeaceMusicState(
            request_id=context.request_id,
            guild_id=context.guild_id,
            channel_id=context.channel_id,
            user_id=context.user_id,
            input_text=text,
            normalized_input=normalized,
            input_route=route.value,
            attachments=list(attachments),
        )

    def apply_policy(
        self, state: PeaceMusicState, *, ai_enabled: bool
    ) -> PeaceMusicState:
        if not ai_enabled:
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
