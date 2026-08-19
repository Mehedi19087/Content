"""
Lemon Squeezy HTTP client. Adapter layer only — talks to LS, returns plain
dicts, knows nothing about Django models, users, or groups. Mirrors the
isolation pattern used by youtube_channels/youtube_client.py.

Four operations are needed for MVP subscriptions:
  - create_checkout               POST /v1/checkouts
  - generate_customer_portal_url  POST /v1/subscriptions/{id}/generate-customer-portal
  - fetch_subscription             GET /v1/subscriptions/{id}
  - update_subscription           PATCH /v1/subscriptions/{id}

All HTTP calls go through _request(), which centralizes auth header, timeout,
and error mapping. LS returns errors as JSON with an "errors" array; we surface
the first message so a single string can be shown to the user / logged.
"""

from __future__ import annotations

import os
from typing import Any

import requests

from .exceptions import BillingAPIError, BillingConfigurationError


class LemonSqueezyClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        store_id: str | None = None,
        base_url: str | None = None,
        timeout: int | None = None,
    ):
        from django.conf import settings

        self.api_key = (
            api_key
            or os.getenv("LEMON_SQUEEZY_API_KEY", "")
            or getattr(settings, "LEMON_SQUEEZY_API_KEY", "")
        )
        self.store_id = (
            store_id
            or os.getenv("LEMON_SQUEEZY_STORE_ID", "")
            or getattr(settings, "LEMON_SQUEEZY_STORE_ID", "")
        )
        self.base_url = (
            base_url
            or os.getenv("LEMON_SQUEEZY_API_BASE_URL", "")
            or getattr(settings, "LEMON_SQUEEZY_API_BASE_URL", "")
        ).rstrip("/")
        self.timeout = timeout or int(
            os.getenv("LEMON_SQUEEZY_TIMEOUT_SECONDS", "")
            or getattr(settings, "LEMON_SQUEEZY_TIMEOUT_SECONDS", 30)
        )

        if not self.api_key:
            raise BillingConfigurationError("LEMON_SQUEEZY_API_KEY is not configured.")

    # ---- public API ------------------------------------------------------

    def create_checkout(
        self,
        *,
        variant_id: str,
        custom_data: dict[str, Any] | None = None,
        redirect_url: str | None = None,
        email: str | None = None,
        name: str | None = None,
    ) -> dict[str, Any]:
        """
        Create a hosted checkout URL. `custom_data` is preserved by LS and
        echoed back in webhook payloads, so we use it to carry our user_id +
        plan_slug. Returns the raw checkout object from LS.
        """
        if not self.store_id:
            raise BillingConfigurationError("LEMON_SQUEEZY_STORE_ID is not configured.")

        checkout_data: dict[str, Any] = {}
        if custom_data is not None:
            checkout_data["custom"] = custom_data
        if email:
            checkout_data["email"] = email
        if name:
            checkout_data["name"] = name

        payload: dict[str, Any] = {
            "data": {
                "type": "checkouts",
                "attributes": {
                    "checkout_data": checkout_data,
                    "preview": False,
                },
                "relationships": {
                    "store": {
                        "data": {"type": "stores", "id": str(self.store_id)},
                    },
                    "variant": {
                        "data": {"type": "variants", "id": str(variant_id)},
                    },
                },
            }
        }

        if redirect_url:
            payload["data"]["attributes"]["product_options"] = {
                "redirect_url": redirect_url,
            }

        response = self._request("POST", "/checkouts", json=payload)
        return response

    def generate_customer_portal_url(self, subscription_id: str) -> str:
        """
        Returns the one-time customer portal URL LS generates. The user is
        sent here to update card / cancel / see invoices.
        """
        response = self._request(
            "POST",
            f"/subscriptions/{subscription_id}/generate-customer-portal",
            json={"data": {"type": "subscriptions", "id": subscription_id}},
            expected_key="data",
        )
        return response["data"]["links"]["customer_portal"]

    def fetch_subscription(self, subscription_id: str) -> dict[str, Any]:
        return self._request("GET", f"/subscriptions/{subscription_id}")

    def update_subscription(self, subscription_id: str, **patch: Any) -> dict[str, Any]:
        """
        Patch a subscription. For MVP we use this only with `cancelled=True`
        to cancel at period end; LS also accepts plan changes etc. The caller
        passes snake_case attributes (e.g. cancelled=True, variant_id="123")
        and we forward them unchanged under data.attributes.
        """
        payload = {
            "data": {
                "type": "subscriptions",
                "id": str(subscription_id),
                "attributes": patch,
            }
        }
        return self._request("PATCH", f"/subscriptions/{subscription_id}", json=payload)

    # ---- internal --------------------------------------------------------

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        headers = {
            "Accept": "application/vnd.api+json",
            "Content-Type": "application/vnd.api+json",
            "Authorization": f"Bearer {self.api_key}",
        }
        try:
            response = requests.request(
                method,
                url,
                headers=headers,
                timeout=self.timeout,
                **kwargs,
            )
        except requests.RequestException as exc:
            raise BillingAPIError(f"Could not reach Lemon Squeezy: {exc}") from exc

        if response.status_code >= 400:
            message = self._extract_error_message(response)
            raise BillingAPIError(
                message or f"Lemon Squeezy returned {response.status_code}.",
                status_code=response.status_code,
                body=response.text,
            )

        if not response.content:
            return {}

        try:
            return response.json()
        except ValueError as exc:
            raise BillingAPIError(
                "Lemon Squeezy returned a non-JSON response.",
                status_code=response.status_code,
                body=response.text,
            ) from exc

    @staticmethod
    def _extract_error_message(response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return ""
        errors = payload.get("errors") if isinstance(payload, dict) else None
        if isinstance(errors, list) and errors:
            first = errors[0]
            if isinstance(first, dict):
                return str(first.get("detail") or first.get("title") or first)
            return str(first)
        if isinstance(payload, dict) and payload.get("error"):
            return str(payload["error"])
        return ""
