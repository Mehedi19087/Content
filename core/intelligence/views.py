from rest_framework.response import Response
from rest_framework.views import APIView

from .creator_services import get_dna, update_dna
from .feed_services import daily_ideas
from .serializers import (
    AnalyzeCreatorSerializer,
    DNAResponseSerializer,
    GenerateIdeasSerializer,
    IdeasResponseSerializer,
    PoolResponseSerializer,
    UpdateDNASerializer,
)
from .tasks import queue_creator_analysis, queue_pool_refresh
from .workflow_services import get_niche_pool


class CreatorAnalysisAPIView(APIView):
    def post(self, request):
        serializer = AnalyzeCreatorSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        dna = queue_creator_analysis(user_id=request.user.pk)
        return Response({"data": DNAResponseSerializer(dna).data}, status=202)


class ChannelDNAAPIView(APIView):
    def get(self, request):
        return Response({"data": DNAResponseSerializer(
            get_dna(user_id=request.user.pk)
        ).data})

    def patch(self, request):
        serializer = UpdateDNASerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        dna = update_dna(user_id=request.user.pk, **serializer.validated_data)
        refresh_status = "not_requested"
        if dna.confirmed and dna.niche_pool_id:
            refresh_status = queue_pool_refresh(dna.niche_pool_id)
        return Response({
            "data": DNAResponseSerializer(dna).data,
            "refresh_status": refresh_status,
        })


class NichePoolAPIView(APIView):
    def get(self, request):
        pool = get_niche_pool(user_id=request.user.pk)
        return Response({"data": PoolResponseSerializer(pool).data})


class GenerateIdeasAPIView(APIView):
    def get(self, request):
        result = daily_ideas(user_id=request.user.pk)
        return Response({"data": IdeasResponseSerializer(result).data})

    def post(self, request):
        # Legacy clients cannot bypass the daily cache by changing count.
        serializer = GenerateIdeasSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return self.get(request)
