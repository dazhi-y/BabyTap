import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from core import models as core_models

from .models import BabyTapEvent
from .serializers import BabyTapEventCreateSerializer
from .services import create_event


def iso(minutes):
    return (timezone.now() - timezone.timedelta(minutes=minutes)).isoformat()


def event_payload(kind, data, event_id=None, occurred_minutes=1):
    return {
        "event_id": str(event_id or uuid.uuid4()),
        "child": 1,
        "kind": kind,
        "occurred_at": iso(occurred_minutes),
        "data": data,
    }


class BabyTapEventAPITests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="babytap-admin", password="test-password"
        )
        self.child = core_models.Child.objects.create(
            id=1, first_name="Test", birth_date=timezone.localdate()
        )
        self.client.force_authenticate(self.user)
        self.list_url = reverse("api:babytap-event-list")

    def test_breastfeeding_accepts_single_side_and_preserves_right_left_order(self):
        left_only = event_payload(
            "breastfeeding",
            {"segments": [{"side": "left", "start": iso(20), "end": iso(16)}]},
        )
        response = self.client.post(self.list_url, left_only, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(core_models.Feeding.objects.count(), 1)
        self.assertEqual(core_models.Feeding.objects.get().method, "left breast")

        core_models.Feeding.objects.all().delete()
        right_left = event_payload(
            "breastfeeding",
            {
                "segments": [
                    {"side": "right", "start": iso(15), "end": iso(11)},
                    {"side": "left", "start": iso(10), "end": iso(6)},
                ]
            },
        )
        response = self.client.post(self.list_url, right_left, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        record_ids = [record["id"] for record in response.data["records"]]
        methods = [core_models.Feeding.objects.get(pk=pk).method for pk in record_ids]
        self.assertEqual(methods, ["right breast", "left breast"])

    def test_same_event_is_idempotent_and_changed_payload_conflicts(self):
        event_id = uuid.uuid4()
        payload = event_payload(
            "bottle",
            {
                "start": iso(10),
                "end": iso(5),
                "amount": 120,
                "type": "formula",
            },
            event_id,
        )
        first = self.client.post(self.list_url, payload, format="json")
        second = self.client.post(self.list_url, payload, format="json")
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertEqual(core_models.Feeding.objects.count(), 1)
        self.assertEqual(BabyTapEvent.objects.count(), 1)

        payload["data"]["amount"] = 150
        conflict = self.client.post(self.list_url, payload, format="json")
        self.assertEqual(conflict.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(core_models.Feeding.objects.count(), 1)

    def test_maps_bottle_solid_diaper_and_sleep(self):
        cases = [
            event_payload(
                "bottle",
                {"start": iso(80), "end": iso(75), "amount": 90},
            ),
            event_payload(
                "solid_food",
                {
                    "start": iso(60),
                    "end": iso(55),
                    "amount": 30,
                    "method": "self fed",
                },
            ),
            event_payload("diaper", {"wet": True, "solid": False}),
            event_payload(
                "sleep", {"start": iso(40), "end": iso(20), "nap": True}
            ),
        ]
        for payload in cases:
            response = self.client.post(self.list_url, payload, format="json")
            self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)

        self.assertEqual(core_models.Feeding.objects.count(), 2)
        self.assertEqual(core_models.DiaperChange.objects.count(), 1)
        self.assertEqual(core_models.Sleep.objects.count(), 1)
        bottle = core_models.Feeding.objects.get(method="bottle")
        solid = core_models.Feeding.objects.get(type="solid food")
        self.assertEqual(bottle.type, "formula")
        self.assertEqual(bottle.amount, 90)
        self.assertEqual(solid.method, "self fed")

    def test_undo_deletes_the_whole_group_and_is_idempotent(self):
        payload = event_payload(
            "breastfeeding",
            {
                "segments": [
                    {"side": "left", "start": iso(15), "end": iso(11)},
                    {"side": "right", "start": iso(10), "end": iso(6)},
                ]
            },
        )
        created = self.client.post(self.list_url, payload, format="json")
        detail_url = reverse(
            "api:babytap-event-detail", kwargs={"event_id": created.data["event_id"]}
        )

        first = self.client.delete(detail_url)
        second = self.client.delete(detail_url)
        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertTrue(first.data["undone_now"])
        self.assertFalse(second.data["undone_now"])
        self.assertEqual(second.data["state"], BabyTapEvent.State.UNDONE)
        self.assertEqual(core_models.Feeding.objects.count(), 0)

        recreate = self.client.post(self.list_url, payload, format="json")
        self.assertEqual(recreate.status_code, status.HTTP_409_CONFLICT)

    def test_undo_missing_event_is_an_idempotent_no_content(self):
        detail_url = reverse(
            "api:babytap-event-detail", kwargs={"event_id": uuid.uuid4()}
        )

        response = self.client.delete(detail_url)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(BabyTapEvent.objects.count(), 0)

    def test_rejects_duplicate_side_and_out_of_order_segments(self):
        duplicate = event_payload(
            "breastfeeding",
            {
                "segments": [
                    {"side": "left", "start": iso(20), "end": iso(16)},
                    {"side": "left", "start": iso(15), "end": iso(10)},
                ]
            },
        )
        response = self.client.post(self.list_url, duplicate, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        out_of_order = event_payload(
            "breastfeeding",
            {
                "segments": [
                    {"side": "right", "start": iso(10), "end": iso(6)},
                    {"side": "left", "start": iso(20), "end": iso(16)},
                ]
            },
        )
        response = self.client.post(self.list_url, out_of_order, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(BabyTapEvent.objects.count(), 0)

    def test_requires_authentication(self):
        self.client.force_authenticate(user=None)
        response = self.client.post(
            self.list_url,
            event_payload("diaper", {"wet": True, "solid": False}),
            format="json",
        )
        self.assertIn(
            response.status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )

    def test_regular_user_needs_add_permission_and_may_undo_own_event(self):
        user = get_user_model().objects.create_user(username="caregiver")
        self.client.force_authenticate(user)
        payload = event_payload(
            "bottle",
            {"start": iso(10), "end": iso(5), "amount": 100},
        )

        forbidden = self.client.post(self.list_url, payload, format="json")
        self.assertEqual(forbidden.status_code, status.HTTP_403_FORBIDDEN)

        user.user_permissions.add(Permission.objects.get(codename="add_feeding"))
        user = get_user_model().objects.get(pk=user.pk)
        self.client.force_authenticate(user)
        created = self.client.post(self.list_url, payload, format="json")
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        detail_url = reverse(
            "api:babytap-event-detail", kwargs={"event_id": created.data["event_id"]}
        )
        undone = self.client.delete(detail_url)
        self.assertEqual(undone.status_code, status.HTTP_200_OK)
        self.assertEqual(undone.data["state"], BabyTapEvent.State.UNDONE)


class BabyTapEventTransactionTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="transaction-admin", password="test-password"
        )
        core_models.Child.objects.create(
            id=1, first_name="Test", birth_date=timezone.localdate()
        )

    def test_second_record_failure_rolls_back_event_and_first_record(self):
        raw = event_payload(
            "breastfeeding",
            {
                "segments": [
                    {"side": "left", "start": iso(15), "end": iso(11)},
                    {"side": "right", "start": iso(10), "end": iso(6)},
                ]
            },
        )
        serializer = BabyTapEventCreateSerializer(data=raw)
        serializer.is_valid(raise_exception=True)

        original_save = core_models.Feeding.save
        calls = 0

        def fail_on_second_save(instance, *args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise IntegrityError("simulated database failure")
            return original_save(instance, *args, **kwargs)

        with patch.object(core_models.Feeding, "save", new=fail_on_second_save):
            with self.assertRaisesRegex(IntegrityError, "simulated database failure"):
                create_event(serializer.validated_data, self.user)

        self.assertEqual(BabyTapEvent.objects.count(), 0)
        self.assertEqual(core_models.Feeding.objects.count(), 0)
