from rest_framework import mixins, status, viewsets
from rest_framework.exceptions import APIException
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import BabyTapEvent
from .serializers import BabyTapEventCreateSerializer, BabyTapEventSerializer
from .services import EventConflict, create_event, undo_event


class Conflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "conflict"


class BabyTapEventViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = (IsAuthenticated,)
    serializer_class = BabyTapEventSerializer
    lookup_field = "event_id"

    def get_queryset(self):
        queryset = BabyTapEvent.objects.select_related("child", "created_by")
        if self.request.user.is_superuser:
            return queryset
        return queryset.filter(created_by=self.request.user)

    def create(self, request, *args, **kwargs):
        serializer = BabyTapEventCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            event, created = create_event(serializer.validated_data, request.user)
        except EventConflict as error:
            raise Conflict(str(error)) from error
        output = self.get_serializer(event)
        return Response(
            output.data,
            status=(status.HTTP_201_CREATED if created else status.HTTP_200_OK),
        )

    def destroy(self, request, *args, **kwargs):
        event, undone = undo_event(kwargs[self.lookup_field], request.user)
        if event is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        output = self.get_serializer(event)
        data = dict(output.data)
        data["undone_now"] = undone
        return Response(data, status=status.HTTP_200_OK)

