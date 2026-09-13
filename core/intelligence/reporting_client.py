"""Read the latest already-generated thumbnail reach report, when available."""
import csv
import io
from urllib.parse import quote, urlparse

import requests

from youtube_channels.exceptions import YouTubeAPIError, YouTubeAuthorizationError

REPORTING_URL = "https://youtubereporting.googleapis.com/v1"


def get_latest_reach_report(client, access_token):
    def get(path):
        return client._get(
            f"{REPORTING_URL}/{path}", access_token=access_token,
            params={"pageSize": 100},
        )

    # Discover report identifiers instead of assuming a versioned reach report ID.
    types = get("reportTypes").get("reportTypes", [])
    reach_types = {
        row["id"] for row in types
        if "reach" in str(row.get("name", "")).lower()
        or "reach" in str(row.get("id", "")).lower()
    }
    if not reach_types:
        return {"available": False, "reason": "No thumbnail reach report type available."}
    jobs = get("jobs").get("jobs", [])
    job = next((row for row in jobs if row.get("reportTypeId") in reach_types), None)
    if not job:
        return {"available": False, "reason": "No existing thumbnail reach Reporting job."}
    reports = get(f"jobs/{quote(job['id'], safe='')}/reports").get("reports", [])
    if not reports:
        return {"available": False, "reason": "Thumbnail reach report has not been generated yet."}
    report = max(reports, key=lambda row: row.get("endTime", ""))
    url = report.get("downloadUrl", "")
    parsed = urlparse(url)
    if (parsed.scheme != "https" or not parsed.hostname
            or not parsed.hostname.endswith(".googleapis.com")
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise YouTubeAPIError("Invalid Reporting download URL.")
    try:
        response = requests.get(
            url, headers={"Authorization": f"Bearer {access_token}"},
            timeout=client.timeout, stream=True, allow_redirects=False,
        )
        with response:
            if response.status_code == 401:
                raise YouTubeAuthorizationError("Reporting access expired. Please reconnect.")
            if response.status_code != 200:
                raise YouTubeAPIError("Could not download thumbnail reach report.")
            chunks, size = [], 0
            for chunk in response.iter_content(chunk_size=65536):
                size += len(chunk)
                if size > 5 * 1024 * 1024:
                    raise YouTubeAPIError("Thumbnail reach report exceeds MVP download limit.")
                chunks.append(chunk)
    except requests.RequestException as exc:
        raise YouTubeAPIError("Could not reach YouTube Reporting.") from exc
    try:
        rows = csv.DictReader(io.StringIO(b"".join(chunks).decode("utf-8-sig")))
        if not {"video_thumbnail_impressions", "video_thumbnail_impressions_ctr"}.issubset(
            rows.fieldnames or [],
        ):
            raise YouTubeAPIError("Reach report does not contain thumbnail metrics.")
        impressions, weighted_ctr = 0, 0.0
        for row in rows:
            count = int(row["video_thumbnail_impressions"])
            impressions += count
            weighted_ctr += count * float(row["video_thumbnail_impressions_ctr"])
    except (ValueError, UnicodeError, csv.Error) as exc:
        raise YouTubeAPIError("Invalid thumbnail reach report.") from exc
    return {
        "available": True, "source": "youtube_reporting", "report_id": report.get("id"),
        "period_start": report.get("startTime"), "period_end": report.get("endTime"),
        "thumbnail_impressions": impressions,
        "thumbnail_impressions_ctr": weighted_ctr / impressions if impressions else None,
    }
