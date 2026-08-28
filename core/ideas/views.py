import logging
import time

from rest_framework import permissions, status
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import (
    ChannelLogoUploadSerializer,
    CronRefreshIdeasSerializer,
    CreatorImageUploadSerializer,
    GeneratePackageSerializer,
    GenerateScriptSerializer,
    ResponseContentPackageJobSerializer,
    ResponseChannelLogoUploadSerializer,
    ResponseCreatorImageUploadSerializer,
    ResponseIdeaCandidateSerializer,
    ResponseSavedPackageSerializer,
    ResponseThumbnailPreparationSerializer,
    ThumbnailPreparationSerializer,
    TrendingIdeaQuerySerializer,
    YouTubeIntentResearchSerializer,
)
from .services import (
    IdeaCronConfigurationError,
    create_content_package_job,
    create_or_reuse_research_job,
    create_script_job,
    get_content_package_job,
    get_content_package_history,
    get_active_idea,
    get_active_ideas,
    mark_content_package_job_dispatched,
    mark_content_package_job_queue_failed,
    prepare_thumbnail_from_intent,
    verify_idea_cron_secret,
    upload_channel_logo,
    upload_creator_image,
)
from .tasks import (
    generate_content_package_task,
    generate_content_script_task,
    generate_youtube_intent_task,
    refresh_all_ideas_task,
)
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


class IdeaDetailAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, idea_id):
        idea = get_active_idea(idea_id=idea_id)
        response_serializer = ResponseIdeaCandidateSerializer(idea)
        return Response(
            {
                "message": "idea retrieved successfully",
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
            task = refresh_all_ideas_task.apply_async(
                kwargs=serializer.validated_data,
                retry=False,
            )
        except Exception:
            logger.exception("ideas.cron.dispatch_failed")
            return Response(
                {"message": "Idea refresh could not be scheduled."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response(
            {
                "message": "scheduled idea refresh started",
                "data": {
                    "region_code": serializer.validated_data["region_code"],
                    "limit": serializer.validated_data["limit"],
                    "task_id": task.id,
                },
            },
            status=status.HTTP_202_ACCEPTED,
        )


class YouTubeIntentResearchAPIView(APIView):
    permission_classes = [HasStarterPermission]

    def post(self, request):
        serializer = YouTubeIntentResearchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            job, should_dispatch = create_or_reuse_research_job(
                user=request.user,
                request_payload=serializer.validated_data,
            )
            if should_dispatch:
                try:
                    task = generate_youtube_intent_task.apply_async(
                        args=[str(job.id)],
                        retry=False,
                    )
                except Exception:
                    mark_content_package_job_queue_failed(job_id=job.id)
                    logger.exception(
                        "ideas.research_job.dispatch_failed job_id=%s", job.id
                    )
                    return Response(
                        {"message": "YouTube research is temporarily unavailable."},
                        status=status.HTTP_503_SERVICE_UNAVAILABLE,
                    )
                mark_content_package_job_dispatched(
                    job_id=job.id,
                    task_id=task.id,
                )
                job.refresh_from_db()

            response_serializer = ResponseContentPackageJobSerializer(job)
            return Response(
                {
                    "message": "youtube intent research started",
                    "data": response_serializer.data,
                },
                status=status.HTTP_202_ACCEPTED,
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


class GenerateScriptAPIView(APIView):
    permission_classes = [HasCreatorPermission]

    def post(self, request):
        serializer = GenerateScriptSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            job = create_script_job(
                user=request.user,
                request_payload=serializer.validated_data,
            )
            try:
                task = generate_content_script_task.apply_async(
                    args=[str(job.id)],
                    retry=False,
                )
            except Exception:
                mark_content_package_job_queue_failed(job_id=job.id)
                logger.exception("ideas.script_job.dispatch_failed job_id=%s", job.id)
                return Response(
                    {"message": "Script generation is temporarily unavailable."},
                    status=status.HTTP_503_SERVICE_UNAVAILABLE,
                )

            mark_content_package_job_dispatched(job_id=job.id, task_id=task.id)
            job.refresh_from_db()
            response_serializer = ResponseContentPackageJobSerializer(job)
            return Response(
                {
                    "message": "script generation started",
                    "data": response_serializer.data,
                },
                status=status.HTTP_202_ACCEPTED,
            )
        except ValidationError as exc:
            raise exc
        except Exception as exc:
            logger.exception("ideas.script.unexpected_failure")
            return Response(
                {
                    "message": "Failed to start script generation.",
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


class CreatorImageUploadAPIView(APIView):
    permission_classes = [HasCreatorPermission]
    parser_classes = [MultiPartParser]

    def post(self, request):
        serializer = CreatorImageUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        asset = upload_creator_image(
            user=request.user,
            image_file=serializer.validated_data["image"],
        )
        response_serializer = ResponseCreatorImageUploadSerializer(asset)
        return Response(
            {
                "message": "creator image uploaded successfully",
                "data": response_serializer.data,
            },
            status=status.HTTP_201_CREATED,
        )


class ChannelLogoUploadAPIView(APIView):
    permission_classes = [HasCreatorPermission]
    parser_classes = [MultiPartParser]

    def post(self, request):
        serializer = ChannelLogoUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        asset = upload_channel_logo(
            user=request.user,
            image_file=serializer.validated_data["image"],
        )
        response_serializer = ResponseChannelLogoUploadSerializer(asset)
        return Response(
            {
                "message": "channel logo uploaded successfully",
                "data": response_serializer.data,
            },
            status=status.HTTP_201_CREATED,
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
    # Starter users can create Research jobs; ownership checks in the service
    # still prevent access to another user's package or script jobs.
    permission_classes = [HasStarterPermission]

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


class PackageHistoryAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        packages = get_content_package_history(user=request.user)
        response_serializer = ResponseSavedPackageSerializer(packages, many=True)
        return Response(
            {
                "message": "package history retrieved successfully",
                "data": response_serializer.data,
            },
            status=status.HTTP_200_OK,
        )
