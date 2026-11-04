from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from uuid import UUID, uuid4

from babytap.action_router import ActionRouter
from babytap.actions import Action, ActionRequest, ActionSource, action_for_key
from babytap.easyinput_protocol import SpeakerCue
from babytap.feedback import FeedbackRouter
from babytap.service import BabyTapEngine
from babytap.storage import SQLiteStore


BASE = datetime(2026, 10, 10, 10, 0, tzinfo=timezone.utc)


class ActionRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.feedback = FeedbackRouter()
        self.router = ActionRouter(BabyTapEngine(), self.feedback)

    def test_all_eight_keys_have_one_stable_action(self) -> None:
        self.assertEqual(
            [action_for_key(key) for key in range(1, 9)],
            list(Action),
        )

    def test_web_and_easyinput_share_the_same_business_path(self) -> None:
        web = ActionRouter(BabyTapEngine()).dispatch_key(
            2, source=ActionSource.WEB, occurred_at=BASE
        )
        hardware = ActionRouter(BabyTapEngine()).dispatch_key(
            2, source=ActionSource.EASYINPUT, occurred_at=BASE
        )
        self.assertEqual(web["action"], hardware["action"])
        self.assertEqual(web["active_side"], hardware["active_side"])
        self.assertEqual(web["input_action"], hardware["input_action"])

    def test_request_metadata_is_returned_for_future_idempotency(self) -> None:
        request = ActionRequest.create(
            Action.DIAPER, ActionSource.TEST, occurred_at=BASE
        )
        result = self.router.dispatch(request)
        self.assertEqual(result["event_id"], str(request.event_id))
        self.assertEqual(UUID(result["event_id"]), request.event_id)

    def test_runtime_feedback_does_not_claim_remote_success(self) -> None:
        self.router.dispatch_key(5, source=ActionSource.WEB, occurred_at=BASE)
        self.assertEqual(self.feedback.snapshot()["state"], "idle")
        self.router.dispatch_key(3, source=ActionSource.WEB, occurred_at=BASE)
        self.assertEqual(self.feedback.snapshot()["state"], "waiting_user")
        self.assertEqual(
            self.feedback.snapshot()["cue"], SpeakerCue.BOTTLE_PROMPT
        )

    def test_status_and_runtime_actions_select_board_speaker_cues(self) -> None:
        self.router.dispatch_key(1, source=ActionSource.WEB, occurred_at=BASE)
        self.assertEqual(
            self.feedback.snapshot()["cue"], SpeakerCue.TIMER_STARTED
        )
        self.router.dispatch_key(8, source=ActionSource.WEB, occurred_at=BASE)
        self.assertEqual(
            self.feedback.snapshot()["cue"], SpeakerCue.STATUS_BREASTFEEDING
        )
        self.router.dispatch_key(7, source=ActionSource.WEB, occurred_at=BASE)
        self.assertEqual(self.feedback.snapshot()["cue"], SpeakerCue.CANCELLED)

    def test_business_exception_keeps_failed_feedback_visible(self) -> None:
        self.router.dispatch_key(1, source=ActionSource.WEB, occurred_at=BASE)
        with self.assertRaises(Exception):
            self.router.dispatch_key(1, source=ActionSource.WEB, occurred_at=BASE)
        self.assertEqual(self.feedback.snapshot()["state"], "failed")
        self.assertEqual(self.feedback.snapshot()["ttl_ms"], 8000)

    def test_invalid_key_publishes_no_success(self) -> None:
        with self.assertRaises(ValueError):
            self.router.dispatch_key(9, source=ActionSource.WEB, occurred_at=BASE)
        self.assertIsNone(self.feedback.snapshot())

    def test_same_event_id_is_only_applied_once(self) -> None:
        with TemporaryDirectory() as directory:
            store = SQLiteStore(Path(directory) / "db.sqlite3")
            engine = BabyTapEngine(store, store)
            router = ActionRouter(engine, event_store=store)
            event_id = uuid4()
            first = router.dispatch_key(
                5,
                source=ActionSource.TEST,
                occurred_at=BASE,
                event_id=event_id,
            )
            second = router.dispatch_key(
                5,
                source=ActionSource.TEST,
                occurred_at=BASE,
                event_id=event_id,
            )
            self.assertEqual(first["record_id"], second["record_id"])
            self.assertTrue(second["deduplicated"])
            self.assertEqual(store.count(), 1)

    def test_local_only_records_stay_retryable_and_undo_is_visible(self) -> None:
        with TemporaryDirectory() as directory:
            store = SQLiteStore(Path(directory) / "db.sqlite3")
            engine = BabyTapEngine(store, store)
            router = ActionRouter(engine, operation_store=store)
            recorded = router.dispatch_key(
                5, source=ActionSource.TEST, occurred_at=BASE
            )
            self.assertEqual(recorded["sync_status"], "local_only")
            operation = store.get_operation(UUID(recorded["record_id"]))
            self.assertEqual(operation.status.value, "pending")

            undone = router.dispatch_key(
                7, source=ActionSource.TEST, occurred_at=BASE
            )
            self.assertEqual(undone["sync_status"], "local_only")
            operation = store.get_operation(UUID(recorded["record_id"]))
            self.assertEqual(operation.status.value, "undone")


if __name__ == "__main__":
    unittest.main()
