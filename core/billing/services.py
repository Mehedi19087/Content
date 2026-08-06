"""
Billing business logic. The single rule that makes this reliable:

    Subscription.status/current_period_end is the source of truth.
    Groups are never written directly; recompute_user_entitlement() derives
    them from Subscription. Webhook handlers do the upsert, then call recompute.

Webhook dispatch table:
    Each LS event_name maps to one handler. Every handler does:
      1. Pull user_id + variant_id + status + dates from the LS payload.
      2. Upsert the Subscription row.
      3. Call recompute_user_entitlement(user).

handle_webhook_event() wraps the handler with idempotency (skip already-seen
event_ids) and audit logging (always store WebhookEvent), so handlers can stay
focused on state mutation.

Public helpers used by views:
    - get_plans()
    - create_checkout_url(user, plan_slug, platform)
    - open_portal(user)
    - cancel_subscription(user)
    - get_billing_status(user)
    - recompute_user_entitlement(user)
    - handle_webhook_event(event_id, event_name, payload)
    - verify_webhook_signature(raw_body, signature_header)
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound, ValidationError

from .client import LemonSqueezyClient
from .exceptions import BillingAPIError, BillingConfigurationError, WebhookSignatureError
from .models import Plan, Subscription, WebhookEvent


logger = logging.getLogger("billing.services")
User = get_user_model()

FREE_GROUP = "Free Users"
ACTIVE_GRANTING_STATUSES = (
    Subscription.Status.ACTIVE,
    Subscription.Status.ON_TRIAL,
    Subscription.Status.PAST_DUE,
    Subscription.Status.PAUSED,
    # CANCELLED subscriptions still grant access until current_period_end
    # passes — this mirrors Lemon Squeezy's "cancel at period end" semantics.
    # Once LS fires subscription_expired (when the period actually lapses),
    # status flips to EXPIRED which is NOT in this set, and recompute drops
    # the user back to Free Users.
    Subscription.Status.CANCELLED,
)


# ----------------------------------------------------------------------
# Self-healing helper: the heart of the design
# ----------------------------------------------------------------------

def recompute_user_entitlement(user) -> None:
    """
    Look at all the user's subscriptions and set their Django Group to match.
    Called after every webhook event and on every GET /billing/status call,
    so even if a webhook is dropped or out of order, the next call heals it.
    """
    now = timezone.now()
    chosen = (
        Subscription.objects.select_related("plan")
        .filter(user=user, status__in=ACTIVE_GRANTING_STATUSES)
        .filter(current_period_end__isnull=False, current_period_end__gt=now)
        .order_by("-current_period_end")
        .first()
    )

    # Mark only the chosen one as current — useful for admin/views.
    with transaction.atomic():
        Subscription.objects.filter(user=user, is_current=True).update(is_current=False)
        if chosen:
            target_group_name = chosen.plan.group
            chosen.is_current = True
            chosen.save(update_fields=["is_current"])
        else:
            target_group_name = FREE_GROUP

        group, _ = Group.objects.get_or_create(name=target_group_name)
        user.groups.set([group])


# ----------------------------------------------------------------------
# LS payload parsing helpers
# ----------------------------------------------------------------------

def _attributes(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data") or {}
    return data.get("attributes") or {}


def _meta(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Lemon Squeezy puts `meta` at the TOP level of a webhook body:
        {"meta": {...}, "data": {...}}
    Some LS API responses nest `meta` under `data.meta` instead, so we
    accept both so the same handler code is reused by webhook + sync paths.
    """
    meta = payload.get("meta")
    if isinstance(meta, dict):
        return meta
    data = payload.get("data") or {}
    nested = data.get("meta")
    return nested if isinstance(nested, dict) else {}


def _custom_data(payload: dict[str, Any]) -> dict[str, Any]:
    # LS echoes custom_data on the resource (data.attributes.custom_data) AND
    # in the webhook meta. Prefer the resource's copy; fall back to meta.
    attrs = _attributes(payload)
    cd = attrs.get("custom_data")
    if not isinstance(cd, dict):
        cd = _meta(payload).get("custom_data") or {}
    return cd if isinstance(cd, dict) else {}


