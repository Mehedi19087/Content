from datetime import date, datetime, timedelta, timezone as datetime_timezone
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from .models import YouTubeChannel, YouTubeChannelAnalysis
from .services import (
    analyze_youtube_channel,
    connect_youtube_channel,
    decrypt_refresh_token,
    disconnect_youtube_channel,
    select_analysis_videos,
)
from .youtube_client import ConnectedYouTubeClient, YOUTUBE_SCOPES


FIXED_NOW = datetime(2026, 7, 20, 12, 0, tzinfo=datetime_timezone.utc)


def channel_payload():
    return {
        "id": "UC-test-channel",
        "snippet": {
            "title": "MVP Creator",
            "thumbnails": {"high": {"url": "https://example.com/channel.jpg"}},
        },
        "contentDetails": {"relatedPlaylists": {"uploads": "UU-test-channel"}},
        "statistics": {
            "subscriberCount": "1200",
            "videoCount": "42",
            "viewCount": "85000",
        },
    }


def upload_payloads(count=12):
    return [
        {
            "video_id": f"video-{index}",
            "published_at": (
                FIXED_NOW - timedelta(days=index * 10 + 2)
            ).isoformat().replace("+00:00", "Z"),
        }
        for index in range(count)
    ]


def video_payloads(count=12):
    return [
        {
            "id": f"video-{index}",
            "snippet": {
                "title": f"AI automation workflow {index}",
                "description": "A practical AI automation tutorial.",
                "tags": ["AI automation", "workflow"],
                "publishedAt": (
                    FIXED_NOW - timedelta(days=index * 10 + 2)
                ).isoformat().replace("+00:00", "Z"),
                "thumbnails": {
                    "high": {"url": f"https://example.com/video-{index}.jpg"}
                },
            },
            "contentDetails": {"duration": "PT8M30S"},
            "statistics": {
                "viewCount": str(10000 - index * 300),
                "likeCount": str(500 - index * 10),
                "commentCount": str(100 - index),
            },
            "status": {"privacyStatus": "public"},
        }
        for index in range(count)
    ]


def analytics_payloads(count=12):
    return [
        {
            "video": f"video-{index}",
            "views": 9000 - index * 300,
            "estimatedMinutesWatched": 40000 - index * 1000,
            "averageViewDuration": 250,
            "averageViewPercentage": 52 if index < 6 else 22,
            "likes": 400 - index * 10,
            "comments": 80 - index,
            "shares": 30,
            "subscribersGained": 90 if index < 6 else 10,
            "subscribersLost": 2,
        }
        for index in range(count)
    ]


class FakeYouTubeClient:
    def __init__(self):
        self.revoked_token = None
        self.analytics_calls = []

    def build_authorization_url(self, *, state, redirect_uri):
        return f"https://accounts.example/authorize?state={state}&redirect_uri={redirect_uri}"

    def exchange_code(self, *, code, redirect_uri):
        return {
            "access_token": "google-access-token",
            "refresh_token": "google-refresh-token",
            "scope": " ".join(YOUTUBE_SCOPES),
        }

    def refresh_access_token(self, *, refresh_token):
        assert refresh_token == "google-refresh-token"
        return "refreshed-access-token"

    def revoke_token(self, *, token):
        self.revoked_token = token

    def get_my_channel(self, *, access_token):
        return channel_payload()

    def get_upload_video_ids(self, **kwargs):
        return upload_payloads()

    def get_videos(self, *, access_token, video_ids):
        selected = set(video_ids)
        return [item for item in video_payloads() if item["id"] in selected]

    def query_analytics(self, **kwargs):
        self.analytics_calls.append(kwargs)
        if kwargs.get("dimensions") == ["video"]:
            return analytics_payloads()
        return [
            {
                "day": "2026-07-18",
                "views": 1200,
                "estimatedMinutesWatched": 5000,
                "subscribersGained": 12,
                "subscribersLost": 1,
            }
        ]


class FakeTextGenerationClient:
    def generate_json(self, **kwargs):
        return {"gaps": []}


