from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import json

import httpx

from babytap.action_router import ActionRouter
from babytap.actions import ActionSource
from babytap.babybuddy import BabyBuddyClient, BabyBuddyConfig
from babytap.feedback import FeedbackRouter
from babytap.service import BabyTapEngine
from babytap.storage import SQLiteStore
from babytap.sync import BabyBuddySynchronizer


BASE = datetime(2026, 10, 10, 2, 0, tzinfo=timezone.utc)


class NonHardwareAcceptanceTests(unittest.TestCase):
    def test_three_complete_rounds_without_easyinput(self) -> None:
        remote = {"next_id": 1, "posts": 0, "deletes": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST":
                payload = json.loads(request.content)
                remote["next_id"] += 1
                remote["posts"] += 1
                return httpx.Response(201, json={"event_id": payload["event_id"]})
            if request.method == "DELETE":
                remote["deletes"] += 1
                return httpx.Response(204)
            raise AssertionError(request.method)

        with TemporaryDirectory() as directory:
            store = SQLiteStore(Path(directory) / "db.sqlite3")
            engine = BabyTapEngine(store, store)
            client = BabyBuddyClient(
                BabyBuddyConfig("http://baby.test", "secret", 9),
                transport=httpx.MockTransport(handler),
            )
            feedback = FeedbackRouter()
            router = ActionRouter(
                engine,
                feedback,
                BabyBuddySynchronizer(store, store, client),
            )

            breastfeeding_keys = ([1, 1], [2, 1, 1], [1, 2, 1, 1])
            for round_index, keys in enumerate(breastfeeding_keys):
                start = BASE + timedelta(hours=round_index * 3)
                for minute, key in enumerate(keys):
                    result = router.dispatch_key(
                        key,
                        source=ActionSource.TEST,
                        occurred_at=start + timedelta(minutes=minute * 3),
                    )
                self.assertEqual(result["sync_status"], "synced")

                router.dispatch_key(
                    3,
                    source=ActionSource.TEST,
                    occurred_at=start + timedelta(minutes=20),
                )
                bottle = engine.complete_voice(
                    "bottle",
                    {"amount_ml": 100 + round_index * 10, "transcript": "奶瓶"},
                    start + timedelta(minutes=21),
                )
                self.assertEqual(
                    router.finalize_record(bottle.record_id)["sync_status"], "synced"
                )

                router.dispatch_key(
                    4,
                    source=ActionSource.TEST,
                    occurred_at=start + timedelta(minutes=22),
                )
                solid = engine.complete_voice(
                    "solid_food",
                    {"description": "南瓜泥", "transcript": "南瓜泥"},
                    start + timedelta(minutes=23),
                )
                self.assertEqual(
                    router.finalize_record(solid.record_id)["sync_status"], "synced"
                )

                diaper = router.dispatch_key(
                    5,
                    source=ActionSource.TEST,
                    occurred_at=start + timedelta(minutes=24),
                )
                self.assertEqual(diaper["sync_status"], "synced")

                router.dispatch_key(
                    6,
                    source=ActionSource.TEST,
                    occurred_at=start + timedelta(minutes=25),
                )
                sleep = router.dispatch_key(
                    6,
                    source=ActionSource.TEST,
                    occurred_at=start + timedelta(minutes=55),
                )
                self.assertEqual(sleep["sync_status"], "synced")
                self.assertEqual(
                    router.dispatch_key(
                        8,
                        source=ActionSource.TEST,
                        occurred_at=start + timedelta(minutes=56),
                    )["action"],
                    "status",
                )

            undone = router.dispatch_key(
                7,
                source=ActionSource.TEST,
                occurred_at=BASE + timedelta(hours=7),
            )
            self.assertEqual(undone["sync_status"], "undone")
            self.assertEqual(remote["deletes"], 1)
            self.assertEqual(engine.snapshot()["record_count"], 14)
            self.assertGreaterEqual(remote["posts"], 15)


if __name__ == "__main__":
    unittest.main()
