from __future__ import annotations

import base64
import hashlib
import math
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone as datetime_timezone
from statistics import median
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import signing
from django.core.signing import BadSignature, SignatureExpired
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import NotFound, ValidationError

from ideas.llm_client import TextGenerationClient

from .exceptions import (
    YouTubeAPIError,
    YouTubeAuthorizationError,
    YouTubeConfigurationError,
)
from .models import YouTubeChannel, YouTubeChannelAnalysis
from .youtube_client import ConnectedYouTubeClient, YOUTUBE_SCOPES


OAUTH_STATE_SALT = "youtube-channel-connect"
OAUTH_STATE_MAX_AGE_SECONDS = 10 * 60
VIDEO_ANALYTICS_METRICS = [
    "views",
    "estimatedMinutesWatched",
    "averageViewDuration",
    "averageViewPercentage",
    "likes",
    "comments",
    "shares",
    "subscribersGained",
    "subscribersLost",
]
DAILY_ANALYTICS_METRICS = [
    "views",
    "estimatedMinutesWatched",
    "subscribersGained",
    "subscribersLost",
]
STOP_WORDS = {
    "about",
    "after",
    "again",
    "best",
    "from",
    "have",
    "into",
    "just",
    "more",
    "that",
    "this",
    "video",
    "what",
    "when",
    "with",
    "your",
    "you",
    "the",
    "and",
    "for",
    "how",
    "why",
}


def build_youtube_connect_url(
    *,
    user_id: int,
    redirect_uri: str,
    youtube_client: ConnectedYouTubeClient | None = None,
) -> str:
    state = signing.dumps(
        {"user_id": user_id},
        salt=OAUTH_STATE_SALT,
        compress=True,
    )
    client = youtube_client or ConnectedYouTubeClient()
    return client.build_authorization_url(state=state, redirect_uri=redirect_uri)


def connect_youtube_channel(
    *,
    code: str,
    state: str,
    redirect_uri: str,
    youtube_client: ConnectedYouTubeClient | None = None,
) -> YouTubeChannel:
    try:
        state_payload = signing.loads(
            state,
            salt=OAUTH_STATE_SALT,
            max_age=OAUTH_STATE_MAX_AGE_SECONDS,
        )
    except SignatureExpired as exc:
        raise ValidationError({"state": "YouTube connection request expired."}) from exc
    except BadSignature as exc:
        raise ValidationError({"state": "Invalid YouTube connection request."}) from exc

    user = get_user_model().objects.filter(id=state_payload.get("user_id")).first()
    if user is None:
        raise ValidationError({"state": "The account for this request no longer exists."})

    client = youtube_client or ConnectedYouTubeClient()
    try:
        token_data = client.exchange_code(code=code, redirect_uri=redirect_uri)
        access_token = str(token_data.get("access_token") or "")
        if not access_token:
            raise YouTubeAuthorizationError("Google did not return an access token.")

        granted_scopes = set(str(token_data.get("scope") or "").split())
        if granted_scopes and not set(YOUTUBE_SCOPES).issubset(granted_scopes):
            raise YouTubeAuthorizationError(
                "Both YouTube channel and analytics permissions are required."
            )
        channel_data = client.get_my_channel(access_token=access_token)
    except (YouTubeAuthorizationError, YouTubeAPIError, YouTubeConfigurationError) as exc:
        raise ValidationError({"youtube": str(exc)}) from exc

    channel_id = str(channel_data.get("id") or "")
    if not channel_id:
        raise ValidationError({"youtube": "Google returned an invalid channel."})

    existing_owner = YouTubeChannel.objects.filter(
        youtube_channel_id=channel_id
    ).exclude(user=user).exists()
    if existing_owner:
        raise ValidationError(
            {"youtube": "This YouTube channel is already connected to another account."}
        )

    existing = YouTubeChannel.objects.filter(user=user).first()
    channel_changed = bool(
        existing and existing.youtube_channel_id != channel_id
    )
    refresh_token = str(token_data.get("refresh_token") or "")
    if refresh_token:
        encrypted_refresh_token = encrypt_refresh_token(refresh_token)
    elif existing and not channel_changed:
        encrypted_refresh_token = existing.encrypted_refresh_token
    else:
        raise ValidationError(
            {"youtube": "Google did not return offline access. Please connect again."}
        )

    defaults = normalize_channel_defaults(
        channel_data=channel_data,
        encrypted_refresh_token=encrypted_refresh_token,
        granted_scopes=sorted(granted_scopes or set(YOUTUBE_SCOPES)),
    )
    if channel_changed:
        defaults["last_analyzed_at"] = None

    try:
        with transaction.atomic():
            channel, _ = YouTubeChannel.objects.update_or_create(
                user=user,
                defaults={"youtube_channel_id": channel_id, **defaults},
            )
            if channel_changed:
                YouTubeChannelAnalysis.objects.filter(channel=channel).delete()
            return channel
    except IntegrityError as exc:
        raise ValidationError(
            {"youtube": "Could not connect this YouTube channel."}
        ) from exc


