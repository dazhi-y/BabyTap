from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from babytap.service import BabyTapEngine
from babytap.storage import SQLiteStore


BASE = datetime(2026, 10, 10, 10, 0, tzinfo=timezone.utc)


class BabyTapEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = BabyTapEngine()

    def test_diaper_is_recorded_immediately(self) -> None:
        result = self.engine.handle_key(5, BASE)
        self.assertEqual(result["kind"], "diaper")
        self.assertEqual(self.engine.snapshot(BASE)["record_count"], 1)

    def test_sleep_toggles(self) -> None:
        self.assertEqual(self.engine.handle_key(6, BASE)["action"], "started")
        result = self.engine.handle_key(6, BASE + timedelta(minutes=45))
        self.assertEqual(result["action"], "completed")
        self.assertEqual(result["duration_seconds"], 2700)

    def test_voice_context_can_be_cancelled(self) -> None:
        self.engine.handle_key(4, BASE)
        result = self.engine.handle_key(7, BASE + timedelta(seconds=1))
        self.assertEqual(result, {"action": "cancelled", "kind": "solid_food"})

    def test_undo_removes_last_completed_record(self) -> None:
        self.engine.handle_key(5, BASE)
        result = self.engine.handle_key(7, BASE + timedelta(seconds=1))
        self.assertEqual(result["action"], "undone")
        self.assertEqual(self.engine.snapshot(BASE)["record_count"], 0)

    def test_status_key_returns_current_state(self) -> None:
        self.engine.handle_key(6, BASE)
        result = self.engine.handle_key(8, BASE + timedelta(minutes=3))
        self.assertEqual(result["action"], "status")
        self.assertEqual(result["status"]["sleep"]["elapsed_seconds"], 180)

    def test_active_breastfeeding_survives_restart(self) -> None:
        with TemporaryDirectory() as directory:
            store = SQLiteStore(Path(directory) / "db.sqlite3")
            first = BabyTapEngine(store, store)
            started = first.handle_key(2, BASE)

            restarted = BabyTapEngine(store, store)
            snapshot = restarted.snapshot(BASE + timedelta(minutes=4))
            self.assertTrue(snapshot["breastfeeding"]["active"])
            self.assertEqual(snapshot["breastfeeding"]["side"], "right")
            completed = restarted.handle_key(2, BASE + timedelta(minutes=6))
            self.assertEqual(completed["session_id"], started["session_id"])
            self.assertEqual(store.count(), 1)

    def test_voice_confirmation_creates_a_record(self) -> None:
        self.engine.handle_key(3, BASE)
        record = self.engine.complete_voice(
            "bottle",
            {"amount_ml": 120, "transcript": "120 毫升"},
            BASE + timedelta(seconds=2),
        )
        self.assertEqual(record.kind, "bottle")
        self.assertEqual(self.engine.snapshot(BASE)["pending_voice"], None)

    def test_voice_confirmation_rejects_a_changed_context(self) -> None:
        self.engine.handle_key(3, BASE)
        self.engine.handle_key(4, BASE + timedelta(seconds=1))

        with self.assertRaisesRegex(ValueError, "voice context changed"):
            self.engine.complete_voice(
                "bottle",
                {"amount_ml": 120, "transcript": "120 毫升"},
                BASE + timedelta(seconds=2),
            )

        snapshot = self.engine.snapshot(BASE + timedelta(seconds=2))
        self.assertEqual(snapshot["pending_voice"], "solid_food")
        self.assertEqual(snapshot["record_count"], 0)

    def test_voice_text_confirmation_is_atomic_with_same_context_restart(self) -> None:
        self.engine.handle_key(3, BASE)
        parse_started = Event()
        release_parse = Event()

        def blocking_parse(context: str, transcript: str) -> dict:
            self.assertEqual(context, "bottle")
            parse_started.set()
            self.assertTrue(release_parse.wait(timeout=1))
            return {"amount_ml": 120, "transcript": transcript}

        def cancel_and_restart() -> tuple:
            cancelled = self.engine.handle_key(7, BASE + timedelta(seconds=2))
            restarted = self.engine.handle_key(3, BASE + timedelta(seconds=3))
            return cancelled, restarted

        with patch("babytap.service.parse_voice", side_effect=blocking_parse):
            with ThreadPoolExecutor(max_workers=2) as executor:
                confirmation = executor.submit(
                    self.engine.complete_voice_transcript,
                    "120 毫升",
                    BASE + timedelta(seconds=1),
                )
                self.assertTrue(parse_started.wait(timeout=1))
                restart = executor.submit(cancel_and_restart)
                self.assertFalse(restart.done())
                release_parse.set()

                record = confirmation.result(timeout=1)
                cancelled, restarted = restart.result(timeout=1)

        self.assertEqual(record.kind, "bottle")
        self.assertEqual(cancelled["action"], "undone")
        self.assertEqual(restarted["action"], "voice_requested")
        snapshot = self.engine.snapshot(BASE + timedelta(seconds=3))
        self.assertEqual(snapshot["pending_voice"], "bottle")
        self.assertEqual(snapshot["record_count"], 0)


if __name__ == "__main__":
    unittest.main()
