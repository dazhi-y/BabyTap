import datetime
import hashlib
import json

from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.utils import timezone

from core import models as core_models

from .models import BabyTapEvent


MODEL_BY_LABEL = {
    "feeding": core_models.Feeding,
    "diaper_change": core_models.DiaperChange,
    "sleep": core_models.Sleep,
}

ADD_PERMISSION_BY_KIND = {
    BabyTapEvent.Kind.BREASTFEEDING: "core.add_feeding",
    BabyTapEvent.Kind.BOTTLE: "core.add_feeding",
    BabyTapEvent.Kind.SOLID_FOOD: "core.add_feeding",
    BabyTapEvent.Kind.DIAPER: "core.add_diaperchange",
    BabyTapEvent.Kind.SLEEP: "core.add_sleep",
}


class EventConflict(Exception):
    pass


def _json_value(value):
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def canonical_payload(validated_data):
    return _json_value(
        {
            "event_id": str(validated_data["event_id"]),
            "child": validated_data["child"].pk,
            "kind": validated_data["kind"],
            "occurred_at": validated_data["occurred_at"],
            "data": validated_data["data"],
        }
    )


def payload_digest(payload):
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _save(model, label):
    model.full_clean()
    model.save()
    return {"model": label, "id": model.pk}


def _create_core_records(event):
    data = event.payload["data"]
    common = {"child": event.child, "notes": data.get("notes", "")}

    if event.kind == BabyTapEvent.Kind.BREASTFEEDING:
        return [
            _save(
                core_models.Feeding(
                    **common,
                    start=segment["start"],
                    end=segment["end"],
                    type="breast milk",
                    method=f'{segment["side"]} breast',
                ),
                "feeding",
            )
            for segment in data["segments"]
        ]

    if event.kind == BabyTapEvent.Kind.BOTTLE:
        return [
            _save(
                core_models.Feeding(
                    **common,
                    start=data["start"],
                    end=data["end"],
                    type=data["type"],
                    method="bottle",
                    amount=data["amount"],
                ),
                "feeding",
            )
        ]

    if event.kind == BabyTapEvent.Kind.SOLID_FOOD:
        return [
            _save(
                core_models.Feeding(
                    **common,
                    start=data["start"],
                    end=data["end"],
                    type="solid food",
                    method=data["method"],
                    amount=data.get("amount"),
                ),
                "feeding",
            )
        ]

    if event.kind == BabyTapEvent.Kind.DIAPER:
        return [
            _save(
                core_models.DiaperChange(
                    **common,
                    time=event.occurred_at,
                    wet=data["wet"],
                    solid=data["solid"],
                    color=data.get("color", ""),
                    amount=data.get("amount"),
                ),
                "diaper_change",
            )
        ]

    if event.kind == BabyTapEvent.Kind.SLEEP:
        sleep = core_models.Sleep(
            **common,
            start=data["start"],
            end=data["end"],
        )
        if "nap" in data:
            sleep.nap = data["nap"]
        return [_save(sleep, "sleep")]

    raise ValueError(f"Unsupported BabyTap event kind: {event.kind}")


def _existing_result(event, digest):
    if event.payload_hash != digest:
        raise EventConflict("event_id is already used with a different payload")
    if event.state == BabyTapEvent.State.UNDONE:
        raise EventConflict("event_id belongs to an event that was already undone")
    return event, False


def create_event(validated_data, user):
    permission = ADD_PERMISSION_BY_KIND[validated_data["kind"]]
    if not user.has_perm(permission):
        raise PermissionDenied(f"Missing permission: {permission}")

    payload = canonical_payload(validated_data)
    digest = payload_digest(payload)
    event_id = validated_data["event_id"]

    try:
        with transaction.atomic():
            existing = (
                BabyTapEvent.objects.select_for_update()
                .filter(event_id=event_id)
                .first()
            )
            if existing:
                return _existing_result(existing, digest)

            event = BabyTapEvent.objects.create(
                event_id=event_id,
                child=validated_data["child"],
                created_by=user,
                kind=validated_data["kind"],
                occurred_at=validated_data["occurred_at"],
                payload=payload,
                payload_hash=digest,
            )
            event.records = _create_core_records(event)
            event.save(update_fields=["records"])
            return event, True
    except IntegrityError as error:
        try:
            existing = BabyTapEvent.objects.get(event_id=event_id)
        except BabyTapEvent.DoesNotExist:
            raise error
        return _existing_result(existing, digest)


def undo_event(event_id, user):
    with transaction.atomic():
        event = (
            BabyTapEvent.objects.select_for_update()
            .filter(event_id=event_id)
            .first()
        )
        if event is None:
            # The desktop client can undo a local event whose original create
            # never reached the server. Treat that as an already-satisfied
            # delete instead of leaking DoesNotExist as HTTP 500.
            return None, False
        if event.state == BabyTapEvent.State.UNDONE:
            return event, False
        if event.created_by_id != user.pk and not user.is_superuser:
            raise PermissionDenied("Only the creator may undo this BabyTap event.")

        for reference in reversed(event.records):
            model = MODEL_BY_LABEL[reference["model"]]
            model.objects.filter(pk=reference["id"]).delete()

        event.state = BabyTapEvent.State.UNDONE
        event.undone_at = timezone.now()
        event.save(update_fields=["state", "undone_at"])
        return event, True