def get_youtube_channel(*, user_id: int) -> YouTubeChannel:
    channel = YouTubeChannel.objects.filter(user_id=user_id).first()
    if channel is None:
        raise NotFound("No YouTube channel is connected.")
    return channel


def get_youtube_analysis(*, user_id: int) -> YouTubeChannelAnalysis:
    channel = get_youtube_channel(user_id=user_id)
    try:
        return channel.analysis
    except YouTubeChannelAnalysis.DoesNotExist as exc:
        raise NotFound("This YouTube channel has not been analyzed yet.") from exc


def disconnect_youtube_channel(
    *,
    user_id: int,
    youtube_client: ConnectedYouTubeClient | None = None,
) -> None:
    channel = get_youtube_channel(user_id=user_id)
    try:
        refresh_token = decrypt_refresh_token(channel.encrypted_refresh_token)
        client = youtube_client or ConnectedYouTubeClient()
        client.revoke_token(token=refresh_token)
    except (YouTubeAPIError, YouTubeConfigurationError, ValidationError):
        # Local deletion must still succeed when Google is temporarily unavailable.
        pass
    channel.delete()


def analyze_youtube_channel(
    *,
    user_id: int,
    youtube_client: ConnectedYouTubeClient | None = None,
    llm_client: TextGenerationClient | None = None,
    now: datetime | None = None,
) -> tuple[YouTubeChannelAnalysis, bool]:
    channel = get_youtube_channel(user_id=user_id)
    current_time = now or timezone.now()
    refresh_after = current_time - timedelta(
        minutes=settings.YOUTUBE_ANALYSIS_REFRESH_MINUTES
    )
    existing_analysis = YouTubeChannelAnalysis.objects.filter(channel=channel).first()
    if (
        existing_analysis
        and channel.last_analyzed_at
        and channel.last_analyzed_at >= refresh_after
    ):
        return existing_analysis, True

    client = youtube_client or ConnectedYouTubeClient()
    try:
        refresh_token = decrypt_refresh_token(channel.encrypted_refresh_token)
        access_token = client.refresh_access_token(refresh_token=refresh_token)
        channel_data = client.get_my_channel(access_token=access_token)
        update_channel_metadata(channel=channel, channel_data=channel_data)

        uploads = client.get_upload_video_ids(
            access_token=access_token,
            uploads_playlist_id=channel.uploads_playlist_id,
            max_results=50,
        )
        selected_uploads, period_start, period_end = select_analysis_videos(
            uploads=uploads,
            today=current_time.date(),
        )
        if not selected_uploads:
            raise ValidationError(
                {"videos": "This YouTube channel does not have any uploaded videos."}
            )

        selected_ids = [item["video_id"] for item in selected_uploads]
        video_data = client.get_videos(
            access_token=access_token,
            video_ids=selected_ids,
        )
        video_rows = client.query_analytics(
            access_token=access_token,
            start_date=period_start.isoformat(),
            end_date=period_end.isoformat(),
            dimensions=["video"],
            metrics=VIDEO_ANALYTICS_METRICS,
            filters=f"video=={','.join(selected_ids)}",
            max_results=settings.YOUTUBE_ANALYSIS_MAX_VIDEOS,
        )
        daily_start = max(period_end - timedelta(days=27), period_start)
        daily_rows = client.query_analytics(
            access_token=access_token,
            start_date=daily_start.isoformat(),
            end_date=period_end.isoformat(),
            dimensions=["day"],
            metrics=DAILY_ANALYTICS_METRICS,
            max_results=31,
        )
    except YouTubeAuthorizationError as exc:
        channel.status = YouTubeChannel.Status.REAUTH_REQUIRED
        channel.save(update_fields=["status", "updated_at"])
        raise ValidationError({"youtube": str(exc)}) from exc
    except (YouTubeAPIError, YouTubeConfigurationError) as exc:
        raise ValidationError({"youtube": str(exc)}) from exc

    records = build_video_records(
        selected_uploads=selected_uploads,
        video_data=video_data,
        analytics_rows=video_rows,
        period_start=period_start,
        period_end=period_end,
    )
    result = build_analysis_result(records=records, daily_rows=daily_rows)
    result["content_gaps"] = enhance_gap_explanations(
        gaps=result["content_gaps"],
        summary=result["summary"],
        llm_client=llm_client,
    )
    result["recommendations"] = [
        gap["recommendation"]
        for gap in result["content_gaps"]
        if gap.get("recommendation")
    ]

    with transaction.atomic():
        analysis, _ = YouTubeChannelAnalysis.objects.update_or_create(
            channel=channel,
            defaults={
                "period_start": period_start,
                "period_end": period_end,
                "videos_analyzed": len(records),
                **result,
            },
        )
        channel.last_analyzed_at = current_time
        channel.status = YouTubeChannel.Status.CONNECTED
        channel.save(
            update_fields=["last_analyzed_at", "status", "updated_at"]
        )
    return analysis, False


