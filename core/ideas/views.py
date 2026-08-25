import logging
import time

from rest_framework import permissions, status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import (
    CronRefreshIdeasSerializer,
    CronRefreshSummarySerializer,
    GeneratePackageSerializer,
    ResponseContentPackageJobSerializer,
    ResponseIdeaCandidateSerializer,
    ResponseThumbnailPreparationSerializer,
    ResponseYouTubeIntentResearchSerializer,
    ThumbnailPreparationSerializer,
    TrendingIdeaQuerySerializer,
    YouTubeIntentResearchSerializer,
)
from .services import (
    IdeaCronConfigurationError,
    create_content_package_job,
    get_content_package_job,
    get_active_ideas,
    mark_content_package_job_dispatched,
    mark_content_package_job_queue_failed,
    prepare_thumbnail_from_intent,
    refresh_all_ideas_for_cron,
    research_youtube_intent_for_idea,
    verify_idea_cron_secret,
)
from .tasks import generate_content_package_task
from users.permissions import (
    HasCreatorPermission,
    HasProPermission,
    HasStarterPermission,
)


logger = logging.getLogger(__name__)
performance_logger = logging.getLogger("ideas.performance")


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


class CronRefreshIdeasAPIView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        try:
            verify_idea_cron_secret(request.headers.get("X-Cron-Secret"))
        except IdeaCronConfigurationError:
            return Response(
                {"message": "Idea cron is not configured."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        serializer = CronRefreshIdeasSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            summary = refresh_all_ideas_for_cron(**serializer.validated_data)
        except ValidationError:
            raise
        except Exception:
            logger.exception("ideas.cron.unexpected_failure")
            return Response(
                {"message": "Scheduled idea refresh failed unexpectedly."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        response_serializer = CronRefreshSummarySerializer(summary)
        response_status = (
            status.HTTP_200_OK
            if summary["failed"] == 0
            else status.HTTP_503_SERVICE_UNAVAILABLE
        )
        return Response(
            {
                "message": (
                    "scheduled idea refresh completed successfully"
                    if summary["failed"] == 0
                    else "scheduled idea refresh completed with failures"
                ),
                "data": response_serializer.data,
            },
            status=response_status,
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
            logger.exception("ideas.research.unexpected_failure")
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
            logger.exception("ideas.thumbnail_preparation.unexpected_failure")
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
        started_at = time.perf_counter()
        outcome = "failed"
        try:
            serializer = GeneratePackageSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            job = create_content_package_job(
                user=request.user,
                request_payload=serializer.validated_data,
            )
            try:
                task = generate_content_package_task.apply_async(
                    args=[str(job.id)],
                    retry=False,
                )
            except Exception:
                mark_content_package_job_queue_failed(job_id=job.id)
                logger.exception("ideas.package_job.dispatch_failed job_id=%s", job.id)
                return Response(
                    {"message": "Content package generation is temporarily unavailable."},
                    status=status.HTTP_503_SERVICE_UNAVAILABLE,
                )

            mark_content_package_job_dispatched(job_id=job.id, task_id=task.id)
            job.refresh_from_db()
            response_serializer = ResponseContentPackageJobSerializer(job)
            outcome = "succeeded"
            return Response(
                {
                    "message": "content package generation started",
                    "data": response_serializer.data,
                },
                status=status.HTTP_202_ACCEPTED,
            )
        except ValidationError as exc:
            raise exc
        except Exception as exc:
            logger.exception("ideas.package.unexpected_failure")
            return Response(
                {
                    "message": "Failed to generate content package due to an internal server error.",
                    "detail": str(exc),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        finally:
            performance_logger.info(
                "ideas.request_timing endpoint=generate_package outcome=%s "
                "duration_seconds=%.3f",
                outcome,
                time.perf_counter() - started_at,
            )


class ContentPackageJobDetailAPIView(APIView):
    permission_classes = [HasCreatorPermission]

    def get(self, request, job_id):
        job = get_content_package_job(user=request.user, job_id=job_id)
        response_serializer = ResponseContentPackageJobSerializer(job)
        return Response(
            {
                "message": "content package generation status retrieved successfully",
                "data": response_serializer.data,
            },
            status=status.HTTP_200_OK,
        )
