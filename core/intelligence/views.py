from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from .creator_services import get_dna, update_dna
from .generation_services import generate_ideas
from .serializers import (
    AnalyzeCreatorSerializer,
    DNAResponseSerializer,
    GenerateIdeasSerializer,
    IdeasResponseSerializer,
    PoolResponseSerializer,
    UpdateDNASerializer,
)
from .tasks import queue_creator_analysis, queue_pool_refresh


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
        dna = get_dna(user_id=request.user.pk)
        if not dna.niche_pool_id:
            raise NotFound("Confirm Channel DNA to select a niche pool.")
        return Response({"data": PoolResponseSerializer(dna.niche_pool).data})


class GenerateIdeasAPIView(APIView):
    def post(self, request):
        serializer = GenerateIdeasSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = generate_ideas(user_id=request.user.pk, **serializer.validated_data)
        return Response({"data": IdeasResponseSerializer(result).data}, status=201)
