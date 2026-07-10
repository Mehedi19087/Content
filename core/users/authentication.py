import hashlib
import logging

from django.conf import settings
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken


logger = logging.getLogger("users.auth")


def _fingerprint(value):
    
    if not value:
        return "missing"
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:12]




class LoggingJWTAuthentication(JWTAuthentication):
    def authenticate(self, request):
        header = self.get_header(request)
        if header is None:
            return None

        raw_token = self.get_raw_token(header)
        if raw_token is None:
            logger.warning(
                "JWT header present but raw token missing | auth_header=%s | signing_key_fp=%s",
                header[:32],
                _fingerprint(settings.SIMPLE_JWT.get("SIGNING_KEY")),
            )
            return None

        logger.info(
            "Authenticating JWT | path=%s | method=%s | signing_key_fp=%s | token_prefix=%s",
            getattr(request, "path", ""),
            getattr(request, "method", ""),
            _fingerprint(settings.SIMPLE_JWT.get("SIGNING_KEY")),
            raw_token[:20].decode("utf-8", errors="ignore"),
        )

        validated_token = self.get_validated_token(raw_token)
        user = self.get_user(validated_token)
        logger.info(
            "JWT accepted | path=%s | user_id=%s | claim_user_id=%s | signing_key_fp=%s",
            getattr(request, "path", ""),
            getattr(user, "id", None),
            validated_token.get(settings.SIMPLE_JWT.get("USER_ID_CLAIM", "user_id")),
            _fingerprint(settings.SIMPLE_JWT.get("SIGNING_KEY")),
        )
        return (user, validated_token)

    def get_validated_token(self, raw_token):
        try:
            return super().get_validated_token(raw_token)
        except InvalidToken as exc:
            logger.error(
                "JWT validation failed: %s | signing_key_fp=%s | algorithm=%s | header_types=%s | token_prefix=%s",
                exc,
                _fingerprint(settings.SIMPLE_JWT.get("SIGNING_KEY")),
                settings.SIMPLE_JWT.get("ALGORITHM"),
                settings.SIMPLE_JWT.get("AUTH_HEADER_TYPES"),
                str(raw_token)[:16],
            )
            raise
