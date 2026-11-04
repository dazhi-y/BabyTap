from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from babytap.records import LocalRecord
from babytap.storage import OperationStatus, RemoteReference, SQLiteStore


BASE = datetime(2026, 10, 10, 10, 0, tzinfo=timezone.utc)


class SQLiteStoreTests(unittest.TestCase):
    def test_records_runtime_and_operations_survive_reopen(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "babytap.sqlite3"
            record = LocalRecord(uuid4(), "diaper", BASE, BASE, {"x": 1})
            store = SQLiteStore(path)
            store.add(record)
            store.save_runtime_state({"pending_voice": "bottle"})
            store.ensure_operation(record.record_id, record.kind)
            store.save_operation(
                record.record_id,
                status=OperationStatus.SYNCED,
                remote_refs=[RemoteReference("babytap/events", "event-42")],
                error=None,
                increment_attempts=True,
            )

            reopened = SQLiteStore(path)
            self.assertEqual(reopened.get(record.record_id), record)
            self.assertEqual(reopened.load_runtime_state()["pending_voice"], "bottle")
            operation = reopened.get_operation(record.record_id)
            self.assertEqual(operation.status, OperationStatus.SYNCED)
            self.assertEqual(operation.remote_refs[0].remote_id, "event-42")

            self.assertEqual(reopened.pop_last(), record)
            self.assertEqual(reopened.count(), 0)
            self.assertEqual(reopened.get(record.record_id), record)

    def test_mark_undone_hides_a_specific_record(self) -> None:
        with TemporaryDirectory() as directory:
            store = SQLiteStore(Path(directory) / "babytap.sqlite3")
            first = LocalRecord(uuid4(), "diaper", BASE, BASE, {})
            second = LocalRecord(uuid4(), "diaper", BASE, BASE, {})
            store.add(first)
            store.add(second)

            self.assertTrue(store.mark_undone(first.record_id))
            self.assertFalse(store.mark_undone(first.record_id))
            self.assertEqual(store.list(), [second])
            self.assertEqual(store.get(first.record_id), first)


if __name__ == "__main__":
    unittest.main()
