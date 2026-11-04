from datetime import datetime, timezone
import unittest
from uuid import uuid4

from babytap.babybuddy import BabyBuddyConfig
from babytap.mapping import record_event_payload
from babytap.records import LocalRecord


class MappingTests(unittest.TestCase):
    def test_breastfeeding_segments_keep_actual_side_order_in_one_event(self) -> None:
        record = LocalRecord(
            uuid4(),
            "breastfeeding",
            datetime.now(timezone.utc),
            datetime.now(timezone.utc),
            {
                "segments": [
                    {"side": "right", "start": "a", "end": "b"},
                    {"side": "left", "start": "b", "end": "c"},
                ]
            },
        )
        payload = record_event_payload(
            record, BabyBuddyConfig("http://baby.test", "token", 7)
        )
        self.assertEqual(payload["kind"], "breastfeeding")
        self.assertEqual(payload["child"], 7)
        self.assertEqual(
            [item["side"] for item in payload["data"]["segments"]],
            ["right", "left"],
        )

    def test_all_records_map_to_the_atomic_event_contract(self) -> None:
        config = BabyBuddyConfig("http://baby.test", "token", 7, "formula")
        records = [
            LocalRecord(uuid4(), "bottle", datetime.now(timezone.utc), datetime.now(timezone.utc), {"amount_ml": 120}),
            LocalRecord(uuid4(), "solid_food", datetime.now(timezone.utc), datetime.now(timezone.utc), {"description": "南瓜泥"}),
            LocalRecord(uuid4(), "diaper", datetime.now(timezone.utc), datetime.now(timezone.utc), {}),
            LocalRecord(uuid4(), "sleep", datetime.now(timezone.utc), datetime.now(timezone.utc), {}),
        ]
        payloads = [record_event_payload(record, config) for record in records]
        self.assertEqual(
            [item["kind"] for item in payloads],
            ["bottle", "solid_food", "diaper", "sleep"],
        )
        self.assertEqual(payloads[0]["data"]["type"], "formula")
        self.assertEqual(payloads[1]["data"]["method"], "parent fed")
        self.assertEqual(
            (payloads[2]["data"]["wet"], payloads[2]["data"]["solid"]),
            (False, False),
        )
        self.assertTrue(all(item["event_id"] for item in payloads))


if __name__ == "__main__":
    unittest.main()
