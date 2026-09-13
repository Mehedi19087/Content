from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from .models import EvidenceMode, NichePool, QuotaLedger, TrendSignal
from .services import calculate_signals, get_or_create_niche_pool, refresh_niche_pool, store_channel, store_videos
from .web_client import youtube_ids
from .youtube_client import PublicYouTubeClient


def channel_item(channel_id):
    return {"id": channel_id, "snippet": {"title": "Japan travel",
        "defaultLanguage": "bn"}, "contentDetails": {"relatedPlaylists": {"uploads": "uploads-" + channel_id}}}


def video_item(channel_id, index, views=100):
    return {"id": f"{channel_id}-{index}", "snippet": {"channelId": channel_id,
        "title": "Japan budget travel", "publishedAt": (timezone.now() - timedelta(days=15)).isoformat()},
        "statistics": {"viewCount": str(views)}, "contentDetails": {"duration": "PT10M"}}


class NichePoolTests(TestCase):
    def setUp(self):
        self.profile = {"core_topic": "Japan travel", "primary_language": "Bangla",
            "geographic_focus": "Bangladesh", "target_audience": "budget travellers",
            "main_content_formats": ["guide", "vlog"]}
        self.pool, _ = get_or_create_niche_pool(self.profile)

    def test_equivalent_niche_reused_without_network(self):
        pool, created = get_or_create_niche_pool({**self.profile, "core_topic": "TRAVEL Japan!",
            "main_content_formats": ["vlog", "guide"]})
        self.assertFalse(created)
        self.assertEqual(pool.pk, self.pool.pk)
        different, created = get_or_create_niche_pool({**self.profile,
            "primary_language": "English"})
        self.assertTrue(created)
        self.assertNotEqual(different.pk, pool.pk)

    def test_bangla_topic_retains_combining_marks(self):
        profile = {**self.profile, "core_topic": "জাপান ভ্রমণ"}
        pool, _ = get_or_create_niche_pool(profile)
        self.assertEqual(pool.definition["topic"], "জাপান ভ্রমণ")

    def test_ambiguous_short_videos_cannot_produce_outliers(self):
        channel = store_channel(channel_item("shorts"))
        items = [video_item("shorts", i, 10000 if i == 3 else 100)
                 for i in range(4)]
        for item in items:
            item["contentDetails"]["duration"] = "PT60S"
        store_videos(items)
        calculate_signals(self.pool, [channel])
        self.assertFalse(self.pool.signals.exists())

    @patch("intelligence.services.PublicYouTubeClient")
    def test_stale_delivery_does_not_collect(self, client_class):
        refresh_niche_pool(
            self.pool.pk, expected_requested_at=timezone.now().isoformat(),
        )
        client_class.assert_not_called()

    @patch("intelligence.services.web_client.search_context", return_value=[])
    @patch("intelligence.services.PublicYouTubeClient")
    def test_monthly_rediscovery_requires_explicit_flag(self, client_class, web):
        client = client_class.return_value
        client.search.return_value = []
        client.channels.return_value = []
        client.videos.return_value = []
        self.pool.last_search_at = timezone.now() - timedelta(days=31)
        self.pool.save()
        refresh_niche_pool(self.pool.pk)
        client.search.assert_not_called()
        refresh_niche_pool(self.pool.pk, rediscover=True)
        client.search.assert_called_once()

    @patch("intelligence.services.web_client.search_context", return_value=[])
    @patch("intelligence.services.PublicYouTubeClient")
    def test_empty_results_never_repeat_search(self, client_class, web_search):
        client = client_class.return_value
        client.search.return_value = []
        client.channels.return_value = []
        client.videos.return_value = []
        for rediscover in (False, False, True):
            result = refresh_niche_pool(self.pool.pk, rediscover=rediscover)
        self.assertEqual(client.search.call_count, 1)
        self.assertEqual(result.evidence_mode, EvidenceMode.AI_FALLBACK)
        web_search.assert_called_once()

    @patch("intelligence.services.web_client.search_context", return_value=[])
    @patch("intelligence.services.PublicYouTubeClient")
    def test_failure_consumes_search_reservation(self, client_class, web_search):
        client = client_class.return_value
        client.search.side_effect = RuntimeError("quota")
        with self.assertRaises(RuntimeError):
            refresh_niche_pool(self.pool.pk)
        self.pool.refresh_from_db()
        self.assertIsNotNone(self.pool.last_search_at)
        self.assertEqual(self.pool.status, "failed")
        refresh_niche_pool(self.pool.pk)
        self.assertEqual(client.search.call_count, 1)

    @patch("intelligence.services.PublicYouTubeClient")
    def test_validates_uploads_and_caps_competitors_at_five(self, client_class):
        client = client_class.return_value
        ids = [f"channel{i}" for i in range(7)]
        client.search.return_value = [{"snippet": {"channelId": value,
            "title": "Japan travel"}} for value in ids]
        client.channels.return_value = [channel_item(value) for value in ids]
        client.uploads.side_effect = lambda playlist: [{"contentDetails": {"videoId": f"{playlist[8:]}-{index}"}} for index in range(4)]
        client.videos.side_effect = lambda values: [video_item(value.rsplit("-",
            1)[0], int(value.rsplit("-", 1)[1]), 1000 if value.endswith("-3") else 100) for value in values]
        result = refresh_niche_pool(self.pool.pk)
        self.assertEqual(result.memberships.filter(relevant=True).count(), 5)
        self.assertEqual(client.uploads.call_count, 5)
        self.assertEqual(result.evidence_mode, EvidenceMode.EVIDENCE_BACKED)
        self.assertEqual(result.signals.count(), 5)
        refresh_niche_pool(self.pool.pk)
        self.assertEqual(client.search.call_count, 1)

    @patch("intelligence.services.web_client.search_context", return_value=[])
    @patch("intelligence.services.PublicYouTubeClient")
    def test_single_related_video_does_not_validate_channel(self, client_class, web_search):
        client = client_class.return_value
        client.search.return_value = [{"snippet": {"channelId": "c", "title": "Japan travel"}}]
        client.channels.side_effect = lambda ids: [channel_item("c")] if ids else []
        client.uploads.return_value = [{"contentDetails": {"videoId": "c-1"}}]
        client.videos.side_effect = lambda ids: [video_item("c", 1)] if ids else []
        result = refresh_niche_pool(self.pool.pk)
        self.assertEqual(result.evidence_mode, EvidenceMode.AI_FALLBACK)

    def test_baseline_excludes_target_and_separates_age_and_duration(self):
        channel = store_channel(channel_item("c"))
        items = [video_item("c", i, 1000 if i == 3 else 100) for i in range(4)]
        brief = video_item("c", 4, 50000)
        brief["contentDetails"]["duration"] = "PT30S"
        old = video_item("c", 5, 50000)
        old["snippet"]["publishedAt"] = (timezone.now() - timedelta(days=200)).isoformat()
        store_videos(items + [brief, old])
        self.pool.confidence = 0.75
        self.pool.expires_at = timezone.now() + timedelta(days=1)
        calculate_signals(self.pool, [channel])
        signal = TrendSignal.objects.get()
        self.assertEqual(signal.outlier_multiplier, 10)
        self.assertEqual(signal.details["sample_size"], 3)

    def test_web_urls_only_accept_official_hosts(self):
        videos, channels = youtube_ids([{"url": "https://youtu.be/abcdefghijk"},
            {"url": "https://youtube.com.evil.test/watch?v=zzzzzzzzzzz"}, {"url": "https://www.youtube.com/channel/UC" + "a" * 22}])
        self.assertEqual(videos, ["abcdefghijk"])
        self.assertEqual(channels, ["UC" + "a" * 22])

    @override_settings(YOUTUBE_API_KEY="test")
    @patch("intelligence.youtube_client.requests.get")
    def test_failed_requests_count_quota_and_videos_batch_at_fifty(self, get):
        get.return_value.ok = True
        get.return_value.json.return_value = {"items": []}
        client = PublicYouTubeClient(self.pool)
        client.videos([str(i) for i in range(101)])
        self.assertEqual(QuotaLedger.objects.count(), 3)
        get.return_value.ok = False
        get.return_value.status_code = 403
        with self.assertRaises(RuntimeError):
            client.search("Japan")
        self.assertEqual(QuotaLedger.objects.get(operation="search.list").search_calls, 1)
        self.assertEqual(QuotaLedger.objects.get(operation="search.list").data_units, 0)

    @override_settings(YOUTUBE_API_KEY="private-api-key")
    @patch("intelligence.youtube_client.requests.get")
    def test_connection_error_does_not_expose_key_in_worker_traceback(self, get):
        import traceback
        import requests

        get.side_effect = requests.ConnectionError("failed URL?key=private-api-key")
        try:
            PublicYouTubeClient(self.pool).search("Japan")
        except RuntimeError:
            self.assertNotIn("private-api-key", traceback.format_exc())
        else:
            self.fail("Expected a sanitized provider error.")
        self.assertEqual(QuotaLedger.objects.get().search_calls, 1)