def _parse_dt(value: Any):
    if not value:
        return None
    if isinstance(value, dict):
        value = value.get("date_time") or value.get("iso8601")
    if value is None:
        return None
    try:
        return timezone.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _resolve_plan_from_variant(variant_id: str | None) -> Plan:
    if not variant_id:
        raise ValidationError({"variant_id": "Webhook payload is missing variant_id."})
    plan = Plan.objects.filter(lemon_variant_id=str(variant_id)).first()
    if plan is None:
        raise ValidationError(
            {"plan": f"No Plan configured for lemon_variant_id={variant_id}."}
        )
    return plan


def _find_user(user_id: Any):
    if not user_id:
        return None
    try:
        return User.objects.filter(id=user_id).first()
    except (ValueError, TypeError):
        return None


def _upsert_subscription(
    *,
    user,
    plan: Plan,
    lemon_subscription_id: str,
    attributes: dict[str, Any],
) -> Subscription:
    status = str(attributes.get("status") or Subscription.Status.INACTIVE).lower()
    if status not in dict(Subscription.Status.choices):
        status = Subscription.Status.INACTIVE

    defaults = {
        "user": user,
        "plan": plan,
        "lemon_customer_id": str(attributes.get("customer_id") or ""),
        "lemon_order_id": str(attributes.get("order_id") or ""),
        "status": status,
        "current_period_end": _parse_dt(attributes.get("renews_at") or attributes.get("ends_at")),
        "trial_ends_at": _parse_dt(attributes.get("trial_ends_at")),
        "cancelled_at": _parse_dt(attributes.get("cancelled_at") or attributes.get("ends_at")),
        "raw_attributes": attributes,
    }
    sub, _ = Subscription.objects.update_or_create(
        lemon_subscription_id=str(lemon_subscription_id),
        defaults=defaults,
    )
    return sub


# ----------------------------------------------------------------------
# Webhook event handlers
# ----------------------------------------------------------------------

def apply_subscription_created(event: WebhookEvent, payload: dict[str, Any]) -> None:
    attrs = _attributes(payload)
    sub_id = payload.get("data", {}).get("id") or attrs.get("subscription_id")
    cd = _custom_data(payload)
    user = _find_user(cd.get("user_id"))
    plan = _resolve_plan_from_variant(attrs.get("variant_id") or cd.get("plan_variant_id"))
    if user is None:
        raise ValidationError({"user_id": "subscription_created: user_id not found in custom_data."})
    _upsert_subscription(
        user=user,
        plan=plan,
        lemon_subscription_id=str(sub_id),
        attributes=attrs,
    )
    recompute_user_entitlement(user)


def apply_subscription_updated(event: WebhookEvent, payload: dict[str, Any]) -> None:
    attrs = _attributes(payload)
    sub_id = payload.get("data", {}).get("id")
    cd = _custom_data(payload)
    user = _find_user(cd.get("user_id"))
    plan = _resolve_plan_from_variant(attrs.get("variant_id") or cd.get("plan_variant_id"))
    sub = Subscription.objects.filter(lemon_subscription_id=str(sub_id)).first()
    if sub is not None:
        user = user or sub.user
    if user is None:
        raise ValidationError({"user_id": "subscription_updated: cannot resolve user."})
    _upsert_subscription(
        user=user,
        plan=plan,
        lemon_subscription_id=str(sub_id),
        attributes=attrs,
    )
    recompute_user_entitlement(user)


def apply_subscription_cancelled(event: WebhookEvent, payload: dict[str, Any]) -> None:
    attrs = _attributes(payload)
    sub_id = payload.get("data", {}).get("id")
    sub = Subscription.objects.filter(lemon_subscription_id=str(sub_id)).first()
    if sub is None:
        return
    sub.status = Subscription.Status.CANCELLED
    sub.cancelled_at = _parse_dt(attrs.get("cancelled_at") or attrs.get("ends_at")) or timezone.now()
    sub.raw_attributes = attrs
    sub.save(update_fields=["status", "cancelled_at", "raw_attributes", "updated_at"])
    recompute_user_entitlement(sub.user)


def apply_subscription_expired(event: WebhookEvent, payload: dict[str, Any]) -> None:
    sub_id = payload.get("data", {}).get("id")
    sub = Subscription.objects.filter(lemon_subscription_id=str(sub_id)).first()
    if sub is None:
        return
    sub.status = Subscription.Status.EXPIRED
    sub.raw_attributes = _attributes(payload)
    sub.save(update_fields=["status", "raw_attributes", "updated_at"])
    # CANCELLED subscriptions with their period_end passed should drop entitlement — recompute handles it.
    recompute_user_entitlement(sub.user)


