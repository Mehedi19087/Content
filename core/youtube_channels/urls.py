from django.urls import path

from .views import (
    AnalyzeYouTubeChannelAPIView,
    YouTubeAnalysisAPIView,
    YouTubeCallbackAPIView,
    YouTubeChannelAPIView,
    YouTubeConnectAPIView,
    YouTubeDisconnectAPIView,
)


urlpatterns = [
    path("youtube/connect/", YouTubeConnectAPIView.as_view(), name="youtube-connect"),
    path(
        "youtube/callback/",
        YouTubeCallbackAPIView.as_view(),
        name="youtube-callback",
    ),
    path("youtube/channel/", YouTubeChannelAPIView.as_view(), name="youtube-channel"),
    path(
        "youtube/analyze/",
        AnalyzeYouTubeChannelAPIView.as_view(),
        name="youtube-analyze",
    ),
    path(
        "youtube/analysis/",
        YouTubeAnalysisAPIView.as_view(),
        name="youtube-analysis",
    ),
    path(
        "youtube/disconnect/",
        YouTubeDisconnectAPIView.as_view(),
        name="youtube-disconnect",
    ),
]
