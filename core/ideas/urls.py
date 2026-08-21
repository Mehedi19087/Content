from django.urls import path

from .views import (
    CronRefreshIdeasAPIView,
    GeneratePackageAPIView,
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
        "ideas/generate-package/",
        GeneratePackageAPIView.as_view(),
        name="ideas-generate-package",
    ),
]