def apply_subscription_paused(event: WebhookEvent, payload: dict[str, Any]) -> None:
    sub_id = payload.get("data", {}).get("id")
    sub = Subscription.objects.filter(lemon_subscription_id=str(sub_id)).first()
    if sub is None:
        return
    sub.status = Subscription.Status.PAUSED
    sub.raw_attributes = _attributes(payload)
    sub.save(update_fields=["status", "raw_attributes", "updated_at"])
    recompute_user_entitlement(sub.user)


def apply_subscription_resumed(event: WebhookEvent, payload: dict[str, Any]) -> None:
    sub_id = payload.get("data", {}).get("id")
    sub = Subscription.objects.filter(lemon_subscription_id=str(sub_id)).first()
    if sub is None:
        return
    sub.status = Subscription.Status.ACTIVE
    sub.raw_attributes = _attributes(payload)
    sub.save(update_fields=["status", "raw_attributes", "updated_at"])
    recompute_user_entitlement(sub.user)


def apply_subscription_payment_success(event: WebhookEvent, payload: dict[str, Any]) -> None:
    """
    Payment success refreshes current_period_end. The subscription id lives
    under meta.subscription_id (LS order events) when this event arrives as an
    order_payment event. We try both shapes defensively.
    """
    cd = _custom_data(payload)
    meta = _meta(payload)
    sub_id = (
        meta.get("subscription_id")
        or payload.get("data", {}).get("id")
        or cd.get("subscription_id")
    )
    sub = Subscription.objects.filter(lemon_subscription_id=str(sub_id)).first()
    if sub is None:
        return
    attrs = _attributes(payload)
    new_end = _parse_dt(attrs.get("renews_at") or attrs.get("ends_at"))
    if new_end:
        sub.current_period_end = new_end
    sub.status = Subscription.Status.ACTIVE
    sub.raw_attributes = attrs
    sub.save(update_fields=["status", "current_period_end", "raw_attributes", "updated_at"])
    recompute_user_entitlement(sub.user)


def apply_subscription_payment_failed(event: WebhookEvent, payload: dict[str, Any]) -> None:
    sub_id = payload.get("data", {}).get("id")
    sub = Subscription.objects.filter(lemon_subscription_id=str(sub_id)).first()
    if sub is None:
        return
    sub.status = Subscription.Status.PAST_DUE
    sub.raw_attributes = _attributes(payload)
    sub.save(update_fields=["status", "raw_attributes", "updated_at"])
    recompute_user_entitlement(sub.user)


EVENT_HANDLERS = {
    "subscription_created": apply_subscription_created,
    "subscription_updated": apply_subscription_updated,
    "subscription_cancelled": apply_subscription_cancelled,
    "subscription_expired": apply_subscription_expired,
    "subscription_paused": apply_subscription_paused,
    "subscription_resumed": apply_subscription_resumed,
    "subscription_payment_success": apply_subscription_payment_success,
    "subscription_payment_failed": apply_subscription_payment_failed,
    # LS also fires an order_created event for one-time purchases; not used
    # for the subscriptions-only MVP, but we accept it without effect so the
    # webhook returns 200 instead of erroring.
    "order_created": lambda e, p: None,
}


@transaction.atomic
def handle_webhook_event(event_id: str, event_name: str, payload: dict[str, Any]) -> str:
    """
    Idempotent webhook dispatcher.

    Returns one of:
      - "skipped":   event_id already processed elsewhere
      - "processed": handler ran successfully
      - "unknown":   event_name we don't handle (still stored as audit)
      - "failed":    handler raised; WebhookEvent.error populated, will retry
    """
    if not event_id:
        raise ValidationError({"event_id": "Webhook payload is missing event_id."})

    existing = WebhookEvent.objects.filter(event_id=event_id).first()
    if existing is not None:
        return "skipped"

    event = WebhookEvent.objects.create(
        event_id=event_id,
        event_name=event_name,
        payload=payload,
        processed=False,
    )

    handler = EVENT_HANDLERS.get(event_name)
    if handler is None:
        event.processed = True
        event.error = f"Unknown event_name: {event_name}"
        event.save(update_fields=["processed", "error"])
        logger.info("billing.webhook.unknown event_id=%s name=%s", event_id, event_name)
        return "unknown"

    try:
        handler(event, payload)
    except Exception as exc:
        event.error = str(exc)
        event.save(update_fields=["error"])
        logger.exception("billing.webhook.failed event_id=%s name=%s", event_id, event_name)
        return "failed"

    event.processed = True
    event.save(update_fields=["processed"])
    return "processed"


