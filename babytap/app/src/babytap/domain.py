from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Dict, List, Optional, Tuple
from uuid import UUID, uuid4


class Side(str, Enum):
    LEFT = "left"
    RIGHT = "right"


class BreastfeedingAction(str, Enum):
    STARTED = "started"
    SWITCHED = "switched"
    COMPLETED = "completed"


class InvalidTransition(ValueError):
    """Raised when an input would create an impossible timeline."""


def require_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class BreastfeedingSegment:
    side: Side
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        start = require_aware_utc(self.start)
        end = require_aware_utc(self.end)
        if end <= start:
            raise InvalidTransition("a breastfeeding segment must have positive duration")
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)

    @property
    def duration(self) -> timedelta:
        return self.end - self.start


@dataclass(frozen=True)
class CompletedBreastfeeding:
    session_id: UUID
    started_at: datetime
    ended_at: datetime
    segments: Tuple[BreastfeedingSegment, ...]

    @property
    def total_duration(self) -> timedelta:
        return sum((segment.duration for segment in self.segments), timedelta())

    def duration_for(self, side: Side) -> timedelta:
        return sum(
            (segment.duration for segment in self.segments if segment.side is side),
            timedelta(),
        )

    @property
    def last_side(self) -> Side:
        return self.segments[-1].side


@dataclass(frozen=True)
class BreastfeedingResult:
    action: BreastfeedingAction
    session_id: UUID
    active_side: Optional[Side]
    closed_segment: Optional[BreastfeedingSegment] = None
    completed: Optional[CompletedBreastfeeding] = None


@dataclass
class _ActiveBreastfeeding:
    session_id: UUID
    started_at: datetime
    active_side: Side
    active_since: datetime
    segments: List[BreastfeedingSegment] = field(default_factory=list)


class BreastfeedingStateMachine:
    """Deterministic two-key state machine with no assumed side order."""

    def __init__(self) -> None:
        self._active: Optional[_ActiveBreastfeeding] = None

    @property
    def active_side(self) -> Optional[Side]:
        return self._active.active_side if self._active else None

    @property
    def active_session_id(self) -> Optional[UUID]:
        return self._active.session_id if self._active else None

    def press(self, side: Side, at: datetime) -> BreastfeedingResult:
        at = require_aware_utc(at)

        if self._active is None:
            session_id = uuid4()
            self._active = _ActiveBreastfeeding(
                session_id=session_id,
                started_at=at,
                active_side=side,
                active_since=at,
            )
            return BreastfeedingResult(
                action=BreastfeedingAction.STARTED,
                session_id=session_id,
                active_side=side,
            )

        active = self._active
        if at <= active.active_since:
            raise InvalidTransition("button time must be later than the active segment start")

        closed = BreastfeedingSegment(
            side=active.active_side,
            start=active.active_since,
            end=at,
        )
        active.segments.append(closed)

        if side is not active.active_side:
            active.active_side = side
            active.active_since = at
            return BreastfeedingResult(
                action=BreastfeedingAction.SWITCHED,
                session_id=active.session_id,
                active_side=side,
                closed_segment=closed,
            )

        completed = CompletedBreastfeeding(
            session_id=active.session_id,
            started_at=active.started_at,
            ended_at=at,
            segments=tuple(active.segments),
        )
        self._active = None
        return BreastfeedingResult(
            action=BreastfeedingAction.COMPLETED,
            session_id=completed.session_id,
            active_side=None,
            closed_segment=closed,
            completed=completed,
        )

    def snapshot(self, at: Optional[datetime] = None) -> Dict[str, object]:
        if self._active is None:
            return {"active": False, "side": None, "session_id": None}

        now = require_aware_utc(at or datetime.now(timezone.utc))
        elapsed = now - self._active.started_at
        return {
            "active": True,
            "side": self._active.active_side.value,
            "session_id": str(self._active.session_id),
            "started_at": self._active.started_at.isoformat(),
            "elapsed_seconds": max(0, int(elapsed.total_seconds())),
            "closed_segments": len(self._active.segments),
        }

    def dump_state(self) -> Optional[Dict[str, object]]:
        """Return the minimum durable state needed to resume after a restart."""

        if self._active is None:
            return None
        return {
            "session_id": str(self._active.session_id),
            "started_at": self._active.started_at.isoformat(),
            "active_side": self._active.active_side.value,
            "active_since": self._active.active_since.isoformat(),
            "segments": [
                {
                    "side": segment.side.value,
                    "start": segment.start.isoformat(),
                    "end": segment.end.isoformat(),
                }
                for segment in self._active.segments
            ],
        }

    def restore_state(self, state: Optional[Dict[str, object]]) -> None:
        if state is None:
            self._active = None
            return
        segments = [
            BreastfeedingSegment(
                side=Side(str(item["side"])),
                start=datetime.fromisoformat(str(item["start"])),
                end=datetime.fromisoformat(str(item["end"])),
            )
            for item in state.get("segments", [])
        ]
        self._active = _ActiveBreastfeeding(
            session_id=UUID(str(state["session_id"])),
            started_at=require_aware_utc(datetime.fromisoformat(str(state["started_at"]))),
            active_side=Side(str(state["active_side"])),
            active_since=require_aware_utc(datetime.fromisoformat(str(state["active_since"]))),
            segments=segments,
        )

    def cancel(self) -> Optional[UUID]:
        if self._active is None:
            return None
        session_id = self._active.session_id
        self._active = None
        return session_id
