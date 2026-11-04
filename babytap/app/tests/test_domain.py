from datetime import datetime, timedelta, timezone
import unittest

from babytap.domain import (
    BreastfeedingAction,
    BreastfeedingStateMachine,
    InvalidTransition,
    Side,
)


BASE = datetime(2026, 10, 10, 10, 0, tzinfo=timezone.utc)


class BreastfeedingStateMachineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.machine = BreastfeedingStateMachine()

    def press(self, side: Side, minutes: int):
        return self.machine.press(side, BASE + timedelta(minutes=minutes))

    def test_left_only(self) -> None:
        self.assertEqual(self.press(Side.LEFT, 0).action, BreastfeedingAction.STARTED)
        result = self.press(Side.LEFT, 8)
        self.assertEqual(result.action, BreastfeedingAction.COMPLETED)
        self.assertEqual(result.completed.duration_for(Side.LEFT), timedelta(minutes=8))
        self.assertEqual(result.completed.duration_for(Side.RIGHT), timedelta())
        self.assertEqual(result.completed.last_side, Side.LEFT)

    def test_right_only(self) -> None:
        self.press(Side.RIGHT, 0)
        result = self.press(Side.RIGHT, 6)
        self.assertEqual(result.completed.duration_for(Side.RIGHT), timedelta(minutes=6))
        self.assertEqual(result.completed.last_side, Side.RIGHT)

    def test_left_then_right(self) -> None:
        self.press(Side.LEFT, 0)
        switched = self.press(Side.RIGHT, 5)
        self.assertEqual(switched.action, BreastfeedingAction.SWITCHED)
        result = self.press(Side.RIGHT, 11)
        self.assertEqual(result.completed.duration_for(Side.LEFT), timedelta(minutes=5))
        self.assertEqual(result.completed.duration_for(Side.RIGHT), timedelta(minutes=6))

    def test_right_then_left(self) -> None:
        self.press(Side.RIGHT, 0)
        self.press(Side.LEFT, 4)
        result = self.press(Side.LEFT, 10)
        self.assertEqual(result.completed.duration_for(Side.RIGHT), timedelta(minutes=4))
        self.assertEqual(result.completed.duration_for(Side.LEFT), timedelta(minutes=6))

    def test_multiple_switches(self) -> None:
        self.press(Side.LEFT, 0)
        self.press(Side.RIGHT, 3)
        self.press(Side.LEFT, 8)
        self.press(Side.RIGHT, 10)
        result = self.press(Side.RIGHT, 14)
        self.assertEqual(len(result.completed.segments), 4)
        self.assertEqual(result.completed.duration_for(Side.LEFT), timedelta(minutes=5))
        self.assertEqual(result.completed.duration_for(Side.RIGHT), timedelta(minutes=9))
        self.assertEqual(result.completed.total_duration, timedelta(minutes=14))

    def test_rejects_non_increasing_time(self) -> None:
        self.press(Side.LEFT, 0)
        with self.assertRaises(InvalidTransition):
            self.press(Side.LEFT, 0)


if __name__ == "__main__":
    unittest.main()

