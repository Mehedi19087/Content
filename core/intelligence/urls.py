from django.urls import path

from .views import (
    ChannelDNAAPIView,
    CreatorAnalysisAPIView,
    GenerateIdeasAPIView,
    NichePoolAPIView,
)


urlpatterns = [
    path("analyze/", CreatorAnalysisAPIView.as_view(), name="intelligence-analyze"),
    path("dna/", ChannelDNAAPIView.as_view(), name="intelligence-dna"),
    path("niche/", NichePoolAPIView.as_view(), name="intelligence-niche"),
    path("ideas/", GenerateIdeasAPIView.as_view(), name="intelligence-ideas"),
]