def normalize_channel_defaults(
    *,
    channel_data: dict[str, Any],
    encrypted_refresh_token: str,
    granted_scopes: list[str],
) -> dict[str, Any]:
    snippet = channel_data.get("snippet", {})
    details = channel_data.get("contentDetails", {})
    statistics = channel_data.get("statistics", {})
    return {
        "title": str(snippet.get("title") or "YouTube channel"),
        "thumbnail_url": get_thumbnail_url(snippet),
        "uploads_playlist_id": str(
            details.get("relatedPlaylists", {}).get("uploads") or ""
        ),
        "encrypted_refresh_token": encrypted_refresh_token,
        "granted_scopes": granted_scopes,
        "status": YouTubeChannel.Status.CONNECTED,
        "subscriber_count": parse_int(statistics.get("subscriberCount")),
        "video_count": parse_int(statistics.get("videoCount")),
        "view_count": parse_int(statistics.get("viewCount")),
    }


def update_channel_metadata(
    *,
    channel: YouTubeChannel,
    channel_data: dict[str, Any],
) -> None:
    defaults = normalize_channel_defaults(
        channel_data=channel_data,
        encrypted_refresh_token=channel.encrypted_refresh_token,
        granted_scopes=channel.granted_scopes,
    )
    for field, value in defaults.items():
        setattr(channel, field, value)
    channel.youtube_channel_id = str(channel_data.get("id") or channel.youtube_channel_id)
    channel.save()


