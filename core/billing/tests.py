"""
Billing tests. All Lemon Squeezy HTTP is mocked via _patch_checkout /
_patch_portal / _patch_update / _patch_fetch. Tests must never call live LS.

Coverage map:
  - signature verification (reject forged events)
  - idempotency (replay same event_id)
  - subscription_created  -> user added to the plan's group
  - subscription_expired   -> user falls back to Free Users
  - subscription_updated  -> plan upgrade swaps the group
  - subscription_payment_success -> refreshes current_period_end
  - recompute self-heal    -> corrupted group overrides resolve to truth
  - checkout web/mobile   -> custom_data carries user_id; redirects split by platform
  - cancel                -> LS PATCH called; group stays paid until expiry webhook fires
  - tier permission hierarchy -> Free blocked, Starter blocked, Creator allowed
  - plans list            -> GET ordering respects is_active + sort_order
  - LS client missing key -> BillingConfigurationError
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import timedelta
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from billing.exceptions import BillingConfigurationError
from billing.models import Plan, Subscription, WebhookEvent
from billing.services import (
    EVENT_HANDLERS,
    handle_webhook_event,
    recompute_user_entitlement,
    verify_webhook_signature,
)


User = get_user_model()
NOW = timezone.now()
PERIOD_END_FUTURE = (NOW + timedelta(days=20)).isoformat()
PERIOD_END_PAST = (NOW - timedelta(days=1)).isoformat()


# ----------------------------------------------------------------------
# Builders for LS webhook payloads (the same shape LS actually sends)
# ----------------------------------------------------------------------

def _ls_subscription_payload(
    *,
    subscription_id: str = "sub_1",
    variant_id: str = "variant_pro",
    status: str = "active",
    renews_at: str = PERIOD_END_FUTURE,
    cancelled_at: str | None = None,
    custom_data: dict | None = None,
) -> dict:
    payload = {
        "data": {
            "id": subscription_id,
            "attributes": {
                "customer_id": "cus_1",
                "order_id": "ord_1",
                "variant_id": variant_id,
                "status": status,
                "renews_at": renews_at,
                "cancelled_at": cancelled_at,
            },
        },
        "meta": {
            "event_name": "subscription_created",
            "event_id": "evt_1",
            "custom_data": custom_data or {},
        },
    }
    return payload


def _signed_body(body: dict, secret: str = "test-secret") -> tuple[bytes, str]:
    raw = json.dumps(body).encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    return raw, sig


# ----------------------------------------------------------------------
# Base setup: authorize webhook secret + seed Free + Pro + Creator plans
# ----------------------------------------------------------------------

@override_settings(
    LEMON_SQUEEZY_WEBHOOK_SECRET="test-secret",
    LEMON_SQUEEZY_API_KEY="test-key",
    FRONTEND_BILLING_SUCCESS_URL="https://web.example.com/billing/success",
    MOBILE_BILLING_SUCCESS_URL="creatorintent://billing/success",
)
class BillingTestCase(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.plan_pro = Plan.objects.create(
            slug="pro",
            name="Pro",
            group="Pro Users",
            lemon_variant_id="variant_pro",
            price_usd_cents=4900,
            interval=Plan.Interval.MONTH,
            sort_order=2,
        )
        cls.plan_creator = Plan.objects.create(
            slug="creator",
            name="Creator",
            group="Creator Users",
            lemon_variant_id="variant_creator",
            price_usd_cents=9900,
            interval=Plan.Interval.MONTH,
            sort_order=3,
        )
        Plan.objects.create(
            slug="starter",
            name="Starter",
            group="Starter Users",
            lemon_variant_id="variant_starter",
            price_usd_cents=1900,
            interval=Plan.Interval.MONTH,
            sort_order=1,
        )
        Group.objects.get_or_create(name="Free Users")
        Group.objects.get_or_create(name="Pro Users")
        Group.objects.get_or_create(name="Creator Users")
        Group.objects.get_or_create(name="Starter Users")

    def setUp(self):
        self.user = User.objects.create_user(
            username="jane",
            email="jane@example.com",
            password="secret123",
        )
        self.client.force_authenticate(user=self.user)


# ----------------------------------------------------------------------
# Webhook endpoint signature + idempotency
# ----------------------------------------------------------------------

class WebhookSignatureTests(BillingTestCase):
    def test_rejects_invalid_signature(self):
        body, _ = _signed_body({"meta": {"event_name": "x", "event_id": "e"}}, secret="wrong")
        response = self.client.post(
            reverse("billing-webhook"),
            data=body,
            content_type="application/json",
            HTTP_X_SIGNATURE="deadbeef",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(WebhookEvent.objects.exists())

    def test_accepts_valid_signature_and_stores_event(self):
        payload = _ls_subscription_payload(custom_data={"user_id": str(self.user.id)})
        payload["data"]["attributes"]["renews_at"] = PERIOD_END_FUTURE
        payload["meta"]["event_id"] = "evt_created"
        raw, sig = _signed_body(payload)
        response = self.client.post(
            reverse("billing-webhook"),
            data=raw,
            content_type="application/json",
            HTTP_X_SIGNATURE=sig,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertTrue(WebhookEvent.objects.filter(event_id="evt_created").exists())


class WebhookIdempotencyTests(BillingTestCase):
    def test_replay_same_event_id_only_processes_once(self):
        from billing.services import handle_webhook_event

        payload = _ls_subscription_payload(custom_data={"user_id": str(self.user.id)})
        first = handle_webhook_event("evt_dup", "subscription_created", payload)
        second = handle_webhook_event("evt_dup", "subscription_created", payload)

        self.assertEqual(first, "processed")
        self.assertEqual(second, "skipped")
        self.assertEqual(WebhookEvent.objects.filter(event_id="evt_dup").count(), 1)
        self.assertEqual(Subscription.objects.filter(user=self.user).count(), 1)

    def test_failed_webhook_returns_500_and_retries_same_event(self):
        payload = {
            "meta": {"event_name": "temporary_failure", "event_id": "evt_retry"},
            "data": {"id": "sub_retry", "attributes": {}},
        }
        raw, sig = _signed_body(payload)

        failing_handler = Mock(side_effect=RuntimeError("temporary failure"))
        with patch.dict(EVENT_HANDLERS, {"temporary_failure": failing_handler}):
            first = self.client.post(
                reverse("billing-webhook"),
                data=raw,
                content_type="application/json",
                HTTP_X_SIGNATURE=sig,
            )

        self.assertEqual(first.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        event = WebhookEvent.objects.get(event_id="evt_retry")
        self.assertFalse(event.processed)
        self.assertIn("temporary failure", event.error)

        successful_handler = Mock()
        with patch.dict(EVENT_HANDLERS, {"temporary_failure": successful_handler}):
            second = self.client.post(
                reverse("billing-webhook"),
                data=raw,
                content_type="application/json",
                HTTP_X_SIGNATURE=sig,
            )

        self.assertEqual(second.status_code, status.HTTP_200_OK)
        event.refresh_from_db()
        self.assertTrue(event.processed)
        self.assertEqual(event.error, "")
        successful_handler.assert_called_once()


# ----------------------------------------------------------------------
# Webhook event handlers -> Subscription + Group behavior
# ----------------------------------------------------------------------

class WebhookEventHandlersTests(BillingTestCase):
    def test_subscription_created_adds_user_to_plan_group(self):
        payload = _ls_subscription_payload(
            variant_id="variant_pro",
            custom_data={"user_id": str(self.user.id)},
        )
        payload["meta"]["event_id"] = "evt_create"

        result = handle_webhook_event("evt_create", "subscription_created", payload)

        self.assertEqual(result, "processed")
        sub = Subscription.objects.get(lemon_subscription_id="sub_1")
        self.assertEqual(sub.plan_id, self.plan_pro.id)
        self.assertEqual(sub.status, Subscription.Status.ACTIVE)
        self.assertTrue(self.user.groups.filter(name="Pro Users").exists())
        self.assertTrue(sub.is_current)

    def test_subscription_expired_falls_back_to_free(self):
        # First land an active subscription
        created = _ls_subscription_payload(custom_data={"user_id": str(self.user.id)})
        handle_webhook_event("evt_create", "subscription_created", created)
        # Then expire it (renews_at in the past is what recompute checks).
        expired = _ls_subscription_payload(custom_data={"user_id": str(self.user.id)})
        expired["meta"]["event_id"] = "evt_expire"
        expired["meta"]["event_name"] = "subscription_expired"

        result = handle_webhook_event("evt_expire", "subscription_expired", expired)

        self.assertEqual(result, "processed")
        self.assertTrue(self.user.groups.filter(name="Free Users").exists())
        self.assertFalse(self.user.groups.filter(name="Pro Users").exists())

    def test_subscription_updated_changes_plan_and_group(self):
        # Active Pro subscription
        pro = _ls_subscription_payload(variant_id="variant_pro", custom_data={"user_id": str(self.user.id)})
        handle_webhook_event("evt_pro", "subscription_created", pro)
        self.assertTrue(self.user.groups.filter(name="Pro Users").exists())

        # Upgrade to Creator; same subscription id, different variant
        creator = _ls_subscription_payload(
            variant_id="variant_creator",
            custom_data={"user_id": str(self.user.id)},
        )
        creator["meta"]["event_name"] = "subscription_updated"
        creator["meta"]["event_id"] = "evt_update"
        result = handle_webhook_event("evt_update", "subscription_updated", creator)

        self.assertEqual(result, "processed")
        sub = Subscription.objects.get(lemon_subscription_id="sub_1")
        self.assertEqual(sub.plan_id, self.plan_creator.id)
        self.assertTrue(self.user.groups.filter(name="Creator Users").exists())
        self.assertFalse(self.user.groups.filter(name="Pro Users").exists())

    def test_payment_success_renews_period_end(self):
        # Set up an expired-end subscription, then a renewal webhook
        sub = Subscription.objects.create(
            user=self.user,
            plan=self.plan_pro,
            lemon_subscription_id="sub_1",
            status=Subscription.Status.ACTIVE,
            current_period_end=NOW - timedelta(days=2),
        )
        renewal_payload = {
            "data": {"id": "sub_1", "attributes": {"status": "active", "renews_at": PERIOD_END_FUTURE}},
            "meta": {
                "event_name": "subscription_payment_success",
                "event_id": "evt_renew",
                "subscription_id": "sub_1",
            },
        }

        result = handle_webhook_event("evt_renew", "subscription_payment_success", renewal_payload)

        self.assertEqual(result, "processed")
        sub.refresh_from_db()
        self.assertGreater(sub.current_period_end, NOW)
        self.assertTrue(self.user.groups.filter(name="Pro Users").exists())

    def test_unknown_event_name_is_stored_without_failing(self):
        payload = _ls_subscription_payload(custom_data={"user_id": str(self.user.id)})
        result = handle_webhook_event("evt_unknown", "order_created", payload)
        self.assertEqual(result, "processed")
        event = WebhookEvent.objects.get(event_id="evt_unknown")
        # We treat order_created as a no-op intentionally (one-time purchases unsupported in MVP).
        self.assertTrue(event.processed)


# ----------------------------------------------------------------------
# Self-heal helper
# ----------------------------------------------------------------------

class RecomputeEntitlementTests(BillingTestCase):
    def test_corrupted_group_overrides_heal_back_to_truth(self):
        # Inject a valid active subscription -> user should be in Pro group.
        sub = Subscription.objects.create(
            user=self.user,
            plan=self.plan_pro,
            lemon_subscription_id="sub_heal",
            status=Subscription.Status.ACTIVE,
            current_period_end=NOW + timedelta(days=10),
        )
        # Manually corrupt the user's group (pretend a buggy path set them to Free)
        free, _ = Group.objects.get_or_create(name="Free Users")
        self.user.groups.set([free])

        recompute_user_entitlement(self.user)

        self.assertTrue(self.user.groups.filter(name="Pro Users").exists())
        self.assertFalse(self.user.groups.filter(name="Free Users").exists())
        sub.refresh_from_db()
        self.assertTrue(sub.is_current)

    def test_expired_subscription_drops_to_free(self):
        Subscription.objects.create(
            user=self.user,
            plan=self.plan_pro,
            lemon_subscription_id="sub_old",
            status=Subscription.Status.EXPIRED,
            current_period_end=NOW - timedelta(days=1),
        )
        recompute_user_entitlement(self.user)
        self.assertTrue(self.user.groups.filter(name="Free Users").exists())


# ----------------------------------------------------------------------
# Checkout / status / portal / cancel views
# ----------------------------------------------------------------------

class CheckoutViewTests(BillingTestCase):
    @override_settings(LEMON_SQUEEZY_WEBHOOK_SECRET="")
    @patch("billing.services.LemonSqueezyClient.create_checkout")
    def test_checkout_refuses_payment_when_webhook_is_not_configured(self, mock_create):
        response = self.client.post(
            reverse("billing-checkout"),
            {"plan_slug": "pro", "platform": "web"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        mock_create.assert_not_called()

    @patch("billing.services.LemonSqueezyClient.create_checkout")
    def test_checkout_returns_url_and_carries_user_id(self, mock_create):
        mock_create.return_value = {
            "data": {"attributes": {"url": "https://checkout.example.com/abc"}}
        }
        response = self.client.post(
            reverse("billing-checkout"),
            {"plan_slug": "pro", "platform": "web"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual(
            response.data["data"]["checkout_url"],
            "https://checkout.example.com/abc",
        )
        # Ensure user_id was forwarded in custom_data so the webhook can resolve it
        _, kwargs = mock_create.call_args
        self.assertEqual(kwargs.get("custom_data", {}).get("user_id"), str(self.user.id))
        self.assertEqual(kwargs.get("custom_data", {}).get("plan_slug"), "pro")

    @patch("billing.services.LemonSqueezyClient.create_checkout")
    def test_checkout_mobile_passes_mobile_success_url_as_redirect(self, mock_create):
        with override_settings(
            MOBILE_BILLING_SUCCESS_URL="myapp://billing-done",
            FRONTEND_BILLING_SUCCESS_URL="https://web.example.com/done",
        ):
            mock_create.return_value = {"data": {"attributes": {"url": "https://checkout.example.com/abc"}}}
            self.client.post(
                reverse("billing-checkout"),
                {"plan_slug": "pro", "platform": "mobile"},
                format="json",
            )
        _, kwargs = mock_create.call_args
        self.assertEqual(kwargs.get("redirect_url"), "myapp://billing-done")

    def test_checkout_unknown_plan_returns_404(self):
        response = self.client.post(
            reverse("billing-checkout"),
            {"plan_slug": "nonexistent", "platform": "web"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class BillingStatusViewTests(BillingTestCase):
    def test_status_shows_pro_when_subscription_active(self):
        Subscription.objects.create(
            user=self.user,
            plan=self.plan_pro,
            lemon_subscription_id="sub_status",
            status=Subscription.Status.ACTIVE,
            current_period_end=NOW + timedelta(days=10),
            is_current=True,
        )
        response = self.client.get(reverse("billing-status"))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual(response.data["data"]["plan"], "pro")
        self.assertEqual(response.data["data"]["group"], "Pro Users")

    def test_status_shows_free_without_subscription(self):
        response = self.client.get(reverse("billing-status"))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual(response.data["data"]["group"], "Free Users")
        self.assertIsNone(response.data["data"]["plan"])


class PortalViewTests(BillingTestCase):
    @patch("billing.services.LemonSqueezyClient.generate_customer_portal_url")
    def test_portal_returns_customer_portal_url(self, mock_portal):
        Subscription.objects.create(
            user=self.user,
            plan=self.plan_pro,
            lemon_subscription_id="sub_p",
            status=Subscription.Status.ACTIVE,
            current_period_end=NOW + timedelta(days=10),
        )
        mock_portal.return_value = "https://ls.example.com/portal/abc"
        response = self.client.post(reverse("billing-portal"), format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual(response.data["data"]["portal_url"], "https://ls.example.com/portal/abc")

    def test_portal_without_subscription_returns_404(self):
        response = self.client.post(reverse("billing-portal"), format="json")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class CancelViewTests(BillingTestCase):
    @patch("billing.services.LemonSqueezyClient.update_subscription")
    def test_cancel_calls_ls_patch_and_keeps_access_until_expiry(self, mock_update):
        sub = Subscription.objects.create(
            user=self.user,
            plan=self.plan_pro,
            lemon_subscription_id="sub_c",
            status=Subscription.Status.ACTIVE,
            current_period_end=NOW + timedelta(days=15),  # paid beyond today
        )
        response = self.client.post(reverse("billing-cancel"), format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        # LS got the cancel-at-period-end PATCH
        mock_update.assert_called_once()
        _, kwargs = mock_update.call_args
        self.assertEqual(kwargs.get("cancelled"), True)
        # User keeps Pro access until expiry (recompute only cares about status +
        # current_period_end, not cancelled_at)
        sub.refresh_from_db()
        self.assertEqual(sub.status, Subscription.Status.CANCELLED)
        self.assertIsNotNone(sub.cancelled_at)
        self.assertTrue(self.user.groups.filter(name="Pro Users").exists())

    def test_cancel_without_subscription_returns_404(self):
        response = self.client.post(reverse("billing-cancel"), format="json")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


# ----------------------------------------------------------------------
# Plans listing
# ----------------------------------------------------------------------

class PlansViewTests(BillingTestCase):
    def test_list_plans_active_in_sort_order(self):
        response = self.client.get(reverse("billing-plans"))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        slugs = [plan["slug"] for plan in response.data["data"]]
        self.assertEqual(slugs, ["starter", "pro", "creator"])


# ----------------------------------------------------------------------
# Tier permission hierarchy end-to-end via existing idea endpoints
# ----------------------------------------------------------------------

class TierPermissionHierarchyTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        from categories.models import Category
        from ideas.models import IdeaCandidate
        cls.category = Category.objects.create(
            name="AI & Automation",
            slug="ai-automation",
            youtube_category_ids=["28"],
            youtube_category_titles=["Science & Technology"],
            search_keywords=["ai tools", "chatgpt"],
            negative_keywords=["iphone"],
            default_regions=["US"],
        )
        cls.idea = IdeaCandidate.objects.create(
            category=cls.category,
            region_code="US",
            title="I Tested 7 AI Tools That Save Creators Time",
            why_now="Trend up",
            audience_promise="Help creators",
            suggested_format="Test",
            difficulty=IdeaCandidate.Difficulty.MEDIUM,
            freshness=IdeaCandidate.Freshness.HIGH,
            trend_score=86,
            source_signal="signal",
            source_video_count=12,
            evidence_video_ids=["abc123"],
            risk_flags=[],
        )

    def _authenticate_user_in_group(self, group_name: str | None):
        user = User.objects.create_user(
            username=f"u-{group_name or 'anon'}",
            email=f"{group_name or 'anon'}@example.com",
            password="secret123",
        )
        if group_name:
            group, _ = Group.objects.get_or_create(name=group_name)
            user.groups.add(group)
        self.client.force_authenticate(user=user)

    def test_free_user_can_view_trending_but_not_research_intent(self):
        self._authenticate_user_in_group("Free Users")
        # GET trending -> 200 (Free tier OK)
        response = self.client.get(
            reverse("ideas-trending"),
            {"category_slug": "ai-automation", "region_code": "US"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)

        # YouTube intent research -> 403 (Starter tier required)
        response = self.client.post(
            reverse("ideas-youtube-intent"),
            {"idea": "AI tools for creators", "region_code": "US"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_creator_unlocks_all_lower_tier_endpoints(self):
        self._authenticate_user_in_group("Creator Users")
        # Intent research requires Starter; a Creator user should pass.
        with patch(
            "ideas.views.research_youtube_intent_for_idea",
            return_value={
                "viewer_intent": "Creators want useful AI tools",
                "content_type": "tool recommendation",
                "search_suggestions": [],
                "title_patterns": [],
                "emotional_angles": [],
                "thumbnail_subjects": [],
                "seo_keywords": [],
            },
        ):
            response = self.client.post(
                reverse("ideas-youtube-intent"),
                {"idea": "AI tools for creators", "region_code": "US"},
                format="json",
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)


# ----------------------------------------------------------------------
# LS client smoke test: missing API key -> BillingConfigurationError
# ----------------------------------------------------------------------

class ClientConfigTests(BillingTestCase):
    @patch("billing.client.requests.request")
    def test_create_checkout_uses_lemon_squeezy_json_api_schema(self, mock_request):
        from billing.client import LemonSqueezyClient

        response = Mock()
        response.status_code = 201
        response.content = b'{"data":{"attributes":{"url":"https://example.com"}}}'
        response.json.return_value = {
            "data": {"attributes": {"url": "https://example.com"}}
        }
        mock_request.return_value = response

        LemonSqueezyClient(api_key="test-key", store_id="123").create_checkout(
            variant_id="456",
            custom_data={"user_id": "7", "plan_slug": "pro"},
            redirect_url="https://creatorintent.com/billing/success",
            email="creator@example.com",
            name="Test Creator",
        )

        payload = mock_request.call_args.kwargs["json"]["data"]
        attributes = payload["attributes"]
        self.assertNotIn("custom_data", attributes)
        self.assertNotIn("email", attributes)
        self.assertNotIn("name", attributes)
        self.assertEqual(
            attributes["checkout_data"],
            {
                "custom": {"user_id": "7", "plan_slug": "pro"},
                "email": "creator@example.com",
                "name": "Test Creator",
            },
        )
        self.assertEqual(
            attributes["product_options"],
            {"redirect_url": "https://creatorintent.com/billing/success"},
        )
        self.assertNotIn("checkout_options", attributes)
        self.assertEqual(
            payload["relationships"],
            {
                "store": {"data": {"type": "stores", "id": "123"}},
                "variant": {"data": {"type": "variants", "id": "456"}},
            },
        )

    def test_missing_api_key_raises_configuration_error(self):
        # Strip every key source (env AND settings override from the test class).
        from billing.client import LemonSqueezyClient

        env_backup = dict(
            (k, v) for k, v in os.environ.items()
            if k.startswith("LEMON_SQUEEZY")
        )
        try:
            for k in env_backup:
                os.environ.pop(k, None)
            from django.test import override_settings as _ord
            with _ord(LEMON_SQUEEZY_API_KEY=""):
                with self.assertRaises(BillingConfigurationError):
                    LemonSqueezyClient()
        finally:
            os.environ.update(env_backup)
