from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional
from uuid import UUID

from .babybuddy import BabyBuddyClient
from .mapping import record_event_payload
from .records import RecordStore
from .storage import (
    OperationEntry,
    OperationStatus,
    OperationStore,
    RemoteReference,
)


@dataclass(frozen=True)
class SyncOutcome:
    record_id: UUID
    status: OperationStatus
    remote_count: int
    error: Optional[str] = None

    def as_dict(self) -> Dict[str, object]:
        return {
            "record_id": str(self.record_id),
            "sync_status": self.status.value,
            "remote_count": self.remote_count,
            "sync_error": self.error,
        }


class BabyBuddySynchronizer:
    def __init__(
        self,
        records: RecordStore,
        operations: OperationStore,
        client: BabyBuddyClient,
    ) -> None:
        self.records = records
        self.operations = operations
        self.client = client

    @staticmethod
    def _outcome(operation: OperationEntry) -> SyncOutcome:
        return SyncOutcome(
            operation.record_id,
            operation.status,
            len(operation.remote_refs),
            operation.error,
        )

    def sync_record(self, record_id: UUID) -> SyncOutcome:
        record = self.records.get(record_id)
        if record is None:
            raise KeyError(f"record not found: {record_id}")
        operation = self.operations.ensure_operation(record_id, record.kind)
        if operation.status is OperationStatus.SYNCED:
            return self._outcome(operation)
        if operation.status is OperationStatus.UNDONE:
            raise ValueError("an undone operation cannot be synchronized")

        operation = self.operations.save_operation(
            record_id,
            status=OperationStatus.SYNCING,
            remote_refs=operation.remote_refs,
            error=None,
            increment_attempts=True,
        )
        try:
            payload = record_event_payload(record, self.client.config)
            result = self.client.create_event(payload)
            remote_id = str(result["event_id"])
            if remote_id != str(record_id):
                raise ValueError("BabyTap server returned a different event_id")
            refs = [RemoteReference("babytap/events", remote_id)]
        except Exception as exc:
            operation = self.operations.save_operation(
                record_id,
                status=OperationStatus.FAILED,
                remote_refs=operation.remote_refs,
                error=str(exc),
            )
            return self._outcome(operation)

        operation = self.operations.save_operation(
            record_id,
            status=OperationStatus.SYNCED,
            remote_refs=refs,
            error=None,
        )
        return self._outcome(operation)

    def undo_record(self, record_id: UUID) -> SyncOutcome:
        record = self.records.get(record_id)
        operation = self.operations.get_operation(record_id)
        if operation is None:
            if record is None:
                raise KeyError(f"record not found: {record_id}")
            operation = self.operations.ensure_operation(record_id, record.kind)
        if operation.status is OperationStatus.UNDONE:
            return self._outcome(operation)

        try:
            self.client.delete_event(str(record_id))
        except Exception as exc:
            operation = self.operations.save_operation(
                record_id,
                status=OperationStatus.UNDO_FAILED,
                remote_refs=operation.remote_refs,
                error=str(exc),
                increment_attempts=True,
            )
            return self._outcome(operation)

        operation = self.operations.save_operation(
            record_id,
            status=OperationStatus.UNDONE,
            remote_refs=(),
            error=None,
            increment_attempts=True,
        )
        return self._outcome(operation)

    def retry(self, record_id: UUID) -> SyncOutcome:
        operation = self.operations.get_operation(record_id)
        if operation is None:
            return self.sync_record(record_id)
        if operation.status is OperationStatus.UNDO_FAILED:
            return self.undo_record(record_id)
        return self.sync_record(record_id)
