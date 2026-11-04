from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import json
from pathlib import Path
import sqlite3
from threading import RLock
from typing import Dict, List, Optional, Protocol, Sequence, Tuple
from uuid import UUID

from .records import LocalRecord


class OperationStatus(str, Enum):
    PENDING = "pending"
    SYNCING = "syncing"
    SYNCED = "synced"
    FAILED = "failed"
    UNDONE = "undone"
    UNDO_FAILED = "undo_failed"


@dataclass(frozen=True)
class RemoteReference:
    endpoint: str
    remote_id: str


@dataclass(frozen=True)
class OperationEntry:
    record_id: UUID
    kind: str
    status: OperationStatus
    remote_refs: Tuple[RemoteReference, ...]
    attempts: int
    error: Optional[str]
    created_at: datetime
    updated_at: datetime


class OperationStore(Protocol):
    def ensure_operation(self, record_id: UUID, kind: str) -> OperationEntry: ...

    def get_operation(self, record_id: UUID) -> Optional[OperationEntry]: ...

    def list_operations(self, limit: int = 50) -> List[OperationEntry]: ...

    def save_operation(
        self,
        record_id: UUID,
        *,
        status: OperationStatus,
        remote_refs: Sequence[RemoteReference],
        error: Optional[str],
        increment_attempts: bool = False,
    ) -> OperationEntry: ...


class ActionResultStore(Protocol):
    def load_action_result(self, event_id: UUID) -> Optional[Dict[str, object]]: ...

    def save_action_result(
        self, event_id: UUID, result: Dict[str, object]
    ) -> None: ...


