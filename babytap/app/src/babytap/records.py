from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from threading import RLock
from typing import Dict, List, Optional, Protocol
from uuid import UUID


@dataclass(frozen=True)
class LocalRecord:
    record_id: UUID
    kind: str
    started_at: datetime
    ended_at: datetime
    data: Dict[str, object]


class RecordStore(Protocol):
    def add(self, record: LocalRecord) -> None: ...

    def get(self, record_id: UUID) -> Optional[LocalRecord]: ...

    def pop_last(self) -> Optional[LocalRecord]: ...

    def mark_undone(self, record_id: UUID) -> bool: ...

    def last(self) -> Optional[LocalRecord]: ...

    def count(self) -> int: ...

    def list(self) -> List[LocalRecord]: ...


class InMemoryRecordStore:
    """A deterministic test store; production uses SQLiteStore."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._records: List[LocalRecord] = []

    def add(self, record: LocalRecord) -> None:
        with self._lock:
            self._records.append(record)

    def get(self, record_id: UUID) -> Optional[LocalRecord]:
        with self._lock:
            return next(
                (record for record in self._records if record.record_id == record_id),
                None,
            )

    def pop_last(self) -> Optional[LocalRecord]:
        with self._lock:
            return self._records.pop() if self._records else None

    def mark_undone(self, record_id: UUID) -> bool:
        with self._lock:
            for index, record in enumerate(self._records):
                if record.record_id == record_id:
                    del self._records[index]
                    return True
        return False

    def last(self) -> Optional[LocalRecord]:
        with self._lock:
            return self._records[-1] if self._records else None

    def count(self) -> int:
        with self._lock:
            return len(self._records)

    def list(self) -> List[LocalRecord]:
        with self._lock:
            return list(self._records)
