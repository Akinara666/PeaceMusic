"""Thread-safe bounded PCM buffer for Discord's synchronous audio callback."""

from __future__ import annotations

import queue
from dataclasses import dataclass

from peacemusic.core.metrics import MetricsRegistry


@dataclass(frozen=True, slots=True)
class BufferStats:
    capacity: int
    buffered: int
    underruns: int
    closed: bool


class BufferedAudioSource:
    """A bounded byte-frame buffer with explicit producer completion."""

    def __init__(
        self,
        *,
        capacity_frames: int,
        frame_size: int = 3840,
        metrics: MetricsRegistry | None = None,
    ) -> None:
        if capacity_frames < 1 or frame_size < 1:
            raise ValueError("Buffer capacity and frame size must be positive")
        self._capacity = capacity_frames
        self._frame_size = frame_size
        self._frames: queue.Queue[bytes | None] = queue.Queue(maxsize=capacity_frames)
        self._underruns = 0
        self._closed = False
        self._metrics = metrics

    def push(self, frame: bytes, *, timeout: float | None = None) -> None:
        if self._closed:
            raise RuntimeError("Audio buffer is closed")
        if len(frame) != self._frame_size:
            raise ValueError("Audio frame has an unexpected size")
        try:
            self._frames.put(frame, timeout=timeout)
        except queue.Full as exc:
            raise BufferError("Audio buffer is full") from exc

    def read(self, *, timeout: float = 0.25) -> bytes:
        if self._closed and self._frames.empty():
            return b"\x00" * self._frame_size
        try:
            frame = self._frames.get(timeout=timeout)
        except queue.Empty:
            self._underruns += 1
            if self._metrics is not None:
                self._metrics.increment("peacemusic_voice_buffer_underruns_total")
            return b"\x00" * self._frame_size
        if frame is None:
            self._closed = True
            return b"\x00" * self._frame_size
        return frame

    def close(self) -> None:
        self._closed = True
        try:
            self._frames.put_nowait(None)
        except queue.Full:
            pass

    def stats(self) -> BufferStats:
        stats = BufferStats(
            capacity=self._capacity,
            buffered=self._frames.qsize(),
            underruns=self._underruns,
            closed=self._closed,
        )
        if self._metrics is not None:
            self._metrics.set_gauge("peacemusic_voice_buffered_frames", stats.buffered)
        return stats
