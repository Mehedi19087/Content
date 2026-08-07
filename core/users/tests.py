from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient, APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from .oauth_utils import decode_oauth_state


User = get_user_model()


@override_settings(SECRET_KEY="test-secret-key")
class GoogleOAuthFlowTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    @patch.dict(
        "os.environ",
        {
            "GOOGLE_CLIENT_ID": "google-client-id",
            "GOOGLE_REDIRECT_URI": (
                "https://api.example.com/api/auth/google/callback/"
            ),
        },
        clear=False,
    )
    def test_google_auth_url_encodes_mobile_platform_in_state(self):
        response = self.client.get("/api/auth/google/auth-url/?platform=mobile")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        auth_url = response.data["auth_url"]
        self.assertIn(
            "redirect_uri=https%3A%2F%2Fapi.example.com%2Fapi%2Fauth%2Fgoogle%2Fcallback%2F",
            auth_url,
        )

        state_value = auth_url.split("state=", 1)[1].split("&", 1)[0]
        decoded = decode_oauth_state(state_value)
        self.assertEqual(decoded["platform"], "mobile")
        self.assertTrue(decoded.get("nonce"))

    @patch("users.views.requests.get")
    @patch("users.views.requests.post")
    @patch.dict(
        "os.environ",
        {
            "GOOGLE_CLIENT_ID": "google-client-id",
            "GOOGLE_CLIENT_SECRET": "google-client-secret",
            "GOOGLE_REDIRECT_URI": (
                "https://api.example.com/api/auth/google/callback/"
            ),
            "FRONTEND_GOOGLE_REDIRECT_URL": (
                "https://web.example.com/google/callback"
            ),
            "MOBILE_GOOGLE_REDIRECT_URL": "creatorintent://auth-callback",
            "DJANGO_SECRET_KEY": "test-secret-key",
        },
        clear=False,
    )
    def test_google_callback_redirects_mobile_users_to_deep_link(
        self,
        mock_post,
        mock_get,
    ):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"access_token": "google-access"},
            text="ok",
        )
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "email": "mobile@example.com",
                "given_name": "Mobile",
                "family_name": "User",
            },
            text="ok",
        )

        auth_url_response = self.client.get(
            "/api/auth/google/auth-url/?platform=mobile",
        )
        state_value = auth_url_response.data["auth_url"].split(
            "state=",
            1,
        )[1].split("&", 1)[0]

        response = self.client.get(
            f"/api/auth/google/callback/?code=test-code&state={state_value}",
        )

        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        self.assertTrue(
            response["Location"].startswith("creatorintent://auth-callback?"),
        )
        self.assertIn("access=", response["Location"])
        self.assertIn("refresh=", response["Location"])

        user = User.objects.get(email="mobile@example.com")
        self.assertEqual(user.first_name, "Mobile")

    @patch.dict(
        "os.environ",
        {
            "GOOGLE_CLIENT_ID": "google-client-id",
            "GOOGLE_CLIENT_SECRET": "google-client-secret",
            "GOOGLE_REDIRECT_URI": (
                "https://api.example.com/api/auth/google/callback/"
            ),
            "FRONTEND_GOOGLE_REDIRECT_URL": (
                "https://web.example.com/google/callback"
            ),
            "MOBILE_GOOGLE_REDIRECT_URL": "",
            "DJANGO_SECRET_KEY": "test-secret-key",
        },
        clear=False,
    )
    def test_google_callback_requires_mobile_redirect_env_for_mobile_flow(self):
        auth_url_response = self.client.get(
            "/api/auth/google/auth-url/?platform=mobile",
        )
        state_value = auth_url_response.data["auth_url"].split(
            "state=",
            1,
        )[1].split("&", 1)[0]

        response = self.client.get(
            f"/api/auth/google/callback/?code=test-code&state={state_value}",
        )

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertIn("MOBILE_GOOGLE_REDIRECT_URL", response.data["error"])


class TokenLifecycleAPITests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="token-user",
            email="token@example.com",
            password="secret123",
        )
        self.refresh = RefreshToken.for_user(self.user)

    def test_refresh_token_returns_new_access_token(self):
        response = self.client.post(
            reverse("token-refresh"),
            {"refresh": str(self.refresh)},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)

        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {response.data['access']}",
        )
        profile_response = self.client.get(reverse("user-profile"))
        self.assertEqual(profile_response.status_code, status.HTTP_200_OK)
        self.assertEqual(profile_response.data["email"], self.user.email)

    def test_verify_token_accepts_valid_access_token(self):
        response = self.client.post(
            reverse("token-verify"),
            {"token": str(self.refresh.access_token)},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {"valid": True})

    def test_refresh_token_rejects_invalid_token_consistently(self):
        response = self.client.post(
            reverse("token-refresh"),
            {"refresh": "not-a-token"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data["error"]["code"], "token_not_valid")


class UserAccountDeletionTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="delete-me",
            email="delete@example.com",
            password="secret123",
        )
        self.client.force_authenticate(user=self.user)

    def test_delete_profile_removes_user(self):
        response = self.client.delete(reverse("user-profile"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["detail"], "Account deleted successfully.")
        self.assertFalse(User.objects.filter(id=self.user.id).exists())

    def test_delete_profile_requires_authentication(self):
        self.client.force_authenticate(user=None)

        response = self.client.delete(reverse("user-profile"))

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
