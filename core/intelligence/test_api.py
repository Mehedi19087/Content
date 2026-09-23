from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from youtube_channels.models import YouTubeChannel

from .models import ChannelDNA, NichePool
from .workflow_services import queue_pool_refresh, refresh_due_pools


class IntelligenceAPITests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="owner")
        self.other = get_user_model().objects.create_user(username="other")
        self.connection = YouTubeChannel.objects.create(
            user=self.user, youtube_channel_id="UCowner", title="Travel",
            uploads_playlist_id="UUowner", encrypted_refresh_token="encrypted",
        )
        self.client.force_authenticate(self.user)

    def test_authentication_required(self):
        self.client.force_authenticate(None)
        for name in ("intelligence-dna", "intelligence-niche"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 401)
        for name in ("intelligence-analyze", "intelligence-ideas"):
            self.assertEqual(self.client.post(reverse(name), {}).status_code, 401)

    def test_channel_confirmation_required(self):
        response = self.client.post(reverse("intelligence-analyze"), {
            "channel_confirmed": False,
        }, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.data)
        self.assertFalse(ChannelDNA.objects.exists())

    @patch("intelligence.tasks.analyze_creator_task.apply_async")
    def test_analysis_queues_once_and_returns_pollable_dna(self, dispatch):
        for _ in range(2):
            response = self.client.post(reverse("intelligence-analyze"), {
                "channel_confirmed": True,
            }, format="json")
            self.assertEqual(response.status_code, 202)
            self.assertEqual(response.data["data"]["status"], "pending")
        dispatch.assert_called_once()
        dna = ChannelDNA.objects.get(connection=self.connection)
        dispatch.assert_called_once_with(
            args=[self.user.pk],
            kwargs={"dna_id": dna.pk, "requested_at": dna.refresh_requested_at.isoformat()},
            retry=False,
        )
        response = self.client.get(reverse("intelligence-dna"))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("encrypted_refresh_token", response.data["data"])

    @patch("intelligence.tasks.analyze_creator_task.apply_async", side_effect=OSError)
    def test_queue_failure_persisted_and_returns_503(self, dispatch):
        response = self.client.post(reverse("intelligence-analyze"), {
            "channel_confirmed": True,
        }, format="json")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data["error"]["code"], "queue_unavailable")
        self.assertEqual(ChannelDNA.objects.get().status, "failed")

    def test_private_dna_cannot_be_read_by_other_user(self):
        ChannelDNA.objects.create(connection=self.connection, profile={"core_topic": "private"})
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(reverse("intelligence-dna")).status_code, 404)
        self.assertEqual(self.client.get(reverse("intelligence-niche")).status_code, 404)

    def test_generation_requires_confirmed_dna(self):
        response = self.client.post(reverse("intelligence-ideas"), {}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_polling_a_stuck_analysis_returns_failed(self):
        dna = ChannelDNA.objects.create(
            connection=self.connection, status="running",
            refresh_requested_at=timezone.now() - timedelta(minutes=11),
        )
        response = self.client.get(reverse("intelligence-dna"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["status"], "failed")
        dna.refresh_from_db()
        self.assertIsNone(dna.refresh_requested_at)

    def test_generation_count_validation(self):
        response = self.client.post(reverse("intelligence-ideas"), {"count": 51})
        self.assertEqual(response.status_code, 400)

    @patch("intelligence.tasks.refresh_pool_task.apply_async")
    def test_pool_queue_deduplicates_requests_and_reuses_fresh_evidence(self, dispatch):
        pool = NichePool.objects.create(identity="pool", name="Travel")
        self.assertEqual(queue_pool_refresh(pool.pk), "queued")
        self.assertEqual(queue_pool_refresh(pool.pk), "already_queued")
        self.assertEqual(dispatch.call_count, 1)
        pool.status = "succeeded"
        pool.last_search_at = timezone.now()
        pool.refresh_requested_at = None
        pool.expires_at = timezone.now() + timedelta(hours=12)
        pool.save()
        self.assertEqual(queue_pool_refresh(pool.pk), "fresh")
        self.assertEqual(dispatch.call_count, 1)

    @patch("intelligence.tasks.refresh_pool_task.apply_async", side_effect=OSError)
    def test_pool_queue_failure_is_nonblocking_and_retryable(self, dispatch):
        pool = NichePool.objects.create(identity="pool", name="Travel")
        self.assertEqual(queue_pool_refresh(pool.pk), "queue_unavailable")
        pool.refresh_from_db()
        self.assertEqual(pool.status, "failed")
        self.assertIsNone(pool.refresh_requested_at)

    @patch("intelligence.tasks.refresh_pool_task.apply_async")
    def test_scheduler_only_queues_active_due_pools_with_monthly_rediscovery(self, dispatch):
        pool = NichePool.objects.create(
            identity="active", name="Travel",
            last_search_at=timezone.now() - timedelta(days=31),
            expires_at=timezone.now() + timedelta(hours=12),
        )
        NichePool.objects.create(identity="unused", name="Unused")
        ChannelDNA.objects.create(connection=self.connection, niche_pool=pool, confirmed=True)
        self.assertEqual(refresh_due_pools(), {pool.pk: "queued"})
        pool.refresh_from_db()
        dispatch.assert_called_once_with(
            args=[pool.pk],
            kwargs={"rediscover": True, "requested_at": pool.refresh_requested_at.isoformat()},
            retry=False,
        )

    @patch("urllib.request.urlopen", side_effect=AssertionError("Unexpected live HTTP request"))
    @patch("requests.get", side_effect=AssertionError("Unexpected live YouTube request"))
    @patch("intelligence.generation_services.DeepSeekClient")
    @patch("intelligence.tasks.analyze_creator_task.apply_async")
    @patch("intelligence.tasks.refresh_pool_task.apply_async")
    def test_confirm_shared_niche_then_generate_from_owner_cache(
        self, pool_dispatch, creator_dispatch, llm_class, http_get, urlopen,
    ):
        from .models import GeneratedIdea, QuotaLedger

        profile = {
            "core_topic": "Japan travel", "target_audience": "Bangladeshi travellers",
            "primary_language": "bn", "geographic_focus": "BD", "intent": "Budget planning",
            "main_content_formats": ["guide"], "creator_direction": "Continue",
        }
        fresh_until = timezone.now() + timedelta(hours=12)
        ChannelDNA.objects.create(
            connection=self.connection, profile=profile, expires_at=fresh_until,
            performance_summary={"private_marker": "first-creator"},
        )
        response = self.client.patch(reverse("intelligence-dna"), {
            "profile": profile, "confirmed": True,
        }, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        pool_id = response.data["data"]["niche_pool_id"]
        self.assertEqual(response.data["refresh_status"], "queued")
        pool_dispatch.assert_called_once()
        NichePool.objects.filter(pk=pool_id).update(
            status="succeeded", expires_at=fresh_until, refresh_requested_at=None,
            last_search_at=timezone.now(),
        )

        other_connection = YouTubeChannel.objects.create(
            user=self.other, youtube_channel_id="UCother", title="Other travel",
            uploads_playlist_id="UUother", encrypted_refresh_token="encrypted",
        )
        ChannelDNA.objects.create(
            connection=other_connection, profile=profile, expires_at=fresh_until,
            performance_summary={"private_marker": "second-creator"},
        )
        self.client.force_authenticate(self.other)
        response = self.client.patch(reverse("intelligence-dna"), {
            "profile": profile, "confirmed": True,
        }, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["niche_pool_id"], pool_id)
        self.assertEqual(response.data["refresh_status"], "fresh")
        self.assertEqual(NichePool.objects.count(), 1)
        self.assertEqual(pool_dispatch.call_count, 1)

        from .models import PublicChannel, NichePoolChannel, YouTubeVideo
        competitor = PublicChannel.objects.create(youtube_channel_id="competitor", title="Travel")
        NichePoolChannel.objects.create(pool_id=pool_id, channel=competitor)
        YouTubeVideo.objects.create(
            youtube_video_id="source-video", channel=competitor, title="Japan travel",
            published_at=timezone.now() - timedelta(days=10), view_count=1234,
            expires_at=fresh_until,
        )
        llm_class.return_value.model = "test-model"
        llm_class.return_value.generate_json.return_value = {"ideas": [{
            "idea": "Plan your first Japan trip", "hook": "Start with a realistic budget",
            "why_this_fits_creator": "A practical guide for your audience",
            "why_now": "Evergreen planning question", "suggested_format": "guide",
            "suggested_video_length": "8 minutes", "risk": "Prices may change",
            "supporting_video_ids": ["source-video"],
        }]}
        response = self.client.post(reverse("intelligence-ideas"), {"count": 1}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        idea = response.data["data"]["ideas"][0]
        self.assertEqual(idea["evidence_mode"], "LIMITED_EVIDENCE")
        self.assertEqual(idea["supporting_videos"][0]["views"], 1234)
        saved = GeneratedIdea.objects.get()
        self.assertEqual(saved.dna.connection.user_id, self.other.pk)
        payload = llm_class.return_value.generate_json.call_args.kwargs["user_payload"]
        self.assertEqual(payload["private_performance_summary"], {"private_marker": "second-creator"})
        llm_class.return_value.generate_json.assert_called_once()
        creator_dispatch.assert_not_called()
        http_get.assert_not_called()
        urlopen.assert_not_called()
        self.assertFalse(QuotaLedger.objects.exists())

    def test_old_creator_job_cannot_claim_or_finish_new_lease(self):
        from .workflow_services import finish_creator_analysis, start_creator_analysis

        now = timezone.now()
        dna = ChannelDNA.objects.create(
            connection=self.connection, status="pending", refresh_requested_at=now,
        )
        stale_lease = (now - timedelta(minutes=11)).isoformat()
        self.assertFalse(start_creator_analysis(
            self.user.pk, dna_id=dna.pk, requested_at=stale_lease,
        ))
        finish_creator_analysis(
            self.user.pk, dna_id=dna.pk, requested_at=stale_lease, failed=True,
        )
        dna.refresh_from_db()
        self.assertEqual(dna.status, "pending")
        self.assertEqual(dna.refresh_requested_at, now)
        self.assertTrue(start_creator_analysis(
            self.user.pk, dna_id=dna.pk, requested_at=now.isoformat(),
        ))
        finish_creator_analysis(
            self.user.pk, dna_id=dna.pk, requested_at=now.isoformat(),
        )
        dna.refresh_from_db()
        self.assertEqual(dna.status, "succeeded")
        self.assertIsNone(dna.refresh_requested_at)

    def test_polling_stuck_evidence_collection_allows_retry(self):
        pool = NichePool.objects.create(
            identity="stuck", name="Travel", status="running",
            refresh_requested_at=timezone.now() - timedelta(minutes=11),
        )
        ChannelDNA.objects.create(connection=self.connection, niche_pool=pool, confirmed=True)
        response = self.client.get(reverse("intelligence-niche"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["status"], "failed")

    @patch("intelligence.tasks.refresh_pool_task.apply_async")
    @patch("intelligence.generation_services.DeepSeekClient")
    def test_empty_evidence_response_does_not_generate_ai_suggestions(self, llm, dispatch):
        pool = NichePool.objects.create(identity="empty", name="Travel")
        ChannelDNA.objects.create(
            connection=self.connection, niche_pool=pool, confirmed=True,
            expires_at=timezone.now() + timedelta(days=1),
        )
        response = self.client.post(reverse("intelligence-ideas"), {"count": 3}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["ideas"], [])
        self.assertEqual(response.data["data"]["status"], "collecting_evidence")
        llm.assert_not_called()
        dispatch.assert_called_once()

    @patch("intelligence.tasks.refresh_pool_task.apply_async")
    def test_dormant_pool_refreshes_on_request_when_statistics_exceed_one_day(self, dispatch):
        pool = NichePool.objects.create(
            identity="dormant", name="Travel", status="succeeded",
            fetched_at=timezone.now() - timedelta(hours=25),
            expires_at=timezone.now() + timedelta(hours=47),
            last_search_at=timezone.now(),
        )
        self.assertEqual(queue_pool_refresh(pool.pk), "queued")
        dispatch.assert_called_once()
