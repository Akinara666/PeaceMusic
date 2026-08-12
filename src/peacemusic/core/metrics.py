"""Small in-process metrics registry rendered as Prometheus text."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping

_NAME_PATTERN = re.compile(r"^[a-zA-Z_:][a-zA-Z0-9_:]*$")
_LABEL_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


class MetricsRegistry:
    """Collect counters and gauges without requiring an external metrics SDK."""

    def __init__(self) -> None:
        self._counters: defaultdict[tuple[str, tuple[tuple[str, str], ...]], int] = (
            defaultdict(int)
        )
        self._gauges: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}

    def increment(
        self,
        name: str,
        amount: int = 1,
        *,
        labels: Mapping[str, object] | None = None,
    ) -> None:
        """Increment a counter, optionally scoped to a stable label set."""

        key = self._key(name, labels)
        self._counters[key] += amount

    def set_gauge(
        self,
        name: str,
        value: float,
        *,
        labels: Mapping[str, object] | None = None,
    ) -> None:
        """Set a gauge value, optionally scoped to a stable label set."""

        self._gauges[self._key(name, labels)] = value

    def render(self) -> str:
        """Render all values using the Prometheus text exposition format."""

        lines: list[str] = []
        for name, values in self._group(self._counters).items():
            lines.append(f"# TYPE {name} counter")
            lines.extend(self._render_values(name, values))
        for name, values in self._group(self._gauges).items():
            lines.append(f"# TYPE {name} gauge")
            lines.extend(self._render_values(name, values))
        return "\n".join(lines) + ("\n" if lines else "")

    @staticmethod
    def _key(
        name: str, labels: Mapping[str, object] | None
    ) -> tuple[str, tuple[tuple[str, str], ...]]:
        if not _NAME_PATTERN.fullmatch(name):
            raise ValueError(f"Invalid metric name: {name}")
        normalized = tuple(
            sorted((key, str(value)) for key, value in (labels or {}).items())
        )
        for key, _value in normalized:
            if not _LABEL_PATTERN.fullmatch(key):
                raise ValueError(f"Invalid metric label: {key}")
        return name, normalized

    @staticmethod
    def _group(
        values: Mapping[tuple[str, tuple[tuple[str, str], ...]], int | float],
    ) -> dict[str, list[tuple[tuple[tuple[str, str], ...], int | float]]]:
        grouped: dict[str, list[tuple[tuple[tuple[str, str], ...], int | float]]] = (
            defaultdict(list)
        )
        for (name, labels), value in values.items():
            grouped[name].append((labels, value))
        return grouped

    @staticmethod
    def _render_values(
        name: str,
        values: list[tuple[tuple[tuple[str, str], ...], int | float]],
    ) -> list[str]:
        rendered: list[str] = []
        for labels, value in values:
            suffix = ""
            if labels:
                encoded = ",".join(
                    f'{key}="{MetricsRegistry._escape(value)}"' for key, value in labels
                )
                suffix = "{" + encoded + "}"
            rendered.append(f"{name}{suffix} {value}")
        return rendered

    @staticmethod
    def _escape(value: str) -> str:
        return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')
