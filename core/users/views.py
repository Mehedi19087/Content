import logging
import os
import secrets

import requests

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.decorators.clickjacking import xframe_options_exempt
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions
from rest_framework_simplejwt.settings import api_settings as jwt_api_settings
from rest_framework_simplejwt.tokens import AccessToken
from rest_framework_simplejwt.tokens import RefreshToken

from .oauth_utils import (
    SUPPORTED_AUTH_PLATFORMS,
    build_redirect_url,
    decode_oauth_state,
    encode_oauth_state,
    fingerprint,
    mobile_deep_link_response,
)
from .serializers import UserSerializer

User = get_user_model()
logger = logging.getLogger("users.views")


def _error_response(message, status_code=status.HTTP_400_BAD_REQUEST, extra=None):
    payload = {"error": message}
    if extra:
        payload.update(extra)
    return Response(payload, status=status_code)

@method_decorator(xframe_options_exempt, name="dispatch")
class GoogleAuthURLView(APIView):
    # Allow anyone to access this to get the URL
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def get(self, request):
        google_client_id = os.getenv("GOOGLE_CLIENT_ID")
        platform = (request.GET.get("platform") or "web").strip().lower()
        if platform not in SUPPORTED_AUTH_PLATFORMS:
            platform = "web"
        # Ensure we use HTTPS for the redirect_uri in production
        redirect_uri = os.getenv("GOOGLE_REDIRECT_URI") or request.build_absolute_uri(
            reverse("google-callback")
        ).replace("http://", "https://")

        if not google_client_id:
            return Response({"error": "GOOGLE_CLIENT_ID missing"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        state = encode_oauth_state(platform)
        params = {
            "client_id": google_client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "access_type": "online",
            "prompt": "select_account",
        }

        auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)
        return Response({"auth_url": auth_url})

@method_decorator(xframe_options_exempt, name="dispatch")
class GoogleCallbackView(APIView):
    # CRITICAL: Disable all authentication and permissions for the callback
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def get(self, request):
        logger.info("Google callback initiated")
        code = request.GET.get("code")
        state_payload = decode_oauth_state(request.GET.get("state"))
        platform = state_payload.get("platform", "web")

        if not code:
            return Response({"error": "No code provided by Google"}, status=status.HTTP_400_BAD_REQUEST)

        google_client_id = os.getenv("GOOGLE_CLIENT_ID")
        google_client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
        frontend_redirect = os.getenv("FRONTEND_GOOGLE_REDIRECT_URL")
        mobile_redirect = os.getenv("MOBILE_GOOGLE_REDIRECT_URL")
        redirect_uri = os.getenv("GOOGLE_REDIRECT_URI") or request.build_absolute_uri(
            reverse("google-callback")
        ).replace("http://", "https://")

        missing_env = [
            name for name, value in (
                ("GOOGLE_CLIENT_ID", google_client_id),
                ("GOOGLE_CLIENT_SECRET", google_client_secret),
                ("FRONTEND_GOOGLE_REDIRECT_URL", frontend_redirect),
            ) if not value
        ]
        if platform == "mobile" and not mobile_redirect:
            missing_env.append("MOBILE_GOOGLE_REDIRECT_URL")
        
        # Check for SECRET_KEY specifically from settings if DJANGO_SECRET_KEY env var is missing
        effective_secret_key = os.getenv("DJANGO_SECRET_KEY") or settings.SECRET_KEY
        if not effective_secret_key or ("django-insecure" in str(effective_secret_key) and not settings.DEBUG):
            if not os.getenv("DJANGO_SECRET_KEY"):
                missing_env.append("DJANGO_SECRET_KEY")

        if missing_env:
            logger.error("Google callback missing required env vars: %s", ", ".join(missing_env))
            return _error_response(
                f"Server configuration incomplete. Missing: {', '.join(missing_env)}",
                status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        logger.info("Exchanging Google code for token with redirect_uri=%s", redirect_uri)

        # Exchange code for access token
        try:
            token_response = requests.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "code": code,
                    "client_id": google_client_id,
                    "client_secret": google_client_secret,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
                timeout=10
            )
        except requests.RequestException as exc:
            logger.exception("Google token exchange request failed: %s", exc)
            return _error_response(
                "Could not reach Google token service.",
                status.HTTP_502_BAD_GATEWAY,
            )

        if token_response.status_code != 200:
            logger.error("Google token exchange failed: status=%s body=%s", token_response.status_code, token_response.text)
            return _error_response(
                "Google token exchange failed.",
                status.HTTP_400_BAD_REQUEST,
                {"provider_status": token_response.status_code},
            )

        token_data = token_response.json()
        access_token = token_data.get("access_token")
        if not access_token:
            logger.error("Google token exchange succeeded without access_token: %s", token_data)
            return _error_response("Google did not return an access token.")

        # Get user info from Google
        try:
            user_info_res = requests.get(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=10
            )
        except requests.RequestException as exc:
            logger.exception("Google userinfo request failed: %s", exc)
            return _error_response(
                "Could not reach Google user profile service.",
                status.HTTP_502_BAD_GATEWAY,
            )

        if user_info_res.status_code != 200:
            logger.error("Google userinfo failed: status=%s body=%s", user_info_res.status_code, user_info_res.text)
            return _error_response(
                "Failed to fetch Google user info.",
                status.HTTP_400_BAD_REQUEST,
                {"provider_status": user_info_res.status_code},
            )

        user_data = user_info_res.json()
        email = (user_data.get("email") or "").strip().lower()
        if not email:
            logger.error("Google userinfo missing email: %s", user_data)
            return _error_response("Google account did provide an email address.")

        # Find or create user
        try:
            with transaction.atomic():
                user = User.objects.filter(email=email).order_by("id").first()
                created = False
                if user is None:
                    base_username = email.split("@")[0][:140] or "user"
                    username = base_username
                    suffix = 1
                    while User.objects.filter(username=username).exists():
                        suffix += 1
                        username = f"{base_username[:140-len(str(suffix))-1]}-{suffix}"

                    user = User.objects.create(
                        email=email,
                        username=username,
                        first_name=user_data.get("given_name", ""),
                        last_name=user_data.get("family_name", ""),
                    )
                    created = True
        except Exception as exc:
            logger.exception("User creation/login failed for email=%s: %s", email, exc)
            return _error_response(
                "Could not finish sign-in for this account.",
                status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        logger.info(
            "Google user authenticated: email=%s created=%s user_id=%s exists_in_db=%s",
            email,
            created,
            user.id,
            User.objects.filter(id=user.id).exists(),
        )

        # Generate JWT tokens
        refresh = RefreshToken.for_user(user)
        access_token = refresh.access_token
        validated_access = AccessToken(str(access_token))

        logger.info(
            "Issued JWT for user_id=%s access_exp=%s refresh_exp=%s access_claim_user_id=%s signing_key_fp=%s secret_key_fp=%s access_lifetime=%s refresh_lifetime=%s",
            user.id,
            validated_access.get("exp"),
            refresh.get("exp"),
            validated_access.get(jwt_api_settings.USER_ID_CLAIM),
            fingerprint(settings.SIMPLE_JWT.get("SIGNING_KEY")),
            fingerprint(settings.SECRET_KEY),
            settings.SIMPLE_JWT.get("ACCESS_TOKEN_LIFETIME"),
            settings.SIMPLE_JWT.get("REFRESH_TOKEN_LIFETIME"),
        )

        redirect_target = mobile_redirect if platform == "mobile" else frontend_redirect
        if redirect_target:
            final_redirect = build_redirect_url(
                redirect_target,
                access_token=str(access_token),
                refresh_token=str(refresh),
            )
            logger.info("Redirecting after Google login | platform=%s | target=%s", platform, final_redirect)
            if platform == "mobile":
                return mobile_deep_link_response(final_redirect)
            return redirect(final_redirect)

        return Response({
            "access": str(access_token),
            "refresh": str(refresh),
            "user": {"email": user.email}
        })


class ReviewerLoginView(APIView):
    """
    Surgical bypass for App Store/Play Store review.
    Allows authentication with a specific email and secret bypass key,
    skipping Google OAuth entirely.
    """
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request):
        email = request.data.get("email", "").strip().lower()
        secret = request.data.get("secret", "")
        
        # These should be set in environment variables (e.g., .env)
        reviewer_email = os.getenv("REVIEWER_BYPASS_EMAIL")
        reviewer_secret = os.getenv("REVIEWER_BYPASS_SECRET")

        if not reviewer_email or not reviewer_secret:
            return Response(
                {"error": "Bypass authentication is not configured on server."}, 
                status=status.HTTP_403_FORBIDDEN
            )

        if email == reviewer_email.strip().lower() and secret == reviewer_secret:
            logger.info("Reviewer bypass login successful for email=%s", email)
            
            user = User.objects.filter(email=email).first()
            if not user:
                # Create the reviewer user if they don't exist
                user = User.objects.create(
                    email=email,
                    username=f"reviewer-{secrets.token_hex(4)}",
                    first_name="App",
                    last_name="Reviewer"
                )
            
            refresh = RefreshToken.for_user(user)
            return Response({
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "user": {
                    "email": user.email,
                    "id": user.id
                }
            })
        
        logger.warning("Failed reviewer bypass attempt | email=%s", email)
        return Response({"error": "Invalid reviewer credentials"}, status=status.HTTP_401_UNAUTHORIZED)


class UserProfileView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        serializer = UserSerializer(request.user)
        return Response(serializer.data)

    def patch(self, request):
        serializer = UserSerializer(request.user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request):
        user = request.user
        user_id = user.id

        logger.info("Account deletion initiated | user_id=%s", user_id)

        # Revoke connected YouTube access and remove its authorized data first.
        from youtube_channels.models import YouTubeChannel
        from youtube_channels.services import disconnect_youtube_channel

        if YouTubeChannel.objects.filter(user_id=user_id).exists():
            disconnect_youtube_channel(user_id=user_id)

        with transaction.atomic():
            user.delete()

        logger.info("Account deletion completed | user_id=%s", user_id)
        return Response(
            {"detail": "Account deleted successfully."},
            status=status.HTTP_200_OK,
        )
