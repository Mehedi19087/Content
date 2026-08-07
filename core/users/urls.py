from django.urls import path

from .views import (
    GoogleAuthURLView,
    GoogleCallbackView,
    RefreshAccessTokenAPIView,
    ReviewerLoginView,
    UserProfileView,
    VerifyTokenAPIView,
)

urlpatterns = [
    path(
        "token/refresh/",
        RefreshAccessTokenAPIView.as_view(),
        name="token-refresh",
    ),
    path("token/verify/", VerifyTokenAPIView.as_view(), name="token-verify"),
    path("google/auth-url/", GoogleAuthURLView.as_view(), name="google-auth-url"),
    path("google/callback/", GoogleCallbackView.as_view(), name="google-callback"),
    path("reviewer-login/", ReviewerLoginView.as_view(), name="reviewer-login"),
    path("profile/", UserProfileView.as_view(), name="user-profile"),
    path("profile", UserProfileView.as_view()),
]
