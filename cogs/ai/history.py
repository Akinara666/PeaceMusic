from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from google.genai import types

logger = logging.getLogger(__name__)


class HistoryManager:
    """Persist and manage per-channel Gemini chat histories."""

    def __init__(self, context_file: Path, history_limit: int) -> None:
        self._context_file = context_file
        self._history_limit = history_limit
        self._histories: Dict[int, List[types.Content]] = {}

    def get_history(self, channel_id: int) -> List[types.Content]:
        """Return an in-memory conversation history for the channel."""
        return self._histories.setdefault(channel_id, [])

    def trim(self, history: List[types.Content]) -> None:
        """Trim history in-place to stay within limits and remove dangling turns."""
        if not history:
            return

        original_len = len(history)

        if len(history) > self._history_limit:
            del history[: -self._history_limit]

        def _has_part(content: types.Content, attr: str) -> bool:
            return any(getattr(part, attr, None) for part in content.parts)

        while history and _has_part(history[-1], "function_call"):
            history.pop()

        while history and (
            _has_part(history[0], "function_call")
            or _has_part(history[0], "function_response")
        ):
            history.pop(0)

        if len(history) != original_len:
            logger.info(
                "Trimmed chat history from %s to %s entries", original_len, len(history)
            )

    def snapshot(self) -> Dict[str, List[Dict[str, Any]]]:
        snapshot: Dict[str, List[Dict[str, Any]]] = {}
        for channel_id, history in self._histories.items():
            serialized = [
                self._serialize_content(content) for content in history if content.parts
            ]
            if serialized:
                snapshot[str(channel_id)] = serialized
        return snapshot

    def load(self) -> None:
        """Load histories from disk, ignoring malformed entries."""
        if not self._context_file.exists():
            return
        try:
            raw_data = json.loads(self._context_file.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - log and continue with fresh histories
            logger.exception("Failed to load chat history from %s", self._context_file)
            return
        if not isinstance(raw_data, dict):
            logger.warning("Context file has unexpected structure; skipping load")
            return

        for channel_id_str, contents in raw_data.items():
            try:
                channel_id = int(channel_id_str)
            except (TypeError, ValueError):
                logger.warning(
                    "Skipping invalid channel id in context file: %s", channel_id_str
                )
                continue
            if not isinstance(contents, list):
                logger.warning(
                    "Skipping context entry for channel %s: expected list",
                    channel_id_str,
                )
                continue
            history: List[types.Content] = []
            for content_payload in contents:
                if not isinstance(content_payload, dict):
                    continue
                content = self._deserialize_content(content_payload)
                if content:
                    history.append(content)
            if not history:
                continue
            self.trim(history)
            self._histories[channel_id] = history

    async def persist(self) -> None:
        """Persist histories to disk in a background thread."""
        snapshot = self.snapshot()

        def _write() -> None:
            if not snapshot:
                if self._context_file.exists():
                    try:
                        self._context_file.unlink()
                    except FileNotFoundError:
                        pass
                return
            tmp_path = self._context_file.with_name(self._context_file.name + ".tmp")
            tmp_path.write_text(
                json.dumps(snapshot, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp_path.replace(self._context_file)

        try:
            await asyncio.to_thread(_write)
        except Exception:  # noqa: BLE001 - keep bot running even if persistence fails
            logger.exception(
                "Failed to persist chat histories to %s", self._context_file
            )

    def _serialize_content(self, content: types.Content) -> Dict[str, Any]:
        parts: List[Dict[str, Any]] = []
        for part in content.parts:
            text_value = getattr(part, "text", None)
            if text_value:
                parts.append({"type": "text", "text": text_value})
                continue
            function_call = getattr(part, "function_call", None)
            if function_call:
                args = getattr(function_call, "args", None) or {}
                if not isinstance(args, dict):
                    try:
                        args = dict(args)
                    except Exception:  # noqa: BLE001 - best-effort serialization
                        pass
                parts.append(
                    {
                        "type": "function_call",
                        "name": getattr(function_call, "name", ""),
                        "args": self._ensure_json_safe(args),
                    }
                )
                continue
            function_response = getattr(part, "function_response", None)
            if function_response:
                parts.append(
                    {
                        "type": "function_response",
                        "name": getattr(function_response, "name", ""),
                        "response": self._ensure_json_safe(
                            getattr(function_response, "response", {})
                        ),
                    }
                )
                continue
            file_data = getattr(part, "file_data", None)
            if file_data and getattr(file_data, "uri", None):
                parts.append(
                    {
                        "type": "file_data",
                        "uri": getattr(file_data, "uri", ""),
                        "mime_type": getattr(file_data, "mime_type", None),
                    }
                )
        return {"role": content.role, "parts": parts}

    def _deserialize_content(self, payload: Dict[str, Any]) -> Optional[types.Content]:
        role = payload.get("role")
        if not role:
            return None
        parts: List[types.Part] = []
        for part_payload in payload.get("parts", []):
            kind = part_payload.get("type")
            if kind == "text":
                text_value = part_payload.get("text", "")
                if text_value:
                    parts.append(types.Part.from_text(text=text_value))
            elif kind == "function_call":
                name = part_payload.get("name")
                args = part_payload.get("args") or {}
                if name:
                    try:
                        parts.append(
                            types.Part.from_function_call(name=name, args=args)
                        )
                    except Exception:  # noqa: BLE001 - fall back to text annotation
                        parts.append(
                            types.Part.from_text(text=f"[tool call] {name}({args})")
                        )
            elif kind == "function_response":
                name = part_payload.get("name") or ""
                response = part_payload.get("response") or {}
                try:
                    parts.append(
                        types.Part.from_function_response(name=name, response=response)
                    )
                except Exception:  # noqa: BLE001
                    parts.append(
                        types.Part.from_text(text=f"[tool response] {name}: {response}")
                    )
            elif kind == "file_data":
                uri = part_payload.get("uri")
                if uri:
                    parts.append(
                        types.Part.from_uri(
                            file_uri=uri,
                            mime_type=part_payload.get("mime_type"),
                        )
                    )
        if not parts:
            return None
        return types.Content(role=role, parts=parts)

    def _ensure_json_safe(self, payload: Any) -> Any:
        try:
            json.dumps(payload)
            return payload
        except TypeError:
            try:
                return json.loads(json.dumps(payload, default=str))
            except Exception:  # noqa: BLE001
                return str(payload)
