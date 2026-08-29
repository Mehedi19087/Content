from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse
from rest_framework import permissions, status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import (
    AnalyzeYouTubeChannelSerializer,
    ResponseYouTubeAnalysisSerializer,
    ResponseYouTubeChannelSerializer,
    YouTubeCallbackSerializer,
)
from .services import (
    analyze_youtube_channel,
    build_youtube_connect_url,
    connect_youtube_channel,
    disconnect_youtube_channel,
    get_youtube_analysis,
    get_youtube_channel,
)
from users.permissions import HasProPermission


class YouTubeConnectAPIView(APIView):
    permission_classes = [HasProPermission]

    def get(self, request):
        try:
            auth_url = build_youtube_connect_url(
                user_id=request.user.id,
                redirect_uri=get_youtube_redirect_uri(request),
            )
            return Response(
                {
                    "message": "youtube connection URL generated successfully",
                    "data": {"auth_url": auth_url},
                },
                status=status.HTTP_200_OK,
            )
        except Exception:
            return Response(
                {"message": "Failed to start YouTube connection."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class YouTubeCallbackAPIView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def get(self, request):
        if request.query_params.get("error"):
            return youtube_callback_error_response(
                message="YouTube authorization was cancelled or denied."
            )

        serializer = YouTubeCallbackSerializer(data=request.query_params)

        try:
            serializer.is_valid(raise_exception=True)
            channel = connect_youtube_channel(
                **serializer.validated_data,
                redirect_uri=get_youtube_redirect_uri(request),
            )
        except ValidationError as exc:
            if settings.FRONTEND_YOUTUBE_REDIRECT_URL:
                return youtube_callback_error_response(
                    message="YouTube authorization could not be completed."
                )
            raise exc
        except Exception:
            if settings.FRONTEND_YOUTUBE_REDIRECT_URL:
                return youtube_callback_error_response(
                    message="YouTube authorization could not be completed."
                )
            return Response(
                {"message": "Failed to connect YouTube channel."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        if settings.FRONTEND_YOUTUBE_REDIRECT_URL:
            return redirect(
                add_query_parameters(
                    settings.FRONTEND_YOUTUBE_REDIRECT_URL,
                    {"status": "connected"},
                )
            )

        response_serializer = ResponseYouTubeChannelSerializer(channel)
        return Response(
            {
                "message": "youtube channel connected successfully",
                "data": response_serializer.data,
            },
            status=status.HTTP_200_OK,
        )


class YouTubeChannelAPIView(APIView):
    permission_classes = [HasProPermission]

    def get(self, request):
        channel = get_youtube_channel(user_id=request.user.id)
        serializer = ResponseYouTubeChannelSerializer(channel)
        return Response(
            {
                "message": "youtube channel retrieved successfully",
                "data": serializer.data,
            },
            status=status.HTTP_200_OK,
        )


class AnalyzeYouTubeChannelAPIView(APIView):
    permission_classes = [HasProPermission]

    def post(self, request):
        serializer = AnalyzeYouTubeChannelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            analysis, cached = analyze_youtube_channel(user_id=request.user.id)
            response_serializer = ResponseYouTubeAnalysisSerializer(analysis)
            data = dict(response_serializer.data)
            data["cached"] = cached
            return Response(
                {
                    "message": (
                        "youtube channel analysis retrieved successfully"
                        if cached
                        else "youtube channel analyzed successfully"
                    ),
                    "data": data,
                },
                status=status.HTTP_200_OK,
            )
        except ValidationError as exc:
            raise exc
        except Exception:
            return Response(
                {"message": "Failed to analyze YouTube channel."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class YouTubeAnalysisAPIView(APIView):
    permission_classes = [HasProPermission]

    def get(self, request):
        analysis = get_youtube_analysis(user_id=request.user.id)
        serializer = ResponseYouTubeAnalysisSerializer(analysis)
        return Response(
            {
                "message": "youtube channel analysis retrieved successfully",
                "data": serializer.data,
            },
            status=status.HTTP_200_OK,
        )


class YouTubeDisconnectAPIView(APIView):
    permission_classes = [HasProPermission]

    def delete(self, request):
        disconnect_youtube_channel(user_id=request.user.id)
        return Response(
            {"message": "youtube channel disconnected successfully"},
            status=status.HTTP_200_OK,
        )


def get_youtube_redirect_uri(request) -> str:
    if settings.YOUTUBE_OAUTH_REDIRECT_URI:
        return settings.YOUTUBE_OAUTH_REDIRECT_URI
    return request.build_absolute_uri(reverse("youtube-callback"))


def add_query_parameters(url: str, params: dict[str, str]) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query))
    query.update(params)
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
    )


def youtube_callback_error_response(*, message: str):
    if settings.FRONTEND_YOUTUBE_REDIRECT_URL:
        return redirect(
            add_query_parameters(
                settings.FRONTEND_YOUTUBE_REDIRECT_URL,
                {"status": "error"},
            )
        )
    return Response(
        {"message": message},
        status=status.HTTP_400_BAD_REQUEST,
    )
