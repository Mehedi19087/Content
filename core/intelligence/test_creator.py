from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.exceptions import NotFound, ValidationError

from youtube_channels.exceptions import YouTubeAPIError, YouTubeAuthorizationError
from youtube_channels.models import YouTubeChannel
from youtube_channels.services import connect_youtube_channel, encrypt_refresh_token
from youtube_channels.youtube_client import ConnectedYouTubeClient

from .creator_services import analyze_creator, get_dna, update_dna
from .models import ChannelDNA, PublicChannel, QuotaLedger, YouTubeVideo
from .reporting_client import get_latest_reach_report


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class CreatorDNATests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="dna", email="dna@example.com", password="test-password",
        )
        self.connection = YouTubeChannel.objects.create(
            user=self.user, youtube_channel_id="UCowner", title="Travel",
            uploads_playlist_id="UUowner", encrypted_refresh_token=encrypt_refresh_token("refresh"),
        )
        self.client = Mock(spec=ConnectedYouTubeClient)
        self.client.refresh_access_token.return_value = "access"
        self.client.get_my_channel.return_value = {
            "id": "UCowner", "snippet": {"title": "Travel", "defaultLanguage": "bn"},
            "contentDetails": {"relatedPlaylists": {"uploads": "UUowner"}},
            "statistics": {},
        }
        self.client.get_upload_video_ids.return_value = [{"video_id": "private1"}]
        self.client.get_videos.return_value = [{"id": "private1", "snippet": {"title": "Japan"}}]
        self.client.query_analytics.return_value = [{"video": "private1", "views": 100}]
        self.llm = Mock()
        self.llm.model = "test-model"
        self.profile = {
            "core_topic": "Japan travel", "target_audience": "Bangladeshi travellers",
            "primary_language": "bn", "geographic_focus": "BD", "intent": "Budget planning",
            "main_content_formats": ["guide"], "creator_direction": "Continue",
        }
        self.llm.generate_json.return_value = {"profile": self.profile}
        self.reach = patch(
            "intelligence.creator_services.get_latest_reach_report",
            return_value={"available": False, "reason": "No existing reporting job."},
        )
        self.reach.start()
        self.addCleanup(self.reach.stop)

    def analyze(self):
        return analyze_creator(self.user.id, youtube_client=self.client, llm_client=self.llm)

    def test_analysis_keeps_private_data_out_of_shared_pool(self):
        dna = self.analyze()
        self.assertEqual(dna.profile["core_topic"], "Japan travel")
        self.assertEqual(dna.performance_summary["recent_videos"][0]["id"], "private1")
        self.assertFalse(PublicChannel.objects.exists())
        self.assertFalse(YouTubeVideo.objects.exists())
        self.assertEqual(sum(QuotaLedger.objects.values_list("data_units", flat=True)), 3)
        self.assertEqual(self.llm.generate_json.call_count, 1)
        calls = self.client.query_analytics.call_args_list
        self.assertEqual(len(calls), 5)
        self.assertEqual(calls[0].kwargs["max_results"], 50)
        self.assertEqual(calls[3].kwargs["filters"], "insightTrafficSourceType==YT_SEARCH")
        self.assertEqual(calls[3].kwargs["max_results"], 25)
        self.assertEqual(calls[4].kwargs["filters"], "video==private1")
        self.assertIn("thumbnail_impressions_and_ctr", dna.performance_summary["unavailable_metrics"])

    def test_unavailable_analytics_is_explicit_and_does_not_abort_profile(self):
        self.client.query_analytics.side_effect = YouTubeAPIError("Unavailable")
        dna = self.analyze()
        self.assertEqual(dna.performance_summary["top_videos_90d"], [])
        self.assertIn("top_videos_90d", dna.performance_summary["unavailable_metrics"])

    def test_revoked_token_requires_reauthorization(self):
        self.client.refresh_access_token.side_effect = YouTubeAuthorizationError("Revoked")
        with self.assertRaises(ValidationError):
            self.analyze()
        self.connection.refresh_from_db()
        self.assertEqual(self.connection.status, YouTubeChannel.Status.REAUTH_REQUIRED)

    def test_confirmed_edits_survive_background_analysis(self):
        ChannelDNA.objects.create(connection=self.connection, profile=self.profile, confirmed=True)
        self.llm.generate_json.return_value = {"profile": {"core_topic": "Wrong"}}
        dna = self.analyze()
        self.assertEqual(dna.profile, self.profile)
        self.llm.generate_json.assert_not_called()

    def test_inflight_analysis_does_not_overwrite_reconnected_channel(self):
        def change_channel(**kwargs):
            YouTubeChannel.objects.filter(pk=self.connection.pk).update(
                youtube_channel_id="UCnew", title="New channel",
            )
            return {"profile": self.profile}

        self.llm.generate_json.side_effect = change_channel
        with self.assertRaises(ValidationError):
            self.analyze()
        self.connection.refresh_from_db()
        self.assertEqual(self.connection.youtube_channel_id, "UCnew")
        self.assertEqual(self.connection.title, "New channel")
        self.assertFalse(ChannelDNA.objects.exists())

    def test_provider_failure_leaves_reviewable_draft_without_invented_topic(self):
        self.llm.generate_json.side_effect = RuntimeError("Provider failed")
        dna = self.analyze()
        self.assertEqual(dna.profile["core_topic"], "")
        self.assertEqual(dna.profile["primary_language"], "bn")
        self.assertEqual(dna.model_version, "metadata-only")

    def test_confirmation_reuses_pool_and_requires_core_fields(self):
        self.analyze()
        first = update_dna(self.user.id, {}, True)
        again = update_dna(self.user.id, {}, True)
        self.assertEqual(first.niche_pool_id, again.niche_pool_id)
        with self.assertRaises(ValidationError):
            update_dna(self.user.id, {"core_topic": ""}, True)
        with self.assertRaises(ValidationError):
            update_dna(self.user.id, {"arbitrary": "field"}, False)
        with self.assertRaises(ValidationError):
            update_dna(self.user.id, {"primary_language": "Bangla"}, True)

    def test_owner_isolation(self):
        self.analyze()
        other = get_user_model().objects.create_user(username="other", email="other@example.com", password="test")
        with self.assertRaises(NotFound):
            get_dna(other.id)
        with self.assertRaises(NotFound):
            update_dna(other.id, {}, True)

    @patch("youtube_channels.services.signing.loads")
    def test_switching_oauth_channel_removes_old_dna(self, signing_loads):
        self.analyze()
        signing_loads.return_value = {"user_id": self.user.id}
        self.client.exchange_code.return_value = {"access_token": "access", "refresh_token": "new"}
        self.client.get_my_channel.return_value["id"] = "UCnew"
        connect_youtube_channel(
            code="code", state="state", redirect_uri="https://example.com/callback",
            youtube_client=self.client,
        )
        self.assertFalse(ChannelDNA.objects.exists())


