from django.urls import path

from .views import (
    ContentPackageJobDetailAPIView,
    CronRefreshIdeasAPIView,
    CreatorImageUploadAPIView,
    GeneratePackageAPIView,
    GenerateScriptAPIView,
    IdeaDetailAPIView,
    ThumbnailPreparationAPIView,
    TrendingIdeasAPIView,
    YouTubeIntentResearchAPIView,
)


urlpatterns = [
    path(
        "internal/ideas/refresh/",
        CronRefreshIdeasAPIView.as_view(),
        name="ideas-cron-refresh",
    ),
    path("ideas/", TrendingIdeasAPIView.as_view(), name="ideas-list"),
    path("ideas/<int:idea_id>/", IdeaDetailAPIView.as_view(), name="ideas-detail"),
    path("ideas/trending/", TrendingIdeasAPIView.as_view(), name="ideas-trending"),
    path(
        "ideas/youtube-intent/",
        YouTubeIntentResearchAPIView.as_view(),
        name="ideas-youtube-intent",
    ),
    path(
        "ideas/thumbnail-preparation/",
        ThumbnailPreparationAPIView.as_view(),
        name="ideas-thumbnail-preparation",
    ),
    path(
        "ideas/creator-image/",
        CreatorImageUploadAPIView.as_view(),
        name="ideas-creator-image-upload",
    ),
    path(
        "ideas/generate-package/",
        GeneratePackageAPIView.as_view(),
        name="ideas-generate-package",
    ),
    path(
        "ideas/generate-script/",
        GenerateScriptAPIView.as_view(),
        name="ideas-generate-script",
    ),
    path(
        "ideas/generation-jobs/<uuid:job_id>/",
        ContentPackageJobDetailAPIView.as_view(),
        name="ideas-generation-job-detail",
    ),
]
