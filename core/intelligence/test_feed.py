from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from django.urls import reverse
from rest_framework.test import APIClient

from youtube_channels.models import YouTubeChannel
from .models import ChannelDNA, CreatorIdeaFeed
from .feed_services import daily_ideas


class DailyFeedTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="feed-user")
        connection = YouTubeChannel.objects.create(user=self.user, youtube_channel_id="own",
            title="Own", uploads_playlist_id="uploads", encrypted_refresh_token="unused")
        self.dna = ChannelDNA.objects.create(connection=connection, confirmed=True,
            profile={"core_topic": "Travel"})
        self.mock = patch("intelligence.feed_services.generate_ideas").start()
        self.addCleanup(patch.stopall)
        self.mock.return_value = self.batch("one", "two", "three", "four")

    def batch(self, *titles, status="ready"):
        return {"ideas": [{"id": n, "idea": title,
            "evidence_expires_at": (timezone.now()+timedelta(hours=20)).isoformat(),
            "data_timestamp": timezone.now().isoformat(), "evidence_mode": "LIMITED_EVIDENCE"}
            for n, title in enumerate(titles)], "status": status, "message": "",
            "evidence_mode": "LIMITED_EVIDENCE", "data_timestamp": None,
            "refresh_status": "not_needed", "creator_refresh_status": "not_needed"}

    def test_repeated_visits_and_legacy_posts_reuse_same_three_ideas(self):
        client = APIClient()
        client.force_authenticate(self.user)
        first = client.get(reverse("intelligence-ideas"))
        second = client.post(reverse("intelligence-ideas"), {"count": 10})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.data, second.data)
        self.assertEqual(len(first.data["data"]["ideas"]), 3)
        self.mock.assert_called_once_with(user_id=self.user.pk, count=6, provider_timeout=30)

    def test_underfilled_first_batch_gets_one_top_up_and_removes_duplicates(self):
        self.mock.side_effect = [self.batch("one", "two"), self.batch("one", "three")]
        result = daily_ideas(user_id=self.user.pk)
        self.assertEqual([i["idea"] for i in result["ideas"]], ["one", "two", "three"])
        self.assertEqual(result["status"], "ready")
        self.assertEqual(self.mock.call_count, 2)

    def test_insufficient_candidates_never_cause_unbounded_retries(self):
        self.mock.return_value = self.batch("one")
        result = daily_ideas(user_id=self.user.pk)
        daily_ideas(user_id=self.user.pk)
        self.assertEqual(result["status"], "limited")
        self.assertEqual(self.mock.call_count, 2)

    def test_active_reservation_prevents_duplicate_generation(self):
        CreatorIdeaFeed.objects.create(dna=self.dna, requested_at=timezone.now())
        self.assertEqual(daily_ideas(user_id=self.user.pk)["status"], "preparing")
        self.mock.assert_not_called()

    def test_expired_set_refreshes_once_and_uses_new_due_time(self):
        daily_ideas(user_id=self.user.pk)
        CreatorIdeaFeed.objects.update(next_refresh_at=timezone.now()-timedelta(seconds=1))
        daily_ideas(user_id=self.user.pk)
        daily_ideas(user_id=self.user.pk)
        self.assertEqual(self.mock.call_count, 2)

    def test_profile_change_cannot_bypass_paid_generation_cooldown(self):
        daily_ideas(user_id=self.user.pk)
        self.dna.profile = {"core_topic": "AI"}
        self.dna.save()
        result = daily_ideas(user_id=self.user.pk)
        self.assertEqual(result["status"], "scheduled")
        self.assertEqual(result["ideas"], [])
        self.assertEqual(self.mock.call_count, 1)

    def test_provider_failure_has_retry_cooldown(self):
        self.mock.side_effect = RuntimeError("Provider down")
        first = daily_ideas(user_id=self.user.pk)
        second = daily_ideas(user_id=self.user.pk)
        self.assertEqual(first, second)
        self.assertEqual(first["status"], "scheduled")
        self.assertEqual(self.mock.call_count, 1)

    def test_collection_pending_does_not_call_model_again_for_top_up(self):
        self.mock.return_value = self.batch(status="collecting_evidence")
        result = daily_ideas(user_id=self.user.pk)
        self.assertEqual(result["status"], "collecting_evidence")
        self.assertEqual(self.mock.call_count, 1)

    def test_another_account_cannot_read_this_feed(self):
        daily_ideas(user_id=self.user.pk)
        other = get_user_model().objects.create_user(username="other-feed")
        client = APIClient()
        client.force_authenticate(other)
        response = client.get(reverse("intelligence-ideas"))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.mock.call_count, 1)
