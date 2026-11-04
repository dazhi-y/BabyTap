from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
from uuid import uuid4

import httpx

from babytap.babybuddy import BabyBuddyClient, BabyBuddyConfig
from babytap.records import LocalRecord
from babytap.storage import OperationStatus, SQLiteStore
from babytap.sync import BabyBuddySynchronizer


BASE = datetime(2026, 10, 10, 10, 0, tzinfo=timezone.utc)


class SynchronizerTests(unittest.TestCase):
    def test_check_returns_the_selected_child_profile(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/children/")
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "id": 7,
                            "first_name": "测试宝宝",
                            "last_name": "",
                            "birth_date": "2025-01-15",
                            "picture": None,
                        },
                        {
                            "id": 8,
                            "first_name": "其他宝宝",
                            "last_name": "",
                            "birth_date": "2026-01-01",
                        },
                    ]
                },
            )

        client = BabyBuddyClient(
            BabyBuddyConfig("http://baby.test", "secret", 7),
            transport=httpx.MockTransport(handler),
        )

        result = client.check()

        self.assertTrue(result["child_found"])
        self.assertEqual(
            result["child"],
            {
                "first_name": "测试宝宝",
                "last_name": "",
                "birth_date": "2025-01-15",
            },
        )

    def test_loopback_server_bypasses_system_proxy(self) -> None:
        for base_url in (
            "http://localhost:8000",
            "http://127.0.0.1:8000",
            "http://[::1]:8000",
        ):
            client = BabyBuddyClient(BabyBuddyConfig(base_url, "secret", 7))
            self.assertFalse(client._trust_env)

        remote_client = BabyBuddyClient(
            BabyBuddyConfig("https://baby.example", "secret", 7)
        )
        self.assertTrue(remote_client._trust_env)

    def test_event_retry_is_idempotent_and_undo_uses_the_event_id(self) -> None:
        posts = []
        deletes = []
        fail_once = {"value": True}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST":
                posts.append(request)
                if fail_once["value"]:
                    fail_once["value"] = False
                    return httpx.Response(503, text="try later")
                payload = json.loads(request.content)
                return httpx.Response(201, json={"event_id": payload["event_id"]})
            if request.method == "DELETE":
                deletes.append(str(request.url))
                return httpx.Response(204)
            raise AssertionError(request.method)

        with TemporaryDirectory() as directory:
            store = SQLiteStore(Path(directory) / "db.sqlite3")
            record = LocalRecord(
                uuid4(),
                "breastfeeding",
                BASE,
                BASE + timedelta(minutes=9),
                {
                    "segments": [
                        {
                            "side": "right",
                            "start": BASE.isoformat(),
                            "end": (BASE + timedelta(minutes=4)).isoformat(),
                        },
                        {
                            "side": "left",
                            "start": (BASE + timedelta(minutes=4)).isoformat(),
                            "end": (BASE + timedelta(minutes=9)).isoformat(),
                        },
                    ]
                },
            )
            store.add(record)
            client = BabyBuddyClient(
                BabyBuddyConfig("http://baby.test", "secret", 7),
                transport=httpx.MockTransport(handler),
            )
            sync = BabyBuddySynchronizer(store, store, client)

            first = sync.sync_record(record.record_id)
            self.assertEqual(first.status, OperationStatus.FAILED)
            self.assertEqual(first.remote_count, 0)

            second = sync.retry(record.record_id)
            self.assertEqual(second.status, OperationStatus.SYNCED)
            self.assertEqual(second.remote_count, 1)
            self.assertEqual(len(posts), 2)

            duplicate = sync.sync_record(record.record_id)
            self.assertEqual(duplicate.status, OperationStatus.SYNCED)
            self.assertEqual(len(posts), 2)

            undone = sync.undo_record(record.record_id)
            self.assertEqual(undone.status, OperationStatus.UNDONE)
            self.assertEqual(len(deletes), 1)
            self.assertIn(str(record.record_id), deletes[0])


if __name__ == "__main__":
    unittest.main()
