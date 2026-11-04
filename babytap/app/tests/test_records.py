from datetime import datetime, timezone
import unittest
from uuid import uuid4

from babytap.records import InMemoryRecordStore, LocalRecord


BASE = datetime(2026, 10, 10, 10, 0, tzinfo=timezone.utc)


class InMemoryRecordStoreTests(unittest.TestCase):
    def test_add_list_and_pop_are_isolated(self) -> None:
        store = InMemoryRecordStore()
        record = LocalRecord(uuid4(), "diaper", BASE, BASE, {})
        store.add(record)
        copy = store.list()
        copy.clear()
        self.assertEqual(store.count(), 1)
        self.assertEqual(store.last(), record)
        self.assertEqual(store.pop_last(), record)
        self.assertIsNone(store.pop_last())

    def test_mark_undone_removes_only_the_selected_record(self) -> None:
        store = InMemoryRecordStore()
        first = LocalRecord(uuid4(), "diaper", BASE, BASE, {})
        second = LocalRecord(uuid4(), "diaper", BASE, BASE, {})
        store.add(first)
        store.add(second)

        self.assertTrue(store.mark_undone(first.record_id))
        self.assertFalse(store.mark_undone(first.record_id))
        self.assertEqual(store.list(), [second])


if __name__ == "__main__":
    unittest.main()
