from __future__ import annotations

from datetime import datetime, timezone
from threading import RLock
from typing import Dict, Optional, Protocol
from uuid import uuid4

from .actions import Action, action_for_key
from .domain import (
    BreastfeedingAction,
    BreastfeedingStateMachine,
    CompletedBreastfeeding,
    Side,
    require_aware_utc,
)
from .records import InMemoryRecordStore, LocalRecord, RecordStore
from .voice import parse_voice


class RuntimeStateStore(Protocol):
    def load_runtime_state(self) -> Optional[Dict[str, object]]: ...

    def save_runtime_state(self, state: Dict[str, object]) -> None: ...


class BabyTapEngine:
    """Hardware-independent v1 interaction engine.

    This stores only prototype runtime state. The Baby Buddy adapter will replace
    completed local records with authoritative API records during integration.
    """

    def __init__(
        self,
        record_store: Optional[RecordStore] = None,
        runtime_store: Optional[RuntimeStateStore] = None,
    ) -> None:
        self._lock = RLock()
        self.breastfeeding = BreastfeedingStateMachine()
        self.sleep_started_at: Optional[datetime] = None
        self.pending_voice: Optional[str] = None
        self.record_store = record_store or InMemoryRecordStore()
        self.runtime_store = runtime_store
        self._restore_runtime_state()

    def handle_key(self, key: int, at: Optional[datetime] = None) -> Dict[str, object]:
        """Compatibility entry point; production adapters use ActionRouter."""

        return self.handle_action(action_for_key(key), at)

    def handle_action(
        self, action: Action, at: Optional[datetime] = None
    ) -> Dict[str, object]:
        with self._lock:
            result = self._handle_action(action, at)
            self._save_runtime_state()
            return result

    def cancel_pending_voice(self) -> Dict[str, object]:
        """Cancel voice entry without ever falling through to record undo."""

        with self._lock:
            if self.pending_voice is None:
                return {"action": "nothing_to_cancel"}
            context = self.pending_voice
            self.pending_voice = None
            self._save_runtime_state()
            return {"action": "cancelled", "kind": context}

    def _handle_action(
        self, action: Action, at: Optional[datetime] = None
    ) -> Dict[str, object]:
        at = require_aware_utc(at or datetime.now(timezone.utc))

        if action in (Action.BREAST_LEFT, Action.BREAST_RIGHT):
            side = Side.LEFT if action is Action.BREAST_LEFT else Side.RIGHT
            result = self.breastfeeding.press(side, at)
            response: Dict[str, object] = {
                "action": result.action.value,
                "session_id": str(result.session_id),
                "active_side": result.active_side.value if result.active_side else None,
            }
            if result.action is BreastfeedingAction.COMPLETED:
                assert result.completed is not None
                record = self._record_breastfeeding(result.completed)
                response["record_id"] = str(record.record_id)
                response["summary"] = record.data
            return response

        if action is Action.BOTTLE_VOICE:
            self.pending_voice = "bottle"
            return {"action": "voice_requested", "context": "bottle"}

        if action is Action.SOLID_FOOD_VOICE:
            self.pending_voice = "solid_food"
            return {"action": "voice_requested", "context": "solid_food"}

        if action is Action.DIAPER:
            record = LocalRecord(uuid4(), "diaper", at, at, {})
            self.record_store.add(record)
            return {"action": "recorded", "kind": "diaper", "record_id": str(record.record_id)}

        if action is Action.SLEEP_TOGGLE:
            if self.sleep_started_at is None:
                self.sleep_started_at = at
                return {"action": "started", "kind": "sleep", "started_at": at.isoformat()}
            if at <= self.sleep_started_at:
                raise ValueError("sleep end must be later than sleep start")
            record = LocalRecord(
                uuid4(),
                "sleep",
                self.sleep_started_at,
                at,
                {"duration_seconds": int((at - self.sleep_started_at).total_seconds())},
            )
            self.sleep_started_at = None
            self.record_store.add(record)
            return {
                "action": "completed",
                "kind": "sleep",
                "record_id": str(record.record_id),
                **record.data,
            }

        if action is Action.UNDO_OR_CANCEL:
            if self.pending_voice is not None:
                context = self.pending_voice
                self.pending_voice = None
                return {"action": "cancelled", "kind": context}
            cancelled_session = self.breastfeeding.cancel()
            if cancelled_session is not None:
                return {"action": "cancelled", "kind": "breastfeeding", "session_id": str(cancelled_session)}
            if self.sleep_started_at is not None:
                self.sleep_started_at = None
                return {"action": "cancelled", "kind": "sleep"}
            removed = self.record_store.pop_last()
            if removed is not None:
                return {"action": "undone", "kind": removed.kind, "record_id": str(removed.record_id)}
            return {"action": "nothing_to_undo"}

        if action is Action.STATUS:
            return {"action": "status", "status": self.snapshot(at)}

        raise ValueError(f"unknown action: {action}")

    def complete_voice(
        self,
        context: str,
        data: Dict[str, object],
        at: Optional[datetime] = None,
    ) -> LocalRecord:
        with self._lock:
            at = require_aware_utc(at or datetime.now(timezone.utc))
            if self.pending_voice not in {"bottle", "solid_food"}:
                raise ValueError("no voice action is waiting for confirmation")
            if self.pending_voice != context:
                raise ValueError("voice context changed before confirmation")
            record = LocalRecord(uuid4(), context, at, at, dict(data))
            self.record_store.add(record)
            self.pending_voice = None
            self._save_runtime_state()
            return record

    def complete_voice_transcript(
        self, transcript: str, at: Optional[datetime] = None
    ) -> LocalRecord:
        """Parse and consume the current voice intent as one atomic operation."""

        with self._lock:
            at = require_aware_utc(at or datetime.now(timezone.utc))
            context = self.pending_voice
            if context not in {"bottle", "solid_food"}:
                raise ValueError("no voice action is waiting for confirmation")
            data = parse_voice(context, transcript)
            record = LocalRecord(uuid4(), context, at, at, dict(data))
            self.record_store.add(record)
            self.pending_voice = None
            self._save_runtime_state()
            return record

    def snapshot(self, at: Optional[datetime] = None) -> Dict[str, object]:
        with self._lock:
            at = require_aware_utc(at or datetime.now(timezone.utc))
            sleep: Dict[str, object]
            if self.sleep_started_at is None:
                sleep = {"active": False}
            else:
                sleep = {
                    "active": True,
                    "started_at": self.sleep_started_at.isoformat(),
                    "elapsed_seconds": max(0, int((at - self.sleep_started_at).total_seconds())),
                }
            last_record = self.record_store.last()
            return {
                "breastfeeding": self.breastfeeding.snapshot(at),
                "sleep": sleep,
                "pending_voice": self.pending_voice,
                "record_count": self.record_store.count(),
                "last_record": last_record.kind if last_record else None,
            }

    def _save_runtime_state(self) -> None:
        if self.runtime_store is None:
            return
        self.runtime_store.save_runtime_state(
            {
                "breastfeeding": self.breastfeeding.dump_state(),
                "sleep_started_at": (
                    self.sleep_started_at.isoformat() if self.sleep_started_at else None
                ),
                "pending_voice": self.pending_voice,
            }
        )

    def _restore_runtime_state(self) -> None:
        if self.runtime_store is None:
            return
        state = self.runtime_store.load_runtime_state()
        if not state:
            return
        breastfeeding = state.get("breastfeeding")
        self.breastfeeding.restore_state(
            breastfeeding if isinstance(breastfeeding, dict) else None
        )
        sleep_started_at = state.get("sleep_started_at")
        if sleep_started_at:
            self.sleep_started_at = require_aware_utc(
                datetime.fromisoformat(str(sleep_started_at))
            )
        pending_voice = state.get("pending_voice")
        self.pending_voice = str(pending_voice) if pending_voice else None

    def _record_breastfeeding(self, completed: CompletedBreastfeeding) -> LocalRecord:
        record = LocalRecord(
            record_id=completed.session_id,
            kind="breastfeeding",
            started_at=completed.started_at,
            ended_at=completed.ended_at,
            data={
                "total_seconds": int(completed.total_duration.total_seconds()),
                "left_seconds": int(completed.duration_for(Side.LEFT).total_seconds()),
                "right_seconds": int(completed.duration_for(Side.RIGHT).total_seconds()),
                "last_side": completed.last_side.value,
                "segments": [
                    {
                        "side": segment.side.value,
                        "start": segment.start.isoformat(),
                        "end": segment.end.isoformat(),
                    }
                    for segment in completed.segments
                ],
            },
        )
        self.record_store.add(record)
        return record
