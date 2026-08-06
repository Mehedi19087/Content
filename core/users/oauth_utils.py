"""
Shared helpers for OAuth-style redirect flows (Google login, Lemon Squeezy checkout,
etc). Extracted from users.views so the billing app can reuse the same mobile /
web redirect semantics without importing users.views (which would create a
circular import).

These helpers are intentionally framework-agnostic: they take and return plain
strings / dicts, and produce an HttpResponse only for the mobile deep-link case.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from base64 import urlsafe_b64decode, urlsafe_b64encode
from urllib.parse import parse_qsl, urlencode

from django.http import HttpResponse


SUPPORTED_AUTH_PLATFORMS = {"web", "mobile"}


def encode_oauth_state(platform: str) -> str:
    """
    Build an opaque, tamper-resistant state string embedding the target platform
    ('web' or 'mobile'). The value is base64url(json). We do NOT sign it because
    the state is only used by us to remember which redirect target to use after
    the round-trip; it is not a security boundary (the real security check is the
    provider's signature / returned code).
    """
    payload = {
        "nonce": secrets.token_urlsafe(32),
        "platform": platform if platform in SUPPORTED_AUTH_PLATFORMS else "web",
    }
    encoded = urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8")
    return encoded.rstrip("=")


def decode_oauth_state(state: str | None) -> dict:
    """
    Inverse of encode_oauth_state. Always returns a dict with at least
    {"platform": "web"}. Never raises; malformed state falls back to web so the
    user is never blocked out of signing in.
    """
    if not state:
        return {"platform": "web"}

    try:
        padded_state = state + "=" * (-len(state) % 4)
        decoded = urlsafe_b64decode(padded_state.encode("utf-8")).decode("utf-8")
        payload = json.loads(decoded)
        platform = payload.get("platform", "web")
        if platform not in SUPPORTED_AUTH_PLATFORMS:
            platform = "web"
        payload["platform"] = platform
        return payload
    except Exception:
        return {"platform": "web"}


def build_redirect_url(base_url: str, access_token: str, refresh_token: str) -> str:
    """
    Append `access` and `refresh` query params to a frontend / deep-link URL,
    preserving any existing query params and fragment.
    """
    redirect_url_parts = base_url.split("#", 1)
    base_part = redirect_url_parts[0]
    hash_part = f"#{redirect_url_parts[1]}" if len(redirect_url_parts) > 1 else ""

    query_parts = base_part.split("?", 1)
    redirect_base = query_parts[0]
    existing_params = dict(parse_qsl(query_parts[1])) if len(query_parts) > 1 else {}

    existing_params.update(
        {
            "access": access_token,
            "refresh": refresh_token,
        }
    )

    return f"{redirect_base}?{urlencode(existing_params)}{hash_part}"


def mobile_deep_link_response(final_redirect: str) -> HttpResponse:
    """
    Return an HTTP 302 redirecting to a mobile app deep link (e.g.
    sereniomind://auth-callback?access=...). Django will render the Location
    header as-is for non-http(s) schemes, which is what mobile clients expect.
    """
    response = HttpResponse(status=302)
    response["Location"] = final_redirect
    return response


def normalize_platform(value: str | None) -> str:
    """Coerce arbitrary input into a valid platform string ('web' or 'mobile')."""
    platform = (value or "web").strip().lower()
    return platform if platform in SUPPORTED_AUTH_PLATFORMS else "web"


def fingerprint(value) -> str:
    """Short sha256 fingerprint for logging secrets without leaking them."""
    if not value:
        return "missing"
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:12]