# ----------------------------------------------------------------------
# Signature verification
# ----------------------------------------------------------------------

def verify_webhook_signature(raw_body: bytes, signature_header: str | None) -> None:
    """
    Verify the X-Signature HMAC-SHA256 header LS sends on every webhook.
    Must be called before request body is parsed (raw_body = request.body).
    Raises on mismatch; doing so is the only defense against forged events.
    """
    secret = settings.LEMON_SQUEEZY_WEBHOOK_SECRET
    if not secret:
        raise BillingConfigurationError("LEMON_SQUEEZY_WEBHOOK_SECRET is not configured.")

    if not signature_header:
        raise WebhookSignatureError("Missing X-Signature header.")

    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, str(signature_header)):
        raise WebhookSignatureError("Webhook signature mismatch.")


# ----------------------------------------------------------------------
# View-facing helpers
# ----------------------------------------------------------------------

def get_plans():
    return list(Plan.objects.filter(is_active=True))


def create_checkout_url(*, user, plan_slug: str, platform: str = "web") -> str:
    plan = Plan.objects.filter(slug=plan_slug, is_active=True).first()
    if plan is None:
        raise NotFound("Plan not found.")

    success_url = (
        settings.MOBILE_BILLING_SUCCESS_URL
        if platform == "mobile"
        else settings.FRONTEND_BILLING_SUCCESS_URL
    )
    cancel_url = settings.FRONTEND_BILLING_CANCEL_URL

    custom_data = {"user_id": str(user.id), "plan_slug": plan.slug}

    client = LemonSqueezyClient()
    response = client.create_checkout(
        variant_id=plan.lemon_variant_id,
        custom_data=custom_data,
        redirect_url=success_url or None,
        cancel_url=cancel_url or None,
        email=getattr(user, "email", None) or None,
        name=(f"{user.first_name} {user.last_name}".strip() or None),
    )
    url = (response.get("data") or {}).get("attributes", {}).get("url")
    if not url:
        raise BillingAPIError("Lemon Squeezy did not return a checkout URL.")
    return url


def open_portal(*, user) -> str:
    sub = (
        Subscription.objects.filter(user=user)
        .exclude(lemon_subscription_id="")
        .order_by("-current_period_end")
        .first()
    )
    if sub is None:
        raise NotFound("No active subscription to manage.")
    client = LemonSqueezyClient()
    return client.generate_customer_portal_url(sub.lemon_subscription_id)


def cancel_subscription(*, user) -> Subscription:
    sub = (
        Subscription.objects.select_related("plan")
        .filter(user=user, is_current=True)
        .first()
    )
    if sub is None:
        sub = (
            Subscription.objects.select_related("plan")
            .filter(user=user)
            .order_by("-current_period_end")
            .first()
        )
    if sub is None:
        raise NotFound("No subscription to cancel.")
    client = LemonSqueezyClient()
    client.update_subscription(sub.lemon_subscription_id, cancelled=True)
    sub.cancelled_at = timezone.now()
    sub.status = Subscription.Status.CANCELLED
    sub.save(update_fields=["cancelled_at", "status", "updated_at"])
    # Recompute — but the user stays in the paid group until current_period_end,
    # because recompute cares about status + current_period_end, not cancelled_at.
    recompute_user_entitlement(user)
    return sub


def get_billing_status(*, user) -> dict[str, Any]:
    recompute_user_entitlement(user)
    sub = (
        Subscription.objects.select_related("plan")
        .filter(user=user, is_current=True)
        .first()
    )
    group = user.groups.first()
    return {
        "plan": sub.plan.slug if sub else None,
        "plan_name": sub.plan.name if sub else None,
        "group": group.name if group else FREE_GROUP,
        "status": sub.status if sub else None,
        "current_period_end": sub.current_period_end if sub else None,
        "cancelled_at": sub.cancelled_at if sub else None,
        "lemon_subscription_id": sub.lemon_subscription_id if sub else None,
    }