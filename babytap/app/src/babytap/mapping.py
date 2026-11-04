from __future__ import annotations

from typing import Dict

from .babybuddy import BabyBuddyConfig
from .records import LocalRecord


def record_event_payload(
    record: LocalRecord,
    config: BabyBuddyConfig,
) -> Dict[str, object]:
    correlation = f"babytap_record={record.record_id}"
    data: Dict[str, object]

    if record.kind == "breastfeeding":
        segments = record.data.get("segments", [])
        if not isinstance(segments, list) or not segments:
            raise ValueError("breastfeeding record has no segments")
        normalized_segments = []
        for segment in segments:
            if not isinstance(segment, dict):
                raise ValueError("invalid breastfeeding segment")
            side = str(segment["side"])
            if side not in {"left", "right"}:
                raise ValueError("invalid breastfeeding side")
            normalized_segments.append(
                {
                    "side": side,
                    "start": str(segment["start"]),
                    "end": str(segment["end"]),
                }
            )
        data = {"segments": normalized_segments, "notes": correlation}
    elif record.kind == "bottle":
        data = {
            "start": record.started_at.isoformat(),
            "end": record.ended_at.isoformat(),
            "type": config.bottle_type,
            "amount": float(record.data["amount_ml"]),
            "notes": correlation,
        }
    elif record.kind == "solid_food":
        data = {
            "start": record.started_at.isoformat(),
            "end": record.ended_at.isoformat(),
            "method": "parent fed",
            "notes": f"{record.data['description']}\n{correlation}",
        }
    elif record.kind == "diaper":
        data = {
            "wet": False,
            "solid": False,
            "notes": f"Diaper changed; contents unspecified. {correlation}",
        }
    elif record.kind == "sleep":
        data = {
            "start": record.started_at.isoformat(),
            "end": record.ended_at.isoformat(),
            "notes": correlation,
        }
    else:
        raise ValueError(f"unsupported record kind: {record.kind}")

    return {
        "event_id": str(record.record_id),
        "child": config.child_id,
        "kind": record.kind,
        "occurred_at": record.ended_at.isoformat(),
        "data": data,
    }