class SQLiteStore:
    """Durable local operation ledger plus resumable runtime state.

    Baby Buddy remains the long-term data source. SQLite only keeps enough
    correlation and runtime data to retry, undo and recover safely.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path))
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS records (
                    record_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT NOT NULL,
                    data_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    undone INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS operations (
                    record_id TEXT PRIMARY KEY REFERENCES records(record_id),
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    remote_refs_json TEXT NOT NULL DEFAULT '[]',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runtime_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    value_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS action_events (
                    event_id TEXT PRIMARY KEY,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _record_from_row(row: sqlite3.Row) -> LocalRecord:
        return LocalRecord(
            record_id=UUID(row["record_id"]),
            kind=row["kind"],
            started_at=datetime.fromisoformat(row["started_at"]),
            ended_at=datetime.fromisoformat(row["ended_at"]),
            data=json.loads(row["data_json"]),
        )

    def add(self, record: LocalRecord) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO records (
                    record_id, kind, started_at, ended_at, data_json, created_at, undone
                ) VALUES (?, ?, ?, ?, ?, ?, 0)
                ON CONFLICT(record_id) DO UPDATE SET
                    kind=excluded.kind,
                    started_at=excluded.started_at,
                    ended_at=excluded.ended_at,
                    data_json=excluded.data_json
                """,
                (
                    str(record.record_id),
                    record.kind,
                    record.started_at.isoformat(),
                    record.ended_at.isoformat(),
                    json.dumps(record.data, ensure_ascii=False, separators=(",", ":")),
                    self._now(),
                ),
            )

    def get(self, record_id: UUID) -> Optional[LocalRecord]:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM records WHERE record_id = ?", (str(record_id),)
            ).fetchone()
        return self._record_from_row(row) if row else None

    def pop_last(self) -> Optional[LocalRecord]:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM records
                WHERE undone = 0
                ORDER BY created_at DESC, rowid DESC
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                "UPDATE records SET undone = 1 WHERE record_id = ?",
                (row["record_id"],),
            )
        return self._record_from_row(row)

    def mark_undone(self, record_id: UUID) -> bool:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "UPDATE records SET undone = 1 WHERE record_id = ? AND undone = 0",
                (str(record_id),),
            )
        return cursor.rowcount > 0

    def last(self) -> Optional[LocalRecord]:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM records
                WHERE undone = 0
                ORDER BY created_at DESC, rowid DESC
                LIMIT 1
                """
            ).fetchone()
        return self._record_from_row(row) if row else None

    def count(self) -> int:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS value FROM records WHERE undone = 0"
            ).fetchone()
        return int(row["value"])

    def list(self) -> List[LocalRecord]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM records
                WHERE undone = 0
                ORDER BY created_at DESC, rowid DESC
                """
            ).fetchall()
        return [self._record_from_row(row) for row in rows]

    def save_runtime_state(self, state: Dict[str, object]) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO runtime_state (id, value_json, updated_at)
                VALUES (1, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    value_json=excluded.value_json,
                    updated_at=excluded.updated_at
                """,
                (
                    json.dumps(state, ensure_ascii=False, separators=(",", ":")),
                    self._now(),
                ),
            )

    def load_runtime_state(self) -> Optional[Dict[str, object]]:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT value_json FROM runtime_state WHERE id = 1"
            ).fetchone()
        return json.loads(row["value_json"]) if row else None

    def load_action_result(self, event_id: UUID) -> Optional[Dict[str, object]]:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT result_json FROM action_events WHERE event_id = ?",
                (str(event_id),),
            ).fetchone()
        return json.loads(row["result_json"]) if row else None

    def save_action_result(
        self, event_id: UUID, result: Dict[str, object]
    ) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO action_events (event_id, result_json, created_at)
                VALUES (?, ?, ?)
                """,
                (
                    str(event_id),
                    json.dumps(result, ensure_ascii=False, separators=(",", ":")),
                    self._now(),
                ),
            )

    @staticmethod
    def _operation_from_row(row: sqlite3.Row) -> OperationEntry:
        refs = tuple(
            RemoteReference(str(item["endpoint"]), str(item["remote_id"]))
            for item in json.loads(row["remote_refs_json"])
        )
        return OperationEntry(
            record_id=UUID(row["record_id"]),
            kind=row["kind"],
            status=OperationStatus(row["status"]),
            remote_refs=refs,
            attempts=int(row["attempts"]),
            error=row["error"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def ensure_operation(self, record_id: UUID, kind: str) -> OperationEntry:
        now = self._now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO operations (
                    record_id, kind, status, remote_refs_json,
                    attempts, error, created_at, updated_at
                ) VALUES (?, ?, ?, '[]', 0, NULL, ?, ?)
                """,
                (str(record_id), kind, OperationStatus.PENDING.value, now, now),
            )
            row = connection.execute(
                "SELECT * FROM operations WHERE record_id = ?", (str(record_id),)
            ).fetchone()
        assert row is not None
        return self._operation_from_row(row)

    def get_operation(self, record_id: UUID) -> Optional[OperationEntry]:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM operations WHERE record_id = ?", (str(record_id),)
            ).fetchone()
        return self._operation_from_row(row) if row else None

    def list_operations(self, limit: int = 50) -> List[OperationEntry]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM operations
                ORDER BY created_at DESC, rowid DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._operation_from_row(row) for row in rows]

    def save_operation(
        self,
        record_id: UUID,
        *,
        status: OperationStatus,
        remote_refs: Sequence[RemoteReference],
        error: Optional[str],
        increment_attempts: bool = False,
    ) -> OperationEntry:
        refs_json = json.dumps(
            [
                {"endpoint": item.endpoint, "remote_id": item.remote_id}
                for item in remote_refs
            ],
            separators=(",", ":"),
        )
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE operations SET
                    status = ?, remote_refs_json = ?, error = ?,
                    attempts = attempts + ?, updated_at = ?
                WHERE record_id = ?
                """,
                (
                    status.value,
                    refs_json,
                    error,
                    1 if increment_attempts else 0,
                    self._now(),
                    str(record_id),
                ),
            )
            row = connection.execute(
                "SELECT * FROM operations WHERE record_id = ?", (str(record_id),)
            ).fetchone()
        if row is None:
            raise KeyError(f"operation not found: {record_id}")
        return self._operation_from_row(row)
