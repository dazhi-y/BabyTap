from rest_framework import serializers

from core.models import Child

from .models import BabyTapEvent


class TimeRangeSerializer(serializers.Serializer):
    start = serializers.DateTimeField()
    end = serializers.DateTimeField()

    def validate(self, attrs):
        if attrs["start"] > attrs["end"]:
            raise serializers.ValidationError("Start time must come before end time.")
        return attrs


class BreastfeedingSegmentSerializer(TimeRangeSerializer):
    side = serializers.ChoiceField(choices=("left", "right"))


class BreastfeedingDataSerializer(serializers.Serializer):
    segments = BreastfeedingSegmentSerializer(many=True, min_length=1, max_length=2)
    notes = serializers.CharField(required=False, allow_blank=True)

    def validate_segments(self, segments):
        sides = [segment["side"] for segment in segments]
        if len(sides) != len(set(sides)):
            raise serializers.ValidationError("Each breast side may occur only once.")
        for previous, current in zip(segments, segments[1:]):
            if current["start"] < previous["end"]:
                raise serializers.ValidationError(
                    "Breastfeeding segments must follow their array order."
                )
        return segments


class BottleDataSerializer(TimeRangeSerializer):
    amount = serializers.FloatField(min_value=0.01)
    type = serializers.ChoiceField(
        choices=("breast milk", "formula", "fortified breast milk"),
        default="formula",
    )
    notes = serializers.CharField(required=False, allow_blank=True)


class SolidFoodDataSerializer(TimeRangeSerializer):
    amount = serializers.FloatField(required=False, allow_null=True, min_value=0)
    method = serializers.ChoiceField(
        choices=("parent fed", "self fed"), default="parent fed"
    )
    notes = serializers.CharField(required=False, allow_blank=True)


class DiaperDataSerializer(serializers.Serializer):
    wet = serializers.BooleanField()
    solid = serializers.BooleanField()
    color = serializers.ChoiceField(
        choices=(
            "black",
            "brown",
            "gray",
            "green",
            "orange",
            "red",
            "white",
            "yellow",
        ),
        required=False,
        allow_blank=True,
    )
    amount = serializers.FloatField(required=False, allow_null=True, min_value=0)
    notes = serializers.CharField(required=False, allow_blank=True)

class SleepDataSerializer(TimeRangeSerializer):
    nap = serializers.BooleanField(required=False, allow_null=True)
    notes = serializers.CharField(required=False, allow_blank=True)


DATA_SERIALIZERS = {
    BabyTapEvent.Kind.BREASTFEEDING: BreastfeedingDataSerializer,
    BabyTapEvent.Kind.BOTTLE: BottleDataSerializer,
    BabyTapEvent.Kind.SOLID_FOOD: SolidFoodDataSerializer,
    BabyTapEvent.Kind.DIAPER: DiaperDataSerializer,
    BabyTapEvent.Kind.SLEEP: SleepDataSerializer,
}


class BabyTapEventCreateSerializer(serializers.Serializer):
    event_id = serializers.UUIDField()
    child = serializers.PrimaryKeyRelatedField(queryset=Child.objects.all())
    kind = serializers.ChoiceField(choices=BabyTapEvent.Kind.choices)
    occurred_at = serializers.DateTimeField()
    data = serializers.JSONField()

    def validate(self, attrs):
        data_serializer = DATA_SERIALIZERS[attrs["kind"]](data=attrs["data"])
        data_serializer.is_valid(raise_exception=True)
        attrs["data"] = data_serializer.validated_data
        return attrs


class BabyTapEventSerializer(serializers.ModelSerializer):
    event_id = serializers.UUIDField(read_only=True)
    child = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = BabyTapEvent
        fields = (
            "event_id",
            "child",
            "kind",
            "occurred_at",
            "payload",
            "records",
            "state",
            "created_at",
            "undone_at",
        )