def select_analysis_videos(
    *,
    uploads: list[dict[str, str]],
    today: date,
) -> tuple[list[dict[str, str]], date, date]:
    end_date = today - timedelta(days=1)
    default_start = end_date - timedelta(days=settings.YOUTUBE_ANALYSIS_DAYS - 1)
    normalized = []
    for upload in uploads:
        published_at = parse_youtube_datetime(upload.get("published_at", ""))
        if published_at is None:
            continue
        normalized.append({**upload, "published_date": published_at.date()})

    normalized.sort(key=lambda item: item["published_date"], reverse=True)
    recent = [item for item in normalized if item["published_date"] >= default_start]
    selected = recent[: settings.YOUTUBE_ANALYSIS_MAX_VIDEOS]
    if len(selected) < settings.YOUTUBE_ANALYSIS_MIN_VIDEOS:
        selected = normalized[: settings.YOUTUBE_ANALYSIS_MIN_VIDEOS]

    if not selected:
        return [], default_start, end_date

    earliest_selected = min(item["published_date"] for item in selected)
    period_start = min(default_start, earliest_selected)
    return selected, period_start, end_date


def build_video_records(
    *,
    selected_uploads: list[dict[str, Any]],
    video_data: list[dict[str, Any]],
    analytics_rows: list[dict[str, Any]],
    period_start: date,
    period_end: date,
) -> list[dict[str, Any]]:
    video_map = {str(item.get("id")): item for item in video_data}
    analytics_map = {str(item.get("video")): item for item in analytics_rows}
    records = []

    for upload in selected_uploads:
        video_id = upload["video_id"]
        item = video_map.get(video_id)
        if item is None:
            continue
        snippet = item.get("snippet", {})
        statistics = item.get("statistics", {})
        analytics = analytics_map.get(video_id, {})
        published_date = upload["published_date"]
        active_start = max(period_start, published_date)
        active_days = max((period_end - active_start).days + 1, 1)
        views = parse_int(analytics.get("views"))
        likes = parse_int(analytics.get("likes"))
        comments = parse_int(analytics.get("comments"))
        shares = parse_int(analytics.get("shares"))
        subscribers_gained = parse_int(analytics.get("subscribersGained"))

        records.append(
            {
                "video_id": video_id,
                "title": str(snippet.get("title") or ""),
                "description": str(snippet.get("description") or ""),
                "tags": [str(tag) for tag in snippet.get("tags", [])[:15]],
                "published_at": str(snippet.get("publishedAt") or ""),
                "published_date": published_date,
                "duration_seconds": parse_duration_seconds(
                    str(item.get("contentDetails", {}).get("duration") or "")
                ),
                "thumbnail_url": get_thumbnail_url(snippet),
                "current_view_count": parse_int(statistics.get("viewCount")),
                "current_like_count": parse_int(statistics.get("likeCount")),
                "current_comment_count": parse_int(statistics.get("commentCount")),
                "views": views,
                "estimated_minutes_watched": parse_float(
                    analytics.get("estimatedMinutesWatched")
                ),
                "average_view_duration": parse_float(
                    analytics.get("averageViewDuration")
                ),
                "average_view_percentage": parse_float(
                    analytics.get("averageViewPercentage")
                ),
                "likes": likes,
                "comments": comments,
                "shares": shares,
                "subscribers_gained": subscribers_gained,
                "subscribers_lost": parse_int(analytics.get("subscribersLost")),
                "views_per_day": round(views / active_days, 2),
                "engagement_per_1000_views": safe_rate(
                    likes + comments + shares, views
                ),
                "subscribers_per_1000_views": safe_rate(
                    subscribers_gained, views
                ),
            }
        )
    return records


