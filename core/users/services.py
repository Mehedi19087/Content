from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken, UntypedToken

from .exceptions import InvalidAuthToken


def create_access_token_from_refresh(*, refresh_token: str) -> str:
    try:
        token = RefreshToken(refresh_token)
        return str(token.access_token)
    except TokenError as exc:
        raise InvalidAuthToken("Refresh token is invalid or expired.") from exc


def validate_token(*, token: str) -> None:
    try:
        UntypedToken(token)
    except TokenError as exc:
        raise InvalidAuthToken() from exc
