from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlencode

import requests

from .exceptions import (
    YouTubeAPIError,
    YouTubeAuthorizationError,
    YouTubeConfigurationError,
)


GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
YOUTUBE_DATA_API_URL = "https://www.googleapis.com/youtube/v3"
YOUTUBE_ANALYTICS_API_URL = "https://youtubeanalytics.googleapis.com/v2/reports"

YOUTUBE_SCOPES = (
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
)


class ConnectedYouTubeClient:
    def __init__(
        self,
        *,
        client_id: str | None = None,
        client_secret: str | None = None,
        timeout: int = 30,
    ):
        self.client_id = client_id or os.getenv("GOOGLE_CLIENT_ID", "")
        self.client_secret = client_secret or os.getenv("GOOGLE_CLIENT_SECRET", "")
        self.timeout = timeout

        if not self.client_id or not self.client_secret:
            raise YouTubeConfigurationError(
                "Google OAuth client credentials are not configured."
            )

    def build_authorization_url(self, *, state: str, redirect_uri: str) -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(YOUTUBE_SCOPES),
            "state": state,
            "access_type": "offline",
            "include_granted_scopes": "true",
            "prompt": "consent select_account",
        }
        return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"

    def exchange_code(self, *, code: str, redirect_uri: str) -> dict[str, Any]:
        return self._token_request(
            {
                "code": code,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            }
        )

    def refresh_access_token(self, *, refresh_token: str) -> str:
        data = self._token_request(
            {
                "refresh_token": refresh_token,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "refresh_token",
            }
        )
        access_token = data.get("access_token")
        if not access_token:
            raise YouTubeAuthorizationError("Google did not return an access token.")
        return str(access_token)

    def revoke_token(self, *, token: str) -> None:
        try:
            response = requests.post(
                GOOGLE_REVOKE_URL,
                data={"token": token},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=self.timeout,
            )
        except requests.RequestException:
            return

        if response.status_code not in (200, 400):
            raise YouTubeAPIError("Google could not revoke YouTube access.")

    def get_my_channel(self, *, access_token: str) -> dict[str, Any]:
        data = self._get(
            f"{YOUTUBE_DATA_API_URL}/channels",
            access_token=access_token,
            params={
                "part": "snippet,contentDetails,statistics",
                "mine": "true",
                "maxResults": 1,
            },
        )
        items = data.get("items", [])
        if not items:
            raise YouTubeAuthorizationError(
                "No YouTube channel was found for the selected Google account."
            )
        return items[0]

    def get_upload_video_ids(
        self,
        *,
        access_token: str,
        uploads_playlist_id: str,
        max_results: int = 50,
    ) -> list[dict[str, str]]:
        data = self._get(
            f"{YOUTUBE_DATA_API_URL}/playlistItems",
            access_token=access_token,
            params={
                "part": "snippet,contentDetails",
                "playlistId": uploads_playlist_id,
                "maxResults": min(max_results, 50),
            },
        )
        results = []
        for item in data.get("items", []):
            video_id = item.get("contentDetails", {}).get("videoId")
            if not video_id:
                continue
            results.append(
                {
                    "video_id": str(video_id),
                    "published_at": str(
                        item.get("contentDetails", {}).get("videoPublishedAt")
                        or item.get("snippet", {}).get("publishedAt")
                        or ""
                    ),
                }
            )
        return results

    def get_videos(
        self,
        *,
        access_token: str,
        video_ids: list[str],
    ) -> list[dict[str, Any]]:
        if not video_ids:
            return []
        data = self._get(
            f"{YOUTUBE_DATA_API_URL}/videos",
            access_token=access_token,
            params={
                "part": "snippet,contentDetails,statistics,status",
                "id": ",".join(video_ids[:50]),
                "maxResults": min(len(video_ids), 50),
            },
        )
        return data.get("items", [])

    def query_analytics(
        self,
        *,
        access_token: str,
        start_date: str,
        end_date: str,
        metrics: list[str],
        dimensions: list[str] | None = None,
        filters: str = "",
        sort: str = "",
        max_results: int = 200,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "ids": "channel==MINE",
            "startDate": start_date,
            "endDate": end_date,
            "metrics": ",".join(metrics),
            "maxResults": max_results,
        }
        if dimensions:
            params["dimensions"] = ",".join(dimensions)
        if filters:
            params["filters"] = filters
        if sort:
            params["sort"] = sort

        data = self._get(
            YOUTUBE_ANALYTICS_API_URL,
            access_token=access_token,
            params=params,
        )
        headers = [item.get("name", "") for item in data.get("columnHeaders", [])]
        return [dict(zip(headers, row)) for row in data.get("rows", [])]

    def _token_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = requests.post(
                GOOGLE_TOKEN_URL,
                data=payload,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise YouTubeAPIError("Could not reach Google authorization services.") from exc

        if response.status_code != 200:
            try:
                error_code = response.json().get("error", "")
            except ValueError:
                error_code = ""
            if error_code in {"invalid_grant", "unauthorized_client", "access_denied"}:
                raise YouTubeAuthorizationError(
                    "YouTube authorization expired or was revoked. Please reconnect."
                )
            raise YouTubeAuthorizationError("Google rejected YouTube authorization.")

        try:
            return response.json()
        except ValueError as exc:
            raise YouTubeAPIError("Google returned an invalid authorization response.") from exc

    def _get(
        self,
        url: str,
        *,
        access_token: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            response = requests.get(
                url,
                params=params,
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise YouTubeAPIError("Could not reach the YouTube API.") from exc

        if response.status_code == 401:
            raise YouTubeAuthorizationError(
                "YouTube authorization expired or was revoked. Please reconnect."
            )
        if response.status_code == 403:
            raise YouTubeAPIError(
                "YouTube denied the request. Check API access, scopes, and quota."
            )
        if response.status_code != 200:
            raise YouTubeAPIError(
                f"YouTube API request failed with status {response.status_code}."
            )

        try:
            return response.json()
        except ValueError as exc:
            raise YouTubeAPIError("YouTube returned an invalid response.") from exc