def build_analysis_result(
    *,
    records: list[dict[str, Any]],
    daily_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    total_views = sum(item["views"] for item in records)
    weighted_retention = weighted_average(
        [(item["average_view_percentage"], item["views"]) for item in records]
    )
    total_subscribers_gained = sum(item["subscribers_gained"] for item in records)
    total_subscribers_lost = sum(item["subscribers_lost"] for item in records)
    publish_intervals = calculate_publish_intervals(records)
    summary = {
        "videos_analyzed": len(records),
        "total_views": total_views,
        "estimated_minutes_watched": round(
            sum(item["estimated_minutes_watched"] for item in records), 2
        ),
        "average_view_percentage": round(weighted_retention, 2),
        "subscribers_gained": total_subscribers_gained,
        "subscribers_lost": total_subscribers_lost,
        "subscribers_per_1000_views": safe_rate(
            total_subscribers_gained, total_views
        ),
        "average_days_between_uploads": round(
            sum(publish_intervals) / len(publish_intervals), 1
        )
        if publish_intervals
        else 0,
    }

    ranked = sorted(records, key=lambda item: item["views_per_day"], reverse=True)
    top_videos = [public_video_result(item) for item in ranked[:5]]
    weak_videos = [public_video_result(item) for item in reversed(ranked[-5:])]
    gaps = detect_content_gaps(records=records, summary=summary)

    return {
        "summary": summary,
        "top_videos": top_videos,
        "weak_videos": weak_videos,
        "content_gaps": gaps,
        "recommendations": [gap["recommendation"] for gap in gaps],
        "raw_metrics": {
            "daily_channel": daily_rows,
            "videos": [public_video_result(item) for item in records],
        },
    }


def detect_content_gaps(
    *,
    records: list[dict[str, Any]],
    summary: dict[str, Any],
) -> list[dict[str, Any]]:
    if not records:
        return []

    gaps = []
    views_per_day_values = [item["views_per_day"] for item in records]
    view_median = median(views_per_day_values) if views_per_day_values else 0

    topic_gap = detect_topic_gap(records=records, channel_median=view_median)
    if topic_gap:
        gaps.append(topic_gap)

    retention_average = float(summary.get("average_view_percentage") or 0)
    retention_limit = min(max(retention_average * 0.75, 25), 35)
    low_retention = [
        item
        for item in records
        if item["views_per_day"] >= view_median
        and 0 < item["average_view_percentage"] < retention_limit
    ]
    if low_retention:
        weakest = min(low_retention, key=lambda item: item["average_view_percentage"])
        gaps.append(
            make_gap(
                gap_type="RETENTION_GAP",
                severity="HIGH" if weakest["average_view_percentage"] < 25 else "MEDIUM",
                title="Improve viewer retention on promising videos",
                explanation=(
                    f'"{weakest["title"]}" receives meaningful views but retains only '
                    f'{weakest["average_view_percentage"]:.1f}% of each view on average.'
                ),
                recommendation=(
                    "Shorten the introduction, show the result earlier, and remove slow sections."
                ),
                video_ids=[weakest["video_id"]],
            )
        )

    subscriber_rates = [
        item["subscribers_per_1000_views"]
        for item in records
        if item["views"] > 0
    ]
    subscriber_median = median(subscriber_rates) if subscriber_rates else 0
    weak_conversion = [
        item
        for item in records
        if item["views_per_day"] >= view_median
        and subscriber_median > 0
        and item["subscribers_per_1000_views"] < subscriber_median * 0.5
    ]
    if weak_conversion:
        item = min(
            weak_conversion,
            key=lambda video: video["subscribers_per_1000_views"],
        )
        gaps.append(
            make_gap(
                gap_type="SUBSCRIBER_GAP",
                severity="MEDIUM",
                title="Turn high-view videos into more subscribers",
                explanation=(
                    f'"{item["title"]}" gets views but converts only '
                    f'{item["subscribers_per_1000_views"]:.2f} subscribers per 1,000 views.'
                ),
                recommendation=(
                    "Add a clear channel promise and point viewers to the next related video."
                ),
                video_ids=[item["video_id"]],
            )
        )

    engagement_rates = [
        item["engagement_per_1000_views"] for item in records if item["views"] > 0
    ]
    engagement_median = median(engagement_rates) if engagement_rates else 0
    weak_engagement = [
        item
        for item in records
        if item["views_per_day"] >= view_median
        and engagement_median > 0
        and item["engagement_per_1000_views"] < engagement_median * 0.6
    ]
    if weak_engagement:
        item = min(
            weak_engagement,
            key=lambda video: video["engagement_per_1000_views"],
        )
        gaps.append(
            make_gap(
                gap_type="ENGAGEMENT_GAP",
                severity="MEDIUM",
                title="Create a stronger reason to respond",
                explanation=(
                    f'"{item["title"]}" has weaker likes, comments, and shares than '
                    "other videos with similar reach."
                ),
                recommendation=(
                    "End with one specific audience question instead of a general request to comment."
                ),
                video_ids=[item["video_id"]],
            )
        )

    average_interval = float(summary.get("average_days_between_uploads") or 0)
    if average_interval > 14:
        gaps.append(
            make_gap(
                gap_type="PUBLISHING_GAP",
                severity="HIGH" if average_interval > 30 else "MEDIUM",
                title="Publish more consistently",
                explanation=(
                    f"The analyzed videos are published about every {average_interval:.1f} days."
                ),
                recommendation=(
                    "Choose a realistic recurring schedule and prepare the next two videos together."
                ),
                video_ids=[],
            )
        )

    return gaps[:5]


def detect_topic_gap(
    *,
    records: list[dict[str, Any]],
    channel_median: float,
) -> dict[str, Any] | None:
    topic_videos: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        keywords = extract_topic_keywords(record)
        for keyword in keywords:
            topic_videos[keyword].append(record)

    candidates = []
    for keyword, videos in topic_videos.items():
        if len(videos) < 2 or len(videos) > max(math.ceil(len(records) * 0.6), 3):
            continue
        average_views_per_day = sum(item["views_per_day"] for item in videos) / len(videos)
        if channel_median > 0 and average_views_per_day >= channel_median * 1.3:
            candidates.append((average_views_per_day, keyword, videos))

    if not candidates:
        return None
    average_views, keyword, videos = max(candidates, key=lambda item: item[0])
    multiplier = average_views / channel_median if channel_median else 0
    return make_gap(
        gap_type="TOPIC_GAP",
        severity="HIGH" if multiplier >= 2 else "MEDIUM",
        title=f"Create more content about {keyword}",
        explanation=(
            f"Videos about {keyword} generate about {multiplier:.1f}× the channel's "
            "median daily views."
        ),
        recommendation=f"Publish a focused follow-up or short series about {keyword}.",
        video_ids=[item["video_id"] for item in videos[:5]],
    )


def enhance_gap_explanations(
    *,
    gaps: list[dict[str, Any]],
    summary: dict[str, Any],
    llm_client: TextGenerationClient | None,
) -> list[dict[str, Any]]:
    if not gaps:
        return gaps
    try:
        client = llm_client or TextGenerationClient()
        generated = client.generate_json(
            system_prompt=(
                "You are a concise YouTube channel coach. Rewrite only the explanation and "
                "recommendation for each supplied gap. Preserve every type, title, severity, "
                "and evidence_video_ids value. Do not invent metrics. Return JSON as "
                '{"gaps": [{"type": "...", "explanation": "...", '
                '"recommendation": "..."}]}.'
            ),
            user_payload={"summary": summary, "gaps": gaps},
            temperature=0.2,
        )
    except Exception:
        return gaps

    generated_gaps = generated.get("gaps", []) if isinstance(generated, dict) else []
    generated_by_type = {
        str(item.get("type")): item
        for item in generated_gaps
        if isinstance(item, dict) and item.get("type")
    }
    enhanced = []
    for gap in gaps:
        replacement = generated_by_type.get(gap["type"], {})
        enhanced.append(
            {
                **gap,
                "explanation": str(
                    replacement.get("explanation") or gap["explanation"]
                )[:1000],
                "recommendation": str(
                    replacement.get("recommendation") or gap["recommendation"]
                )[:1000],
            }
        )
    return enhanced


def make_gap(
    *,
    gap_type: str,
    severity: str,
    title: str,
    explanation: str,
    recommendation: str,
    video_ids: list[str],
) -> dict[str, Any]:
    return {
        "type": gap_type,
        "severity": severity,
        "title": title,
        "explanation": explanation,
        "recommendation": recommendation,
        "evidence_video_ids": video_ids,
    }


def extract_topic_keywords(record: dict[str, Any]) -> list[str]:
    title_words = re.findall(r"[a-z0-9]+", record["title"].lower())
    tag_words = [word.lower().strip() for word in record.get("tags", [])]
    candidates = [
        word
        for word in [*title_words, *tag_words]
        if 3 < len(word) < 35 and word not in STOP_WORDS and not word.isdigit()
    ]
    return list(dict.fromkeys(candidates))[:8]


def public_video_result(record: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "video_id",
        "title",
        "published_at",
        "duration_seconds",
        "thumbnail_url",
        "views",
        "views_per_day",
        "average_view_duration",
        "average_view_percentage",
        "likes",
        "comments",
        "shares",
        "subscribers_gained",
        "subscribers_lost",
        "engagement_per_1000_views",
        "subscribers_per_1000_views",
    )
    return {field: record[field] for field in fields}


def calculate_publish_intervals(records: list[dict[str, Any]]) -> list[int]:
    dates = sorted(
        {item["published_date"] for item in records},
        reverse=True,
    )
    return [(dates[index] - dates[index + 1]).days for index in range(len(dates) - 1)]


def encrypt_refresh_token(value: str) -> str:
    return get_token_cipher().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_refresh_token(value: str) -> str:
    try:
        return get_token_cipher().decrypt(value.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValidationError(
            {"youtube": "Stored YouTube authorization is invalid. Please reconnect."}
        ) from exc


def get_token_cipher() -> Fernet:
    key_source = settings.YOUTUBE_TOKEN_ENCRYPTION_KEY or settings.SECRET_KEY
    digest = hashlib.sha256(str(key_source).encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def get_thumbnail_url(snippet: dict[str, Any]) -> str:
    thumbnails = snippet.get("thumbnails", {})
    for key in ("maxres", "standard", "high", "medium", "default"):
        url = thumbnails.get(key, {}).get("url")
        if url:
            return str(url)
    return ""


def parse_youtube_datetime(value: str) -> datetime | None:
    parsed = parse_datetime(value)
    if parsed is None:
        return None
    if timezone.is_naive(parsed):
        return parsed.replace(tzinfo=datetime_timezone.utc)
    return parsed


def parse_duration_seconds(value: str) -> int:
    match = re.fullmatch(
        r"P(?:(?P<days>\d+)D)?T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?",
        value,
    )
    if not match:
        return 0
    parts = {key: int(number or 0) for key, number in match.groupdict().items()}
    return (
        parts["days"] * 86400
        + parts["hours"] * 3600
        + parts["minutes"] * 60
        + parts["seconds"]
    )


def parse_int(value: Any) -> int:
    try:
        return max(int(float(value or 0)), 0)
    except (TypeError, ValueError):
        return 0


def parse_float(value: Any) -> float:
    try:
        return max(float(value or 0), 0.0)
    except (TypeError, ValueError):
        return 0.0


def safe_rate(numerator: int | float, denominator: int | float) -> float:
    if not denominator:
        return 0.0
    return round(float(numerator) / float(denominator) * 1000, 2)


def weighted_average(values: list[tuple[float, int]]) -> float:
    total_weight = sum(weight for _, weight in values)
    if not total_weight:
        non_zero = [value for value, _ in values if value]
        return sum(non_zero) / len(non_zero) if non_zero else 0.0
    return sum(value * weight for value, weight in values) / total_weight
