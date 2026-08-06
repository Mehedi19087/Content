"""
Billing exceptions. Mirrors the structure of youtube_channels/exceptions.py.

- BillingError              base class so callers can catch any billing issue
- BillingConfigurationError missing API key / missing webhook secret / bad env
- BillingAPIError           LS returned a non-2xx response
- WebhookSignatureError     webhook payload failed HMAC verification
"""


class BillingError(Exception):
    """Base class for all billing-related errors."""


class BillingConfigurationError(BillingError):
    """Raised when billing cannot start because env / settings are missing."""


class BillingAPIError(BillingError):
    """Raised when Lemon Squeezy returns a non-success HTTP response."""

    def __init__(self, message: str, *, status_code: int | None = None, body: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class WebhookSignatureError(BillingError):
    """Raised when a webhook payload does not match the expected HMAC signature."""