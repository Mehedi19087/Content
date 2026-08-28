from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from django.conf import settings
from rest_framework.exceptions import ValidationError


YOUTUBE_API_BASE_URL = "https://www.googleapis.com/youtube/v3"
logger = logging.getLogger(__name__)


class YouTubeAPIError(ValidationError):
    def __init__(self, message: str, *, upstream_status_code: int | None = None):
        self.upstream_status_code = upstream_status_code
        super().__init__({"youtube_api": message})


class YouTubeClient:
    def __init__(
        self,
        api_key: str | None = None,
        timeout_seconds: int | None = None,
    ):
        self.api_key = api_key or settings.YOUTUBE_API_KEY
        self.timeout_seconds = timeout_seconds or 30
        if not self.api_key:
            raise ValidationError(
                {"youtube_api_key": "YOUTUBE_API_KEY is not configured."}
            )

    def fetch_most_popular_videos(
        self,
        *,
        category_ids: list[str],
        region_code: str,
        max_results: int = 15,
    ) -> list[dict[str, Any]]:
        videos: list[dict[str, Any]] = []

        for category_id in category_ids:
            try:
                data = self._get(
                    "videos",
                    {
                        "part": "snippet,statistics,contentDetails",
                        "chart": "mostPopular",
                        "regionCode": region_code,
                        "videoCategoryId": category_id,
                        "maxResults": max_results,
                    },
                )
            except YouTubeAPIError as exc:
                if exc.upstream_status_code != 404:
                    raise
                logger.warning(
                    "YouTube most-popular chart unavailable; continuing with "
                    "remaining charts and keyword search. category_id=%s region=%s",
                    category_id,
                    region_code,
                )
                continue
            for item in data.get("items", []):
                item["_source_type"] = "most_popular"
                item["_matched_keyword"] = ""
                videos.append(item)

        return videos

    def search_videos_by_keywords(
        self,
        *,
        keywords: list[str],
        category_ids: list[str],
        region_code: str,
        published_after: str,
        max_keywords: int = 4,
        max_results_per_keyword: int = 5,
    ) -> list[dict[str, Any]]:
        search_results: list[dict[str, Any]] = []
        category_id = category_ids[0] if category_ids else ""

        for keyword in keywords[:max_keywords]:
            params = {
                "part": "snippet",
                "q": keyword,
                "type": "video",
                "order": "viewCount",
                "publishedAfter": published_after,
                "regionCode": region_code,
                "relevanceLanguage": "en",
                "maxResults": max_results_per_keyword,
            }
            if category_id:
                params["videoCategoryId"] = category_id

            data = self._get("search", params)
            for item in data.get("items", []):
                video_id = item.get("id", {}).get("videoId")
                if not video_id:
                    continue

                search_results.append(
                    {
                        "video_id": video_id,
                        "snippet": item.get("snippet", {}),
                        "_source_type": "search",
                        "_matched_keyword": keyword,
                    }
                )

        return search_results

    def search_videos_by_query(
        self,
        *,
        query: str,
        region_code: str = "US",
        language_code: str = "en",
        max_results: int = 10,
    ) -> list[dict[str, Any]]:
        data = self._get(
            "search",
            {
                "part": "snippet",
                "q": query,
                "type": "video",
                "order": "relevance",
                "regionCode": region_code,
                "relevanceLanguage": language_code,
                "safeSearch": "moderate",
                "maxResults": max_results,
            },
        )

        results: list[dict[str, Any]] = []
        for item in data.get("items", []):
            video_id = item.get("id", {}).get("videoId")
            if not video_id:
                continue

            results.append(
                {
                    "video_id": video_id,
                    "snippet": item.get("snippet", {}),
                }
            )

        return results

    def fetch_videos_by_ids(self, video_ids: list[str]) -> list[dict[str, Any]]:
        videos: list[dict[str, Any]] = []
        unique_ids = list(dict.fromkeys(video_ids))

        for start in range(0, len(unique_ids), 50):
            chunk = unique_ids[start : start + 50]
            if not chunk:
                continue

            data = self._get(
                "videos",
                {
                    "part": "snippet,statistics,contentDetails",
                    "id": ",".join(chunk),
                    "maxResults": 50,
                },
            )
            videos.extend(data.get("items", []))

        return videos

    def _get(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        params = {**params, "key": self.api_key}
        url = f"{YOUTUBE_API_BASE_URL}/{endpoint}?{urllib.parse.urlencode(params)}"

        try:
            with urllib.request.urlopen(
                url,
                timeout=self.timeout_seconds,
            ) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            response_body = exc.read().decode("utf-8", errors="replace")
            upstream_message = _get_youtube_error_message(response_body)
            raise YouTubeAPIError(
                (
                    f"YouTube API returned HTTP {exc.code} for {endpoint}: "
                    f"{upstream_message}"
                ),
                upstream_status_code=exc.code,
            ) from exc
        except Exception as exc:
            raise YouTubeAPIError(
                f"Failed to fetch YouTube data from {endpoint}: {exc}"
            ) from exc


def _get_youtube_error_message(response_body: str) -> str:
    try:
        payload = json.loads(response_body)
        message = payload.get("error", {}).get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
    except (json.JSONDecodeError, AttributeError):
        pass
    return response_body[:500] or "Unknown YouTube API error."
