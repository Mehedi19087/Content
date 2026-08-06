"""
Billing views. Thin view layer only: validate input, call services, shape
output. Same pattern as ideas/views.py — every handler is a small wrapper
that does serializer.is_valid() + service call + Response(...).

The webhook view is special:
  - public (no JWT), like the Google callback in users/views.py
  - must verify the HMAC signature before ANY parsing (request.body must stay raw)
  - always returns 200 for known events, even unknown event_names (LS retries
    on non-2xx, and we already logged + flagged unknown events in the audit row)
"""

import json
import logging

from rest_framework import permissions, status
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from .exceptions import BillingConfigurationError, WebhookSignatureError
from .serializers import (
    BillingStatusSerializer,
    CancelResponseSerializer,
    CheckoutRequestSerializer,
    CheckoutResponseSerializer,
    PlanSerializer,
    PortalResponseSerializer,
)
from .services import (
    cancel_subscription,
    create_checkout_url,
    get_billing_status,
    get_plans,
    handle_webhook_event,
    open_portal,
    verify_webhook_signature,
)

logger = logging.getLogger("billing.views")


class PlansAPIView(APIView):
    """GET /api/billing/plans/ — list purchasable plans."""

    def get(self, request):
        plans = get_plans()
        serializer = PlanSerializer(plans, many=True)
        return Response(
            {
                "message": "plans retrieved successfully",
                "data": serializer.data,
            },
            status=status.HTTP_200_OK,
        )


class CheckoutAPIView(APIView):
    """POST /api/billing/checkout/ — return a LS hosted checkout URL."""

    def post(self, request):
        serializer = CheckoutRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            url = create_checkout_url(
                user=request.user,
                plan_slug=serializer.validated_data["plan_slug"],
                platform=serializer.validated_data["platform"],
            )
            response_serializer = CheckoutResponseSerializer({"checkout_url": url})
            return Response(
                {
                    "message": "checkout url generated successfully",
                    "data": response_serializer.data,
                },
                status=status.HTTP_200_OK,
            )
        except APIException:
            raise
        except BillingConfigurationError as exc:
            return Response(
                {"message": str(exc)},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except Exception as exc:
            logger.exception("billing.checkout.failed user=%s", request.user.id)
            return Response(
                {
                    "message": "Failed to start checkout.",
                    "detail": str(exc),
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )


class BillingStatusAPIView(APIView):
    """GET /api/billing/status/ — show the current user's subscription state."""

    def get(self, request):
        result = get_billing_status(user=request.user)
        serializer = BillingStatusSerializer(result)
        return Response(
            {
                "message": "billing status retrieved successfully",
                "data": serializer.data,
            },
            status=status.HTTP_200_OK,
        )


class PortalAPIView(APIView):
    """POST /api/billing/portal/ — return a LS customer-portal URL."""

    def post(self, request):
        try:
            url = open_portal(user=request.user)
            serializer = PortalResponseSerializer({"portal_url": url})
            return Response(
                {
                    "message": "portal url generated successfully",
                    "data": serializer.data,
                },
                status=status.HTTP_200_OK,
            )
        except APIException:
            raise
        except BillingConfigurationError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except Exception as exc:
            logger.exception("billing.portal.failed user=%s", request.user.id)
            return Response(
                {"message": "Failed to open billing portal.", "detail": str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )


class CancelAPIView(APIView):
    """POST /api/billing/cancel/ — cancel at period end. Access stays until renewal."""

    def post(self, request):
        try:
            sub = cancel_subscription(user=request.user)
            response_serializer = CancelResponseSerializer(
                {
                    "message": "subscription will cancel at period end",
                    "cancelled_at": sub.cancelled_at,
                    "current_period_end": sub.current_period_end,
                }
            )
            return Response(
                response_serializer.data,
                status=status.HTTP_200_OK,
            )
        except APIException:
            raise
        except BillingConfigurationError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except Exception as exc:
            logger.exception("billing.cancel.failed user=%s", request.user.id)
            return Response(
                {"message": "Failed to cancel subscription.", "detail": str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )


class WebhookAPIView(APIView):
    """
    POST /api/billing/webhook/ — Lemon Squeezy forwards events here.
    Public (no JWT). Signature is verified BEFORE parsing the body so forged
    events can never reach the dispatcher. Always returns 200 for parsed
    events (LS only retries on non-2xx; failed handlers are recorded to the
    WebhookEvent.row.error and can be either retried by LS or replayed by an
    admin via the dashboard).
    """

    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        raw_body = request.body
        signature = request.headers.get("X-Signature") or request.META.get("HTTP_X_SIGNATURE")

        try:
            verify_webhook_signature(raw_body, signature)
        except (WebhookSignatureError, BillingConfigurationError) as exc:
            logger.warning("billing.webhook.signature_rejected reason=%s", exc)
            return Response({"message": "signature verification failed"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            logger.warning("billing.webhook.bad_body")
            return Response({"message": "invalid JSON"}, status=status.HTTP_400_BAD_REQUEST)

        meta = payload.get("meta") or {}
        event_name = meta.get("event_name") or payload.get("event_name") or ""
        event_id = meta.get("event_id") or payload.get("event_id") or ""

        try:
            result = handle_webhook_event(
                event_id=str(event_id),
                event_name=str(event_name),
                payload=payload,
            )
        except APIException as exc:
            return Response(
                {"message": "validation error", "detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {"message": "webhook received", "event_id": event_id, "status": result},
            status=status.HTTP_200_OK,
        )