class CreatorClientTests(TestCase):
    def test_oauth_requests_incremental_offline_readonly_scopes(self):
        client = ConnectedYouTubeClient(client_id="id", client_secret="secret")
        params = parse_qs(urlparse(client.build_authorization_url(state="state", redirect_uri="https://example.com")).query)
        self.assertEqual(params["include_granted_scopes"], ["true"])
        self.assertEqual(params["access_type"], ["offline"])
        self.assertIn("yt-analytics.readonly", params["scope"][0])

    def test_reporting_missing_job_is_explicit(self):
        client = Mock()
        client._get.side_effect = [{"reportTypes": [{"id": "channel_reach_a1"}]}, {"jobs": []}]
        report = get_latest_reach_report(client, "access")
        self.assertFalse(report["available"])
        self.assertIn("job", report["reason"])

    @patch("intelligence.reporting_client.requests.get")
    def test_reporting_download_rejects_untrusted_url_before_sending_token(self, request):
        client = Mock()
        client._get.side_effect = [
            {"reportTypes": [{"id": "channel_reach_a1"}]},
            {"jobs": [{"id": "job", "reportTypeId": "channel_reach_a1"}]},
            {"reports": [{"id": "report", "downloadUrl": "https://evil.example/report"}]},
        ]
        with self.assertRaises(YouTubeAPIError):
            get_latest_reach_report(client, "private-access-token")
        request.assert_not_called()

    @patch("intelligence.reporting_client.requests.get")
    def test_reporting_aggregates_ctr_weighted_by_impressions(self, request):
        client = Mock(timeout=10)
        client._get.side_effect = [
            {"reportTypes": [{"id": "channel_reach_a1"}]},
            {"jobs": [{"id": "job", "reportTypeId": "channel_reach_a1"}]},
            {"reports": [{"id": "report", "downloadUrl": "https://youtubereporting.googleapis.com/report"}]},
        ]
        response = request.return_value
        response.status_code = 200
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.iter_content.return_value = [
            b"video_thumbnail_impressions,video_thumbnail_impressions_ctr\n100,0.1\n300,0.2\n",
        ]
        report = get_latest_reach_report(client, "access")
        self.assertTrue(report["available"])
        self.assertEqual(report["thumbnail_impressions"], 400)
        self.assertAlmostEqual(report["thumbnail_impressions_ctr"], 0.175)
