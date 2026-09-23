"""Small public Data API client. Each attempted request is accounted once."""
import requests
from datetime import timedelta
from django.utils import timezone
from django.conf import settings

from .models import QuotaLedger


class PublicYouTubeClient:
    def __init__(self, pool=None):
        self.pool = pool

    def _get(self, resource, **params):
        key = getattr(settings, "YOUTUBE_API_KEY", "")
        if not key:
            raise RuntimeError("YouTube API key is not configured.")
        QuotaLedger.objects.create(
            pool=self.pool, operation=f"{resource}.list",
            search_calls=int(resource == "search"),
            data_units=int(resource != "search"),
        )
        try:
            response = requests.get(
                f"https://www.googleapis.com/youtube/v3/{resource}",
                params={**params, "key": key}, timeout=30,
            )
        except requests.RequestException:
            # Requests errors can contain the full URL, including the API key.
            raise RuntimeError(f"YouTube {resource} could not be reached.") from None
        if not response.ok:
            raise RuntimeError(f"YouTube {resource} request failed ({response.status_code}).")
        return response.json().get("items", [])

    def search(self, query, language="", region=""):
        params = {"q": query, "type": "video", "part": "snippet", "maxResults": 50,
            "order": "relevance",
            "publishedAfter": (timezone.now() - timedelta(days=180)).isoformat()}
        if language:
            params["relevanceLanguage"] = language
        if region:
            params["regionCode"] = region
        return self._get("search", **params)

    def channels(self, ids):
        return self._get("channels", id=",".join(ids), part="snippet,statistics,contentDetails") if ids else []

    def uploads(self, playlist_id):
        return self._get("playlistItems", playlistId=playlist_id, part="contentDetails",
            maxResults=50)

    def videos(self, ids):
        results = []
        for offset in range(0, len(ids), 50):
            results.extend(self._get("videos", id=",".join(ids[offset:offset + 50]),
                part="snippet,statistics,contentDetails"))
        return results
