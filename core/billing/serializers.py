"""
Billing serializers. Same shape as categories/serializers.py and
ideas/serializers.py — small serializer per response / request, no business
logic. Datetimes are returned in ISO 8601 so the frontend can parse them.
"""

from rest_framework import serializers

from .models import Plan, Subscription


class PlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = Plan
        fields = [
            "id",
            "slug",
            "name",
            "description",
            "group",
            "price_usd_cents",
            "interval",
            "is_active",
            "sort_order",
        ]


class CheckoutRequestSerializer(serializers.Serializer):
    plan_slug = serializers.SlugField(max_length=80)
    platform = serializers.ChoiceField(choices=["web", "mobile"], default="web")


class CheckoutResponseSerializer(serializers.Serializer):
    checkout_url = serializers.URLField()


class BillingStatusSerializer(serializers.Serializer):
    plan = serializers.CharField(allow_null=True)
    plan_name = serializers.CharField(allow_null=True)
    group = serializers.CharField()
    status = serializers.CharField(allow_null=True)
    current_period_end = serializers.DateTimeField(allow_null=True)
    cancelled_at = serializers.DateTimeField(allow_null=True)
    lemon_subscription_id = serializers.CharField(allow_null=True)


class PortalResponseSerializer(serializers.Serializer):
    portal_url = serializers.URLField()


class CancelResponseSerializer(serializers.Serializer):
    message = serializers.CharField()
    cancelled_at = serializers.DateTimeField(allow_null=True)
    current_period_end = serializers.DateTimeField(allow_null=True)


class WebhookAckSerializer(serializers.Serializer):
    message = serializers.CharField()
    event_id = serializers.CharField(allow_null=True)
    status = serializers.CharField()