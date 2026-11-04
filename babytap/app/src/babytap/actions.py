from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, Optional
from uuid import UUID, uuid4

from .domain import require_aware_utc


class Action(str, Enum):
    BREAST_LEFT = "breast_left"
    BREAST_RIGHT = "breast_right"
    BOTTLE_VOICE = "bottle_voice"
    SOLID_FOOD_VOICE = "solid_food_voice"
    DIAPER = "diaper"
    SLEEP_TOGGLE = "sleep_toggle"
    UNDO_OR_CANCEL = "undo_or_cancel"
    STATUS = "status"


KEY_TO_ACTION: Dict[int, Action] = {
    1: Action.BREAST_LEFT,
    2: Action.BREAST_RIGHT,
    3: Action.BOTTLE_VOICE,
    4: Action.SOLID_FOOD_VOICE,
    5: Action.DIAPER,
    6: Action.SLEEP_TOGGLE,
    7: Action.UNDO_OR_CANCEL,
    8: Action.STATUS,
}


class ActionSource(str, Enum):
    WEB = "web"
    EASYINPUT = "easyinput"
    TEST = "test"


def action_for_key(key: int) -> Action:
    try:
        return KEY_TO_ACTION[key]
    except KeyError as exc:
        raise ValueError(f"unknown key: {key}") from exc


@dataclass(frozen=True)
class ActionRequest:
    action: Action
    source: ActionSource
    occurred_at: datetime
    event_id: UUID

    @classmethod
    def create(
        cls,
        action: Action,
        source: ActionSource,
        *,
        occurred_at: Optional[datetime] = None,
        event_id: Optional[UUID] = None,
    ) -> "ActionRequest":
        return cls(
            action=action,
            source=source,
            occurred_at=require_aware_utc(
                occurred_at or datetime.now(timezone.utc)
            ),
            event_id=event_id or uuid4(),
        )
