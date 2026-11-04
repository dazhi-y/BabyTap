from __future__ import annotations

from datetime import datetime
from typing import Dict, Optional, Protocol
from uuid import UUID

from .actions import Action, ActionRequest, ActionSource, action_for_key
from .easyinput_protocol import SpeakerCue
from .feedback import (
    FAILED_FEEDBACK_TTL_MS,
    FeedbackEvent,
    FeedbackRouter,
    FeedbackState,
)
from .service import BabyTapEngine
from .storage import ActionResultStore, OperationStatus, OperationStore
from .sync import SyncOutcome


class RecordSynchronizer(Protocol):
    def sync_record(self, record_id: UUID) -> SyncOutcome: ...

    def undo_record(self, record_id: UUID) -> SyncOutcome: ...


class ActionRouter:
    """The only production entry point from input adapters to BabyTap logic."""

    def __init__(
        self,
        engine: BabyTapEngine,
        feedback: Optional[FeedbackRouter] = None,
        synchronizer: Optional[RecordSynchronizer] = None,
        event_store: Optional[ActionResultStore] = None,
        operation_store: Optional[OperationStore] = None,
    ) -> None:
        self._engine = engine
        self._feedback = feedback or FeedbackRouter()
        self._synchronizer = synchronizer
        self._event_store = event_store
        self._operation_store = operation_store

    def dispatch_key(
        self,
        key: int,
        *,
        source: ActionSource,
        occurred_at: Optional[datetime] = None,
        event_id: Optional[UUID] = None,
    ) -> Dict[str, object]:
        return self.dispatch(
            ActionRequest.create(
                action_for_key(key),
                source,
                occurred_at=occurred_at,
                event_id=event_id,
            )
        )

    def dispatch(self, request: ActionRequest) -> Dict[str, object]:
        if self._event_store is not None:
            cached = self._event_store.load_action_result(request.event_id)
            if cached is not None:
                return {**cached, "deduplicated": True}
        try:
            result = self._engine.handle_action(request.action, request.occurred_at)
        except Exception as exc:
            self._feedback.publish(
                FeedbackEvent(
                    FeedbackState.FAILED,
                    FAILED_FEEDBACK_TTL_MS,
                    str(exc),
                    SpeakerCue.FAILED,
                )
            )
            raise

        response = {
            **result,
            "input_action": request.action.value,
            "source": request.source.value,
            "event_id": str(request.event_id),
        }
        record_id = result.get("record_id")
        if record_id:
            if result.get("action") == "undone":
                response.update(self.undo_record(UUID(str(record_id))))
            else:
                response.update(self.finalize_record(UUID(str(record_id))))
        else:
            self._publish_runtime_state(result)
        if self._event_store is not None:
            self._event_store.save_action_result(request.event_id, response)
        return response

    def finalize_record(self, record_id: UUID) -> Dict[str, object]:
        record = self._engine.record_store.get(record_id)
        if self._synchronizer is None:
            if record is not None and self._operation_store is not None:
                self._operation_store.ensure_operation(record_id, record.kind)
            self._publish_runtime_state()
            return {"sync_status": "local_only", "remote_count": 0}
        outcome = self._synchronizer.sync_record(record_id)
        if outcome.status is OperationStatus.SYNCED:
            cue = (
                SpeakerCue.DIAPER_RECORDED
                if record is not None and record.kind == "diaper"
                else SpeakerCue.RECORD_SAVED
            )
            self._feedback.publish(
                FeedbackEvent(
                    FeedbackState.COMPLETED,
                    5000,
                    "已写入 Baby Buddy",
                    cue,
                )
            )
        else:
            self._feedback.publish(
                FeedbackEvent(
                    FeedbackState.FAILED,
                    FAILED_FEEDBACK_TTL_MS,
                    outcome.error,
                    SpeakerCue.FAILED,
                )
            )
        return outcome.as_dict()

    def undo_record(self, record_id: UUID) -> Dict[str, object]:
        if self._synchronizer is None:
            record = self._engine.record_store.get(record_id)
            if record is not None and self._operation_store is not None:
                operation = self._operation_store.ensure_operation(record_id, record.kind)
                self._operation_store.save_operation(
                    record_id,
                    status=OperationStatus.UNDONE,
                    remote_refs=operation.remote_refs,
                    error=None,
                )
            self._publish_runtime_state()
            return {"sync_status": "local_only", "remote_count": 0}
        outcome = self._synchronizer.undo_record(record_id)
        if outcome.status is OperationStatus.UNDONE:
            self._feedback.publish(
                FeedbackEvent(
                    FeedbackState.COMPLETED,
                    5000,
                    "已撤销",
                    SpeakerCue.UNDONE,
                )
            )
        else:
            self._feedback.publish(
                FeedbackEvent(
                    FeedbackState.FAILED,
                    FAILED_FEEDBACK_TTL_MS,
                    outcome.error,
                    SpeakerCue.FAILED,
                )
            )
        return outcome.as_dict()

    def _publish_runtime_state(self, result: Optional[Dict[str, object]] = None) -> None:
        state = self._engine.snapshot()
        action = result.get("action") if result is not None else None
        cue = SpeakerCue.NONE
        if action == "voice_requested":
            cue = (
                SpeakerCue.BOTTLE_PROMPT
                if result.get("context") == "bottle"
                else SpeakerCue.SOLID_FOOD_PROMPT
            )
        elif action == "started":
            cue = (
                SpeakerCue.SLEEP_STARTED
                if result.get("kind") == "sleep"
                else SpeakerCue.TIMER_STARTED
            )
        elif action == "switched":
            cue = SpeakerCue.SIDE_SWITCHED
        elif action == "cancelled":
            cue = SpeakerCue.CANCELLED
        elif action == "nothing_to_undo":
            cue = SpeakerCue.NOTHING_TO_UNDO
        elif action == "status":
            if state["pending_voice"] is not None:
                cue = SpeakerCue.STATUS_WAITING
            elif state["breastfeeding"]["active"]:
                cue = SpeakerCue.STATUS_BREASTFEEDING
            elif state["sleep"]["active"]:
                cue = SpeakerCue.STATUS_SLEEP
            else:
                cue = SpeakerCue.STATUS_IDLE
        if state["pending_voice"] is not None:
            event = FeedbackEvent(
                FeedbackState.WAITING_USER, 5 * 60 * 1000, cue=cue
            )
        elif state["breastfeeding"]["active"] or state["sleep"]["active"]:
            event = FeedbackEvent(
                FeedbackState.RUNNING, 12 * 60 * 60 * 1000, cue=cue
            )
        else:
            # COMPLETED is intentionally reserved for an authoritative Baby
            # Buddy success response in A1.
            event = FeedbackEvent(FeedbackState.IDLE, 0, cue=cue)
        self._feedback.publish(event)
