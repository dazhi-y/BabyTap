from django.contrib import admin

from .models import BabyTapEvent


@admin.register(BabyTapEvent)
class BabyTapEventAdmin(admin.ModelAdmin):
    list_display = ("event_id", "kind", "child", "state", "created_at")
    list_filter = ("kind", "state")
    search_fields = ("event_id", "child__first_name", "child__last_name")
    readonly_fields = ("payload_hash", "records", "created_at", "undone_at")

