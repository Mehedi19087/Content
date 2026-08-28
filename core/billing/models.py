"""
Billing models. Two tables for live state, one append-only audit table.

Plan         -> static menu of things you can buy (seeded by `seed_plans`)
Subscription -> per-user LS subscription; the source of truth for who is paid
WebhookEvent -> append-only audit + idempotency key for LS webhooks

Why these three tables:
  - Plan decouples your code from LS's variant ids (look up by slug, not by 12345).
  - Subscription is the only place we trust to answer "is user X paid?". Groups
    are never written to directly by webhook handlers; they are always derived
    from Subscription via services.recompute_user_entitlement(). That single
    rule is what makes the system self-healing if a webhook is dropped or late.
  - WebhookEvent.event_id is the unique key LS uses to identify an event, so we
    can safely ignore replays (LS will redeliver on any non-2xx or network blip).
"""

from django.conf import settings
from django.db import models


class Plan(models.Model):
    """A purchasable tier mapped to a Django auth Group."""

    class Interval(models.TextChoices):
        MONTH = "month", "Monthly"
        YEAR = "year", "Yearly"

    slug = models.SlugField(max_length=80, unique=True)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True, default="")
    group = models.CharField(max_length=120, help_text="Django auth Group name this tier grants.")
    lemon_product_id = models.CharField(max_length=80, blank=True, default="")
    lemon_variant_id = models.CharField(max_length=80, unique=True)
    price_usd_cents = models.PositiveIntegerField(default=0)
    monthly_package_limit = models.PositiveIntegerField(default=0)
    interval = models.CharField(max_length=10, choices=Interval.choices, default=Interval.MONTH)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "price_usd_cents"]

    def __str__(self) -> str:
        return f"{self.name} ({self.slug})"


class Subscription(models.Model):
    """
    Per-user LS subscription. The subscription's status + period end are the
    only facts used to decide entitlement; groups are recomputed from them.
    """

    class Status(models.TextChoices):
        INACTIVE = "inactive", "Inactive"
        ON_TRIAL = "on_trial", "On trial"
        ACTIVE = "active", "Active"
        PAUSED = "paused", "Paused"
        PAST_DUE = "past_due", "Past due"
        CANCELLED = "cancelled", "Cancelled"
        EXPIRED = "expired", "Expired"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="billing_subscriptions",
    )
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="subscriptions")
    lemon_subscription_id = models.CharField(max_length=80, unique=True)
    lemon_customer_id = models.CharField(max_length=80, blank=True, default="")
    lemon_order_id = models.CharField(max_length=80, blank=True, default="")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.INACTIVE)
    current_period_end = models.DateTimeField(null=True, blank=True)
    trial_ends_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    is_current = models.BooleanField(default=False)
    raw_attributes = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-current_period_end"]

    def __str__(self) -> str:
        return f"Subscription {self.lemon_subscription_id} ({self.status})"


class UserPackageQuota(models.Model):
    """The user's remaining content-package allowance for one calendar month."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="package_quota",
    )
    allowance = models.PositiveIntegerField(default=0)
    remaining = models.PositiveIntegerField(default=0)
    period_start = models.DateField()
    period_end = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(remaining__lte=models.F("allowance")),
                name="package_quota_remaining_lte_allowance",
            ),
            models.CheckConstraint(
                condition=models.Q(period_start__lt=models.F("period_end")),
                name="package_quota_valid_period",
            ),
        ]

    def __str__(self) -> str:
        return f"Package quota for user {self.user_id}: {self.remaining}/{self.allowance}"


class WebhookEvent(models.Model):
    """Append-only log of every webhook LS sent us, used for idempotency."""

    event_id = models.CharField(max_length=120, unique=True)
    event_name = models.CharField(max_length=120)
    payload = models.JSONField(default=dict)
    processed = models.BooleanField(default=False)
    error = models.TextField(blank=True, default="")
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-received_at"]

    def __str__(self) -> str:
        return f"WebhookEvent {self.event_id} ({self.event_name})"
