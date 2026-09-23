from datetime import timedelta
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from youtube_channels.models import YouTubeChannel as Connection
from .generation_services import generate_ideas
from .models import (
    ChannelDNA, GeneratedIdea, IdeaEvidence, NichePool, NichePoolChannel,
    PublicChannel, TrendSignal, VideoStatSnapshot, YouTubeVideo,
)


class CachedGenerationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="creator")
        self.other = get_user_model().objects.create_user(username="other")
        self.pool = NichePool.objects.create(
            identity="test-niche", name="Bangla travel", status="succeeded",
            definition={"topic": "japan travel"}, last_search_at=timezone.now(),
            expires_at=timezone.now() + timedelta(hours=12),
        )
        self.dna = self.make_dna(self.user, "own", {"private": "owner-data"})
        self.make_dna(self.other, "other", {"private": "do-not-share"})
        self.llm = Mock(model="test-model")
        self.raw = {
            "idea": "A budget Japan guide", "hook": "Plan your first trip",
            "why_this_fits_creator": "Travel planning for your audience",
            "why_now": "Invented 99 million searches", "suggested_format": "Guide",
            "suggested_video_length": "8 minutes", "risk": "Prices may change",
            "supporting_video_ids": [],
        }
        self.llm.generate_json.return_value = {"ideas": [self.raw]}
        self.queue = patch("intelligence.tasks.queue_pool_refresh", return_value="fresh").start()
        self.addCleanup(patch.stopall)
        patch("requests.get", side_effect=AssertionError("Live HTTP forbidden")).start()
        patch("urllib.request.urlopen", side_effect=AssertionError("Live HTTP forbidden")).start()

    def make_dna(self, user, channel_id, summary):
        connection = Connection.objects.create(
            user=user, youtube_channel_id=channel_id, title=channel_id,
            uploads_playlist_id="uploads", encrypted_refresh_token="never-used",
        )
        return ChannelDNA.objects.create(
            connection=connection, profile={"topic": "Japan travel"},
            performance_summary=summary, confirmed=True, niche_pool=self.pool,
            expires_at=timezone.now() + timedelta(days=1),
        )

    def add_video(self, suffix):
        channel = PublicChannel.objects.create(
            youtube_channel_id=f"channel-{suffix}", title=f"Travel {suffix}",
        )
        NichePoolChannel.objects.create(pool=self.pool, channel=channel, relevant=True)
        return YouTubeVideo.objects.create(
            youtube_video_id=f"video-{suffix}", channel=channel,
            title="Japan travel budget tips", published_at=timezone.now() - timedelta(days=10),
            view_count=10000, expires_at=timezone.now() + timedelta(hours=12),
        )

    def generate(self):
        return generate_ideas(user_id=self.user.pk, count=1, llm_client=self.llm)

    def support(self, video):
        self.raw["supporting_video_ids"] = [video.youtube_video_id]

    def test_no_evidence_never_calls_model_or_saves_ai_fallback(self):
        result = self.generate()
        self.assertEqual(result["ideas"], [])
        self.assertEqual(result["status"], "insufficient_evidence")
        self.assertIsNone(result["data_timestamp"])
        self.llm.generate_json.assert_not_called()
        self.assertFalse(GeneratedIdea.objects.exists())

    def test_pending_evidence_returns_pollable_state(self):
        self.queue.return_value = "already_queued"
        self.assertEqual(self.generate()["status"], "collecting_evidence")
        self.llm.generate_json.assert_not_called()

    def test_one_llm_call_no_live_youtube_and_private_isolation(self):
        self.support(self.add_video(1))
        result = self.generate()
        self.llm.generate_json.assert_called_once()
        payload = self.llm.generate_json.call_args.kwargs["user_payload"]
        self.assertEqual(payload["private_performance_summary"], {"private": "owner-data"})
        self.assertNotIn("do-not-share", str(payload))
        self.assertEqual(result["ideas"][0]["evidence_mode"], "LIMITED_EVIDENCE")
        self.assertEqual(GeneratedIdea.objects.get().dna_id, self.dna.pk)

    def test_fabricated_or_foreign_evidence_cannot_create_idea(self):
        self.add_video(1)
        foreign = self.add_video("foreign")
        foreign_pool = NichePool.objects.create(identity="foreign", name="Foreign")
        NichePoolChannel.objects.filter(channel=foreign.channel).update(pool=foreign_pool)
        self.raw.update({"evidence_mode": "EVIDENCE_BACKED", "confidence": 1,
                         "supporting_video_ids": ["invented", foreign.youtube_video_id]})
        self.assertEqual(self.generate()["ideas"], [])
        self.assertFalse(GeneratedIdea.objects.exists())
        self.assertFalse(IdeaEvidence.objects.exists())

    def test_sources_are_server_metrics_and_demand_prose_is_not_from_llm(self):
        video = self.add_video(1)
        self.support(video)
        snapshot = VideoStatSnapshot.objects.create(video=video, view_count=12345)
        self.raw.update({"views": 999999, "demand_status": "high"})
        idea = self.generate()["ideas"][0]
        source = idea["supporting_videos"][0]
        self.assertEqual(source["views"], 12345)
        self.assertEqual(source["source"], "youtube_data_api")
        self.assertEqual(source["fetched_at"], snapshot.fetched_at.isoformat())
        self.assertEqual(source["url"], f"https://www.youtube.com/watch?v={video.youtube_video_id}")
        self.assertEqual(idea["demand_status"], "not_established")
        self.assertNotIn("99 million", idea["why_now"])
        self.assertIsNone(source["outlier_multiplier"])

    def test_outperformance_uses_saved_calculation_and_exposes_baseline(self):
        video = self.add_video(1)
        self.support(video)
        signal = TrendSignal.objects.create(
            pool=self.pool, video=video, outlier_multiplier=2.5,
            details={"baseline_views": 4000, "sample_size": 4, "age_bucket": "8-30d"},
            expires_at=timezone.now() + timedelta(hours=1),
        )
        idea = self.generate()["ideas"][0]
        self.assertEqual(idea["demand_status"], "observed_outperformance")
        self.assertEqual(idea["supporting_videos"][0]["baseline"], signal.details)
        signal.expires_at = timezone.now() - timedelta(hours=1)
        signal.save()
        self.assertEqual(self.generate()["ideas"][0]["demand_status"], "not_established")

    def test_channel_count_is_evidence_breadth_not_proof_of_demand(self):
        videos = [self.add_video(index) for index in range(3)]
        self.raw["supporting_video_ids"] = [video.youtube_video_id for video in videos]
        idea = self.generate()["ideas"][0]
        self.assertEqual(idea["evidence_mode"], "EVIDENCE_BACKED")
        self.assertEqual(idea["demand_status"], "not_established")
        self.assertEqual(IdeaEvidence.objects.count(), 3)

    def test_new_statistics_invalidate_old_outlier_calculation(self):
        video = self.add_video(1)
        self.support(video)
        TrendSignal.objects.create(
            pool=self.pool, video=video, outlier_multiplier=3,
            expires_at=timezone.now() + timedelta(hours=1),
        )
        VideoStatSnapshot.objects.create(video=video, view_count=20000)
        idea = self.generate()["ideas"][0]
        self.assertEqual(idea["supporting_videos"][0]["views"], 20000)
        self.assertEqual(idea["demand_status"], "not_established")

    def test_expired_old_unofficial_unrelated_and_own_videos_are_excluded(self):
        video = self.add_video(1)
        self.support(video)
        original = {"source": video.source, "expires_at": video.expires_at,
                    "published_at": video.published_at, "title": video.title}
        cases = [
            {"source": "ai"}, {"expires_at": timezone.now() - timedelta(seconds=1)},
            {"published_at": timezone.now() - timedelta(days=181)},
            {"title": "Cooking Italian pizza"},
        ]
        for changes in cases:
            with self.subTest(changes=changes):
                YouTubeVideo.objects.filter(pk=video.pk).update(**{**original, **changes})
                self.assertEqual(self.generate()["ideas"], [])
        YouTubeVideo.objects.filter(pk=video.pk).update(**original)
        video.channel.youtube_channel_id = self.dna.connection.youtube_channel_id
        video.channel.save()
        self.assertEqual(self.generate()["ideas"], [])
        self.llm.generate_json.assert_not_called()

    def test_fresh_sources_survive_pool_refresh_queue_failure(self):
        self.support(self.add_video(1))
        self.pool.expires_at = timezone.now() - timedelta(days=1)
        self.pool.save()
        self.queue.side_effect = ConnectionError("Redis down")
        result = self.generate()
        self.assertEqual(result["refresh_status"], "queue_unavailable")
        self.assertEqual(len(result["ideas"]), 1)

    def test_partial_result_does_not_pad_with_unsupported_ideas(self):
        self.support(self.add_video(1))
        self.llm.generate_json.return_value = {"ideas": [self.raw, {
            **self.raw, "supporting_video_ids": ["made-up"],
        }]}
        result = generate_ideas(user_id=self.user.pk, count=2, llm_client=self.llm)
        self.assertEqual(len(result["ideas"]), 1)
        self.assertIn("Only 1 of 2", result["message"])

    def test_unconfirmed_dna_rejected_before_provider_call(self):
        self.dna.confirmed = False
        self.dna.save()
        with self.assertRaises(ValidationError):
            self.generate()
        self.llm.generate_json.assert_not_called()

    def test_invalid_model_response_does_not_partially_save(self):
        self.support(self.add_video(1))
        self.llm.generate_json.return_value = {"ideas": [self.raw, {"idea": "incomplete"}]}
        with self.assertRaises(ValidationError):
            generate_ideas(user_id=self.user.pk, count=2, llm_client=self.llm)
        self.assertFalse(GeneratedIdea.objects.exists())
