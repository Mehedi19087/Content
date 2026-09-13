from datetime import timedelta
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from youtube_channels.models import YouTubeChannel as Connection
from .generation_services import FALLBACK_MESSAGE, generate_ideas
from .models import (
    ChannelDNA, GeneratedIdea, IdeaEvidence, NichePool, NichePoolChannel,
    PublicChannel, YouTubeVideo,
)


class CachedGenerationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="creator")
        self.other = get_user_model().objects.create_user(username="other")
        self.pool = NichePool.objects.create(
            identity="test-niche", name="Bangla travel", status="ready",
            definition={"topic": "japan travel"},
            expires_at=timezone.now() + timedelta(hours=12),
        )
        self.dna = self.make_dna(self.user, "own", {"private": "owner-data"})
        self.make_dna(self.other, "other", {"private": "do-not-share"})
        self.llm = Mock(model="test-model")
        self.raw = {
            "idea": "A budget Japan guide", "hook": "Plan your first trip",
            "why_this_fits_creator": "Your audience asks for travel planning",
            "why_now": "A useful topic", "suggested_format": "Guide",
            "suggested_video_length": "8 minutes", "risk": "Prices may change",
            "supporting_video_ids": [],
        }
        self.llm.generate_json.return_value = {"ideas": [self.raw]}

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
            view_count=10000,
        )

    @patch("urllib.request.urlopen", side_effect=AssertionError("Live HTTP forbidden"))
    def test_one_llm_call_no_live_youtube_and_private_isolation(self, http):
        result = generate_ideas(user_id=self.user.pk, count=1, llm_client=self.llm)
        self.llm.generate_json.assert_called_once()
        http.assert_not_called()
        payload = self.llm.generate_json.call_args.kwargs["user_payload"]
        self.assertEqual(payload["private_performance_summary"], {"private": "owner-data"})
        self.assertNotIn("do-not-share", str(payload))
        self.assertEqual(result["ideas"][0]["evidence_mode"], "AI_FALLBACK")
        self.assertEqual(GeneratedIdea.objects.get().dna_id, self.dna.pk)
        self.assertIn(FALLBACK_MESSAGE, result["ideas"][0]["why_now"])

    def test_fabricated_evidence_is_dropped_and_mode_downgraded(self):
        for index in range(3):
            self.add_video(index)
        foreign_pool = NichePool.objects.create(identity="foreign", name="Foreign")
        foreign = self.add_video("foreign")
        NichePoolChannel.objects.filter(channel=foreign.channel).update(pool=foreign_pool)
        self.raw.update({
            "idea": "A trending Japan guide", "evidence_mode": "EVIDENCE_BACKED",
            "confidence": 1.0, "supporting_video_ids": ["invented", foreign.youtube_video_id],
        })
        result = generate_ideas(user_id=self.user.pk, count=1, llm_client=self.llm)
        idea = result["ideas"][0]
        self.assertEqual(result["evidence_mode"], "AI_FALLBACK")
        self.assertEqual(idea["evidence_mode"], "AI_FALLBACK")
        self.assertEqual(idea["supporting_videos"], [])
        self.assertNotIn("trending", idea["idea"])
        self.assertLess(idea["confidence"], 0.5)
        self.assertFalse(IdeaEvidence.objects.exists())

    def test_evidence_modes_use_stored_supporting_channels(self):
        videos = [self.add_video(index) for index in range(3)]
        self.raw["supporting_video_ids"] = [video.youtube_video_id for video in videos]
        result = generate_ideas(user_id=self.user.pk, count=1, llm_client=self.llm)
        self.assertEqual(result["ideas"][0]["evidence_mode"], "EVIDENCE_BACKED")
        self.assertEqual(IdeaEvidence.objects.count(), 3)
        self.raw["supporting_video_ids"] = [videos[0].youtube_video_id]
        result = generate_ideas(user_id=self.user.pk, count=1, llm_client=self.llm)
        self.assertEqual(result["ideas"][0]["evidence_mode"], "LIMITED_EVIDENCE")
        self.assertIn("broad market trend has not been confirmed", result["ideas"][0]["why_now"])

    @patch("intelligence.tasks.queue_pool_refresh", side_effect=ConnectionError("Redis down"))
    def test_stale_cache_generation_survives_refresh_queue_failure(self, queue):
        self.pool.expires_at = timezone.now() - timedelta(days=1)
        self.pool.save(update_fields=["expires_at"])
        result = generate_ideas(user_id=self.user.pk, count=1, llm_client=self.llm)
        self.assertEqual(result["refresh_status"], "queue_unavailable")
        self.assertEqual(result["data_timestamp"], self.pool.fetched_at.isoformat())
        queue.assert_called_once_with(self.pool.pk)
        self.llm.generate_json.assert_called_once()
        self.assertEqual(GeneratedIdea.objects.count(), 1)

    def test_unconfirmed_dna_rejected_before_provider_call(self):
        self.dna.confirmed = False
        self.dna.save(update_fields=["confirmed"])
        with self.assertRaises(ValidationError):
            generate_ideas(user_id=self.user.pk, count=1, llm_client=self.llm)
        self.llm.generate_json.assert_not_called()

    def test_invalid_model_response_does_not_partially_save(self):
        self.llm.generate_json.return_value = {"ideas": [self.raw, {"idea": "incomplete"}]}
        with self.assertRaises(ValidationError):
            generate_ideas(user_id=self.user.pk, count=2, llm_client=self.llm)
        self.assertFalse(GeneratedIdea.objects.exists())

    @patch("intelligence.tasks.queue_pool_refresh", return_value="already_queued")
    def test_stale_refresh_status_is_preserved(self, queue):
        self.pool.expires_at = timezone.now() - timedelta(hours=1)
        self.pool.save(update_fields=["expires_at"])
        result = generate_ideas(user_id=self.user.pk, count=1, llm_client=self.llm)
        self.assertEqual(result["refresh_status"], "already_queued")
        queue.assert_called_once_with(self.pool.pk)

    def test_creator_channel_is_excluded_from_shared_competitor_evidence(self):
        own_video = self.add_video("own")
        own_video.channel.youtube_channel_id = self.dna.connection.youtube_channel_id
        own_video.channel.save(update_fields=["youtube_channel_id"])
        self.raw["supporting_video_ids"] = [own_video.youtube_video_id]
        result = generate_ideas(user_id=self.user.pk, count=1, llm_client=self.llm)
        self.assertEqual(result["ideas"][0]["evidence_mode"], "AI_FALLBACK")
        self.assertEqual(self.llm.generate_json.call_args.kwargs["user_payload"]["videos"], [])

    def test_unrelated_upload_is_excluded_from_evidence(self):
        video = self.add_video("unrelated")
        video.title = "Cooking Italian pizza"
        video.save(update_fields=["title"])
        self.raw["supporting_video_ids"] = [video.youtube_video_id]
        result = generate_ideas(user_id=self.user.pk, count=1, llm_client=self.llm)
        self.assertEqual(result["ideas"][0]["evidence_mode"], "AI_FALLBACK")
        self.assertFalse(IdeaEvidence.objects.exists())

    @patch("intelligence.tasks.queue_creator_analysis", side_effect=ConnectionError("Redis down"))
    def test_stale_private_summary_queues_refresh_without_blocking_ideas(self, queue):
        self.dna.expires_at = timezone.now() - timedelta(hours=1)
        self.dna.save(update_fields=["expires_at"])
        result = generate_ideas(user_id=self.user.pk, count=1, llm_client=self.llm)
        queue.assert_called_once_with(user_id=self.user.pk)
        self.assertEqual(result["creator_refresh_status"], "queue_unavailable")
        self.assertEqual(GeneratedIdea.objects.count(), 1)

    def test_evidence_timestamp_includes_older_private_analytics(self):
        old_time = timezone.now() - timedelta(days=4)
        self.dna.fetched_at = old_time
        self.dna.save(update_fields=["fetched_at"])
        result = generate_ideas(user_id=self.user.pk, count=1, llm_client=self.llm)
        self.assertEqual(result["data_timestamp"], old_time.isoformat())
        self.assertEqual(result["ideas"][0]["data_timestamp"], old_time.isoformat())

    def test_baselines_from_older_pool_refresh_are_not_reused(self):
        from .models import CompetitorBaseline

        video = self.add_video("baseline")
        CompetitorBaseline.objects.create(
            channel=video.channel, format="long", age_bucket="0-7d",
            median_views=100, fetched_at=self.pool.fetched_at - timedelta(days=2),
        )
        current = CompetitorBaseline.objects.create(
            channel=video.channel, format="long", age_bucket="8-30d",
            median_views=200, fetched_at=self.pool.fetched_at,
        )
        generate_ideas(user_id=self.user.pk, count=1, llm_client=self.llm)
        rows = self.llm.generate_json.call_args.kwargs["user_payload"]["baselines"]
        self.assertEqual([row["age_bucket"] for row in rows], [current.age_bucket])
