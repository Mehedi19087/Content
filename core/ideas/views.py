from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import (
    GeneratePackageSerializer,
    RefreshIdeasSerializer,
    ResponseGeneratePackageSerializer,
    ResponseIdeaCandidateSerializer,
    ResponseThumbnailPreparationSerializer,
    ResponseYouTubeIntentResearchSerializer,
    ThumbnailPreparationSerializer,
    TrendingIdeaQuerySerializer,
    YouTubeIntentResearchSerializer,
)
from .services import (
    generate_content_package,
    get_active_ideas,
    prepare_thumbnail_from_intent,
    refresh_ideas_for_category,
    research_youtube_intent_for_idea,
)
from rest_framework import permissions
from users.permissions import (
    HasCreatorPermission,
    HasProPermission,
    HasStarterPermission,
)


class TrendingIdeasAPIView(APIView):
    # Trending ideas are visible to any authenticated user (Free tier included).
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        serializer = TrendingIdeaQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        ideas = get_active_ideas(**serializer.validated_data)
        response_serializer = ResponseIdeaCandidateSerializer(ideas, many=True)

        return Response(
            {
                "message": "trending ideas retrieved successfully",
                "data": response_serializer.data,
            },
            status=status.HTTP_200_OK,
        )


class RefreshIdeasAPIView(APIView):
    permission_classes = [HasStarterPermission]

    def post(self, request):
        serializer = RefreshIdeasSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            ideas = refresh_ideas_for_category(**serializer.validated_data)
            response_serializer = ResponseIdeaCandidateSerializer(ideas, many=True)
            return Response(
                {
                    "message": "trending ideas refreshed successfully",
                    "data": response_serializer.data,
                },
                status=status.HTTP_201_CREATED,
            )
        except ValidationError as exc:
            raise exc
        except Exception as exc:
            return Response(
                {
                    "message": "Failed to refresh ideas due to an internal server error.",
                    "detail": str(exc),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class YouTubeIntentResearchAPIView(APIView):
    permission_classes = [HasStarterPermission]

    def post(self, request):
        serializer = YouTubeIntentResearchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            research = research_youtube_intent_for_idea(**serializer.validated_data)
            response_serializer = ResponseYouTubeIntentResearchSerializer(research)
            return Response(
                {
                    "message": "youtube intent research generated successfully",
                    "data": response_serializer.data,
                },
                status=status.HTTP_200_OK,
            )
        except ValidationError as exc:
            raise exc
        except Exception as exc:
            return Response(
                {
                    "message": "Failed to research YouTube intent due to an internal server error.",
                    "detail": str(exc),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class ThumbnailPreparationAPIView(APIView):
    permission_classes = [HasProPermission]

    def post(self, request):
        serializer = ThumbnailPreparationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            preparation = prepare_thumbnail_from_intent(**serializer.validated_data)
            response_serializer = ResponseThumbnailPreparationSerializer(preparation)
            return Response(
                {
                    "message": "thumbnail preparation generated successfully",
                    "data": response_serializer.data,
                },
                status=status.HTTP_200_OK,
            )
        except ValidationError as exc:
            raise exc
        except Exception as exc:
            return Response(
                {
                    "message": "Failed to prepare thumbnail due to an internal server error.",
                    "detail": str(exc),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class GeneratePackageAPIView(APIView):
    permission_classes = [HasCreatorPermission]

    def post(self, request):
        serializer = GeneratePackageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            package = generate_content_package(**serializer.validated_data)
            response_serializer = ResponseGeneratePackageSerializer(package)
            return Response(
                {
                    "message": "content package generated successfully",
                    "data": response_serializer.data,
                },
                status=status.HTTP_201_CREATED,
            )
        except ValidationError as exc:
            raise exc
        except Exception as exc:
            return Response(
                {
                    "message": "Failed to generate content package due to an internal server error.",
                    "detail": str(exc),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
