from django.urls import path

from .views import (
    GeneratePackageAPIView,
    RefreshIdeasAPIView,
    ThumbnailPreparationAPIView,
    TrendingIdeasAPIView,
    YouTubeIntentResearchAPIView,
)


urlpatterns = [
    path("ideas/trending/", TrendingIdeasAPIView.as_view(), name="ideas-trending"),
    path("ideas/refresh/", RefreshIdeasAPIView.as_view(), name="ideas-refresh"),
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
