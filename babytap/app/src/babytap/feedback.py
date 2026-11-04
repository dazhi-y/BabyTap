from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from threading import RLock
from typing import Callable, Dict, List, Optional

from .easyinput_protocol import SpeakerCue


class FeedbackState(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    WAITING_USER = "waiting_user"
    COMPLETED = "completed"
    FAILED = "failed"


FAILED_FEEDBACK_TTL_MS = 8000


@dataclass(frozen=True)
class FeedbackEvent:
    state: FeedbackState
    ttl_ms: int
    message: Optional[str] = None
    cue: SpeakerCue = SpeakerCue.NONE


FeedbackSink = Callable[[FeedbackEvent], None]


class FeedbackRouter:
    """Fans one business feedback event out to UI, speech and hardware sinks."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._sinks: List[FeedbackSink] = []
        self._last_event: Optional[FeedbackEvent] = None

    def add_sink(self, sink: FeedbackSink) -> None:
        with self._lock:
            self._sinks.append(sink)

    def publish(self, event: FeedbackEvent) -> None:
        with self._lock:
            self._last_event = event
            sinks = list(self._sinks)
        for sink in sinks:
            try:
                sink(event)
            except Exception:
                # A feedback channel must never invalidate the business action.
                continue

    def snapshot(self) -> Optional[Dict[str, object]]:
        with self._lock:
            return asdict(self._last_event) if self._last_event else None

    def reset(self) -> None:
        with self._lock:
            self._last_event = None
