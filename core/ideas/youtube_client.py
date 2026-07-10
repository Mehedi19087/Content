from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any

from django.conf import settings
from rest_framework.exceptions import ValidationError


YOUTUBE_API_BASE_URL = "https://www.googleapis.com/youtube/v3"


class YouTubeClient:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or settings.YOUTUBE_API_KEY
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
            with urllib.request.urlopen(url, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise ValidationError(
                {"youtube_api": f"Failed to fetch YouTube data: {exc}"}
            )
