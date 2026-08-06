from django.urls import path

from .views import (
    BillingStatusAPIView,
    CancelAPIView,
    CheckoutAPIView,
    PlansAPIView,
    PortalAPIView,
    WebhookAPIView,
)


urlpatterns = [
    path("billing/plans/", PlansAPIView.as_view(), name="billing-plans"),
    path("billing/checkout/", CheckoutAPIView.as_view(), name="billing-checkout"),
    path("billing/status/", BillingStatusAPIView.as_view(), name="billing-status"),
    path("billing/portal/", PortalAPIView.as_view(), name="billing-portal"),
    path("billing/cancel/", CancelAPIView.as_view(), name="billing-cancel"),
    path("billing/webhook/", WebhookAPIView.as_view(), name="billing-webhook"),
]