@override_settings(
    YOUTUBE_TOKEN_ENCRYPTION_KEY="test-encryption-key",
    YOUTUBE_ANALYSIS_DAYS=90,
    YOUTUBE_ANALYSIS_MAX_VIDEOS=30,
    YOUTUBE_ANALYSIS_MIN_VIDEOS=10,
    YOUTUBE_ANALYSIS_REFRESH_MINUTES=60,
)
class YouTubeServiceTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="creator",
            email="creator@example.com",
            password="secret123",
        )

    def test_selects_at_most_thirty_recent_videos(self):
        uploads = [
            {
                "video_id": f"video-{index}",
                "published_at": (
                    FIXED_NOW - timedelta(days=index + 2)
                ).isoformat().replace("+00:00", "Z"),
            }
            for index in range(40)
        ]

        selected, period_start, period_end = select_analysis_videos(
            uploads=uploads,
            today=FIXED_NOW.date(),
        )

        self.assertEqual(len(selected), 30)
        self.assertEqual(period_end, date(2026, 7, 19))
        self.assertEqual(period_start, date(2026, 4, 21))

    def test_extends_backward_only_until_ten_videos(self):
        selected, period_start, _ = select_analysis_videos(
            uploads=upload_payloads(count=20),
            today=FIXED_NOW.date(),
        )

        self.assertEqual(len(selected), 10)
        self.assertEqual(period_start, selected[-1]["published_date"])

    def test_connects_channel_and_encrypts_refresh_token(self):
        from django.core import signing

        state = signing.dumps(
            {"user_id": self.user.id},
            salt="youtube-channel-connect",
            compress=True,
        )

        channel = connect_youtube_channel(
            code="oauth-code",
            state=state,
            redirect_uri="https://api.example.com/api/youtube/callback/",
            youtube_client=FakeYouTubeClient(),
        )

        self.assertEqual(channel.youtube_channel_id, "UC-test-channel")
        self.assertNotIn("google-refresh-token", channel.encrypted_refresh_token)
        self.assertEqual(
            decrypt_refresh_token(channel.encrypted_refresh_token),
            "google-refresh-token",
        )

    def test_analyzes_channel_and_reuses_result_during_cooldown(self):
        client = FakeYouTubeClient()
        channel = YouTubeChannel.objects.create(
            user=self.user,
            youtube_channel_id="UC-test-channel",
            title="MVP Creator",
            uploads_playlist_id="UU-test-channel",
            encrypted_refresh_token=self._encrypted_token(),
        )

        analysis, cached = analyze_youtube_channel(
            user_id=self.user.id,
            youtube_client=client,
            llm_client=FakeTextGenerationClient(),
            now=FIXED_NOW,
        )
        cached_analysis, second_cached = analyze_youtube_channel(
            user_id=self.user.id,
            youtube_client=client,
            llm_client=FakeTextGenerationClient(),
            now=FIXED_NOW + timedelta(minutes=20),
        )

        self.assertFalse(cached)
        self.assertTrue(second_cached)
        self.assertEqual(analysis.id, cached_analysis.id)
        self.assertEqual(analysis.videos_analyzed, 10)
        self.assertEqual(analysis.summary["videos_analyzed"], 10)
        self.assertLessEqual(len(analysis.content_gaps), 5)
        self.assertEqual(channel.analysis.id, analysis.id)
        self.assertEqual(len(client.analytics_calls), 2)

    def test_disconnect_revokes_token_and_deletes_data(self):
        client = FakeYouTubeClient()
        channel = YouTubeChannel.objects.create(
            user=self.user,
            youtube_channel_id="UC-test-channel",
            title="MVP Creator",
            uploads_playlist_id="UU-test-channel",
            encrypted_refresh_token=self._encrypted_token(),
        )
        YouTubeChannelAnalysis.objects.create(
            channel=channel,
            period_start=date(2026, 4, 21),
            period_end=date(2026, 7, 19),
        )

        disconnect_youtube_channel(
            user_id=self.user.id,
            youtube_client=client,
        )

        self.assertEqual(client.revoked_token, "google-refresh-token")
        self.assertFalse(YouTubeChannel.objects.filter(user=self.user).exists())
        self.assertFalse(YouTubeChannelAnalysis.objects.exists())

    def test_connecting_a_different_channel_removes_old_analysis(self):
        old_channel = YouTubeChannel.objects.create(
            user=self.user,
            youtube_channel_id="UC-old-channel",
            title="Old Channel",
            uploads_playlist_id="UU-old-channel",
            encrypted_refresh_token=self._encrypted_token(),
            last_analyzed_at=FIXED_NOW,
        )
        YouTubeChannelAnalysis.objects.create(
            channel=old_channel,
            period_start=date(2026, 4, 21),
            period_end=date(2026, 7, 19),
        )
        from django.core import signing

        state = signing.dumps(
            {"user_id": self.user.id},
            salt="youtube-channel-connect",
            compress=True,
        )

        channel = connect_youtube_channel(
            code="oauth-code",
            state=state,
            redirect_uri="https://api.example.com/api/youtube/callback/",
            youtube_client=FakeYouTubeClient(),
        )

        self.assertEqual(channel.youtube_channel_id, "UC-test-channel")
        self.assertIsNone(channel.last_analyzed_at)
        self.assertFalse(YouTubeChannelAnalysis.objects.filter(channel=channel).exists())

    def _encrypted_token(self):
        from .services import encrypt_refresh_token

        return encrypt_refresh_token("google-refresh-token")


@override_settings(
    GOOGLE_CLIENT_ID="google-client-id",
    GOOGLE_CLIENT_SECRET="google-client-secret",
    YOUTUBE_OAUTH_REDIRECT_URI="https://api.example.com/api/youtube/callback/",
    YOUTUBE_TOKEN_ENCRYPTION_KEY="test-encryption-key",
)
class YouTubeAPITests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="api-creator",
            email="api@example.com",
            password="secret123",
        )
        # Connect/analyze/analyze/disconnect now require Pro tier (pricing matrix).
        from django.contrib.auth.models import Group
        pro_group, _ = Group.objects.get_or_create(name="Pro Users")
        self.user.groups.add(pro_group)
        self.client.force_authenticate(user=self.user)

    @patch("youtube_channels.views.build_youtube_connect_url")
    def test_connect_url_requires_authenticated_user(self, mock_build_url):
        mock_build_url.return_value = "https://accounts.example/authorize"

        response = self.client.get(reverse("youtube-connect"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["data"]["auth_url"],
            "https://accounts.example/authorize",
        )
        mock_build_url.assert_called_once_with(
            user_id=self.user.id,
            redirect_uri="https://api.example.com/api/youtube/callback/",
        )

    def test_real_authorization_url_requests_offline_readonly_access(self):
        client = ConnectedYouTubeClient(
            client_id="google-client-id",
            client_secret="google-client-secret",
        )
        url = client.build_authorization_url(
            state="signed-state",
            redirect_uri="https://api.example.com/api/youtube/callback/",
        )
        query = parse_qs(urlsplit(url).query)

        self.assertEqual(query["access_type"], ["offline"])
        self.assertEqual(query["state"], ["signed-state"])
        self.assertEqual(set(query["scope"][0].split()), set(YOUTUBE_SCOPES))

    @patch("youtube_channels.views.analyze_youtube_channel")
    def test_analyze_endpoint_returns_latest_result(self, mock_analyze):
        channel = YouTubeChannel.objects.create(
            user=self.user,
            youtube_channel_id="UC-api-test",
            title="API Creator",
            uploads_playlist_id="UU-api-test",
            encrypted_refresh_token="encrypted",
        )
        analysis = YouTubeChannelAnalysis.objects.create(
            channel=channel,
            period_start=date(2026, 4, 21),
            period_end=date(2026, 7, 19),
            videos_analyzed=10,
            summary={"videos_analyzed": 10},
        )
        mock_analyze.return_value = (analysis, False)

        response = self.client.post(reverse("youtube-analyze"), {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["videos_analyzed"], 10)
        self.assertFalse(response.data["data"]["cached"])

    def test_channel_endpoint_does_not_expose_refresh_token(self):
        YouTubeChannel.objects.create(
            user=self.user,
            youtube_channel_id="UC-api-test",
            title="API Creator",
            uploads_playlist_id="UU-api-test",
            encrypted_refresh_token="secret-encrypted-value",
        )

        response = self.client.get(reverse("youtube-channel"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn("encrypted_refresh_token", response.data["data"])

    def test_channel_endpoint_requires_authentication(self):
        self.client.force_authenticate(user=None)

        response = self.client.get(reverse("youtube-channel"))

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
