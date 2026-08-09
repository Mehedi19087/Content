from __future__ import annotations

import json
import urllib.parse
import urllib.request


YOUTUBE_SUGGEST_URL = "https://suggestqueries.google.com/complete/search"


class YouTubeSuggestClient:
    def fetch_suggestions(
        self,
        *,
        query: str,
        region_code: str = "US",
        language_code: str = "en",
        limit: int = 10,
    ) -> list[str]:
        params = urllib.parse.urlencode(
            {
                "client": "firefox",
                "ds": "yt",
                "q": query,
                "hl": language_code,
                "gl": region_code,
            }
        )
        request = urllib.request.Request(
            f"{YOUTUBE_SUGGEST_URL}?{params}",
            headers={
                "Accept": "application/json",
                "User-Agent": "content-youtube-intent-research/1.0",
            },
        )

        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception:
            return []

        if not isinstance(payload, list) or len(payload) < 2:
            return []

        raw_suggestions = payload[1]
        if not isinstance(raw_suggestions, list):
            return []

        suggestions = []
        seen = set()
        for item in raw_suggestions:
            suggestion = str(item).strip()
            normalized = suggestion.casefold()
            if not suggestion or normalized in seen:
                continue
            suggestions.append(suggestion)
            seen.add(normalized)
            if len(suggestions) >= limit:
                break

        return suggestions
