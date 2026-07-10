from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from chat.models import ChatMessage, ChatSession, PlanProgress, ProblemCategory, UserPlan
from .views import _decode_oauth_state

User = get_user_model()


@override_settings(SECRET_KEY="test-secret-key")
class GoogleOAuthFlowTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.base_env = {
            "GOOGLE_CLIENT_ID": "google-client-id",
            "GOOGLE_CLIENT_SECRET": "google-client-secret",
            "GOOGLE_REDIRECT_URI": "https://api.example.com/api/google/callback/",
            "FRONTEND_GOOGLE_REDIRECT_URL": "https://web.example.com/google/callback",
            "MOBILE_GOOGLE_REDIRECT_URL": "sereniomind://auth-callback",
            "DJANGO_SECRET_KEY": "test-secret-key",
        }

    @patch.dict("os.environ", {"GOOGLE_CLIENT_ID": "google-client-id", "GOOGLE_REDIRECT_URI": "https://api.example.com/api/google/callback/"}, clear=False)
    def test_google_auth_url_encodes_mobile_platform_in_state(self):
        response = self.client.get("/api/google/auth-url/?platform=mobile")

        self.assertEqual(response.status_code, 200)
        auth_url = response.data["auth_url"]
        self.assertIn("redirect_uri=https%3A%2F%2Fapi.example.com%2Fapi%2Fgoogle%2Fcallback%2F", auth_url)

        state_value = auth_url.split("state=", 1)[1].split("&", 1)[0]
        decoded = _decode_oauth_state(state_value)
        self.assertEqual(decoded["platform"], "mobile")
        self.assertTrue(decoded.get("nonce"))

    @patch("core.users.views.requests.get")
    @patch("core.users.views.requests.post")
    @patch.dict("os.environ", {
        "GOOGLE_CLIENT_ID": "google-client-id",
        "GOOGLE_CLIENT_SECRET": "google-client-secret",
        "GOOGLE_REDIRECT_URI": "https://api.example.com/api/google/callback/",
        "FRONTEND_GOOGLE_REDIRECT_URL": "https://web.example.com/google/callback",
        "MOBILE_GOOGLE_REDIRECT_URL": "sereniomind://auth-callback",
        "DJANGO_SECRET_KEY": "test-secret-key",
    }, clear=False)
    def test_google_callback_redirects_mobile_users_to_deep_link(self, mock_post, mock_get):
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {"access_token": "google-access"}, text="ok")
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "email": "mobile@example.com",
                "given_name": "Mobile",
                "family_name": "User",
            },
            text="ok",
        )

        auth_url_response = self.client.get("/api/google/auth-url/?platform=mobile")
        state_value = auth_url_response.data["auth_url"].split("state=", 1)[1].split("&", 1)[0]

        response = self.client.get(f"/api/google/callback/?code=test-code&state={state_value}")

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("sereniomind://auth-callback?"))
        self.assertIn("access=", response["Location"])
        self.assertIn("refresh=", response["Location"])

        user = User.objects.get(email="mobile@example.com")
        self.assertEqual(user.first_name, "Mobile")

    @patch.dict("os.environ", {
        "GOOGLE_CLIENT_ID": "google-client-id",
        "GOOGLE_CLIENT_SECRET": "google-client-secret",
        "GOOGLE_REDIRECT_URI": "https://api.example.com/api/google/callback/",
        "FRONTEND_GOOGLE_REDIRECT_URL": "https://web.example.com/google/callback",
        "DJANGO_SECRET_KEY": "test-secret-key",
    }, clear=False)
    def test_google_callback_requires_mobile_redirect_env_for_mobile_flow(self):
        state_value = self.client.get("/api/google/auth-url/?platform=mobile").data["auth_url"].split("state=", 1)[1].split("&", 1)[0]

        response = self.client.get(f"/api/google/callback/?code=test-code&state={state_value}")

        self.assertEqual(response.status_code, 500)
        self.assertIn("MOBILE_GOOGLE_REDIRECT_URL", response.data["error"])


class UserAccountDeletionTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="delete-me",
            email="delete@example.com",
            password="secret123",
            emergency_number="+8801000000000",
        )
        self.client.force_authenticate(user=self.user)

    def test_delete_profile_removes_user_and_related_records(self):
        category = ProblemCategory.objects.create(name="General Anxiety")
        session = ChatSession.objects.create(user=self.user, title="Private Session")
        ChatMessage.objects.create(session=session, sender="user", content="I feel overwhelmed")
        plan = UserPlan.objects.create(user=self.user, category=category)
        PlanProgress.objects.create(plan=plan, day_number=1, is_completed=True)

        response = self.client.delete("/api/profile/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["detail"], "Account deleted successfully.")
        self.assertFalse(User.objects.filter(id=self.user.id).exists())
        self.assertFalse(ChatSession.objects.filter(id=session.id).exists())
        self.assertFalse(ChatMessage.objects.filter(session=session).exists())
        self.assertFalse(UserPlan.objects.filter(id=plan.id).exists())
        self.assertFalse(PlanProgress.objects.filter(plan=plan).exists())

    def test_delete_profile_requires_authentication(self):
        self.client.force_authenticate(user=None)

        response = self.client.delete("/api/profile/")

        self.assertEqual(response.status_code, 401)
