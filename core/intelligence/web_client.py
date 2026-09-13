"""Optional Brave web context; no arbitrary URL fetching or YouTube scraping."""
from urllib.parse import parse_qs, urlparse
from datetime import timedelta
import re

import requests
from django.conf import settings
from django.utils import timezone


def search_context(query):
    key = getattr(settings, "INTELLIGENCE_WEB_SEARCH_API_KEY", "")
    if not key:
        return []
    response = requests.get(
        "https://api.search.brave.com/res/v1/web/search",
        headers={"X-Subscription-Token": key}, params={"q": query, "count": 10}, timeout=20,
    )
    if not response.ok:
        raise RuntimeError("Web context search failed.")
    now = timezone.now()
    return [
        {
            "title": item.get("title", ""), "url": item.get("url", ""),
            "description": item.get("description", ""), "source": "brave_search",
            "fetched_at": now.isoformat(),
            "expires_at": (now + timedelta(days=3)).isoformat(),
        }
        for item in response.json().get("web", {}).get("results", [])[:10]
    ]


def youtube_ids(context):
    videos, channels = set(), set()
    for item in context:
        parsed = urlparse(item.get("url", ""))
        host = (parsed.hostname or "").lower()
        path = parsed.path.strip("/").split("/")
        video_id = ""
        if host == "youtu.be":
            video_id = path[0]
        elif host in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
            if len(path) >= 2 and path[0] == "channel" and re.fullmatch(r"UC[\w-]{22}", path[1]):
                channels.add(path[1])
            elif len(path) >= 2 and path[0] in {"shorts", "embed", "live"}:
                video_id = path[1]
            elif path[0] == "watch":
                video_id = parse_qs(parsed.query).get("v", [""])[0]
        if re.fullmatch(r"[\w-]{11}", video_id):
            videos.add(video_id)
    return sorted(videos), sorted(channels)
