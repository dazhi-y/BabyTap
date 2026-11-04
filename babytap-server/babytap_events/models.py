import uuid

from django.conf import settings
from django.db import models


class BabyTapEvent(models.Model):
    class Kind(models.TextChoices):
        BREASTFEEDING = "breastfeeding", "Breastfeeding"
        BOTTLE = "bottle", "Bottle"
        SOLID_FOOD = "solid_food", "Solid food"
        DIAPER = "diaper", "Diaper"
        SLEEP = "sleep", "Sleep"

    class State(models.TextChoices):
        ACTIVE = "active", "Active"
        UNDONE = "undone", "Undone"

    event_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    child = models.ForeignKey(
        "core.Child", on_delete=models.CASCADE, related_name="babytap_events"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="babytap_events",
    )
    kind = models.CharField(max_length=32, choices=Kind.choices)
    occurred_at = models.DateTimeField()
    payload = models.JSONField()
    payload_hash = models.CharField(max_length=64, editable=False)
    records = models.JSONField(default=list)
    state = models.CharField(
        max_length=16, choices=State.choices, default=State.ACTIVE
    )
    created_at = models.DateTimeField(auto_now_add=True)
    undone_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.kind}: {self.event_id}"

