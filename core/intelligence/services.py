"""Shared niche collection, with one persistent discovery reservation."""
import hashlib
import json
import statistics
import unicodedata
from collections import Counter, defaultdict
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime, parse_duration

from . import web_client
from .models import (
    CompetitorBaseline, EvidenceMode, NichePool, NichePoolChannel,
    PublicChannel, TrendSignal, VideoStatSnapshot, YouTubeVideo,
)
from .youtube_client import PublicYouTubeClient


def _text(value):
    if isinstance(value, list):
        value = " ".join(sorted(str(item) for item in value))
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return " ".join("".join(
        char if unicodedata.category(char)[0] in {"L", "N", "M"} else " "
        for char in normalized
    ).split())


def canonical_definition(profile):
    aliases = {
        "topic": ("core_topic", "topic"),
        "audience": ("target_audience", "audience"),
        "language": ("primary_language", "language"),
        "geography": ("geographic_focus", "geography", "region_code"),
        "format": ("main_content_formats", "formats", "format"),
        "intent": ("intent", "audience_intent"),
    }
    return {
        key: _text(next((profile[name] for name in names if profile.get(name)), ""))
        for key, names in aliases.items()
    }


def get_or_create_niche_pool(profile):
    definition = canonical_definition(profile)
    pools = NichePool.objects.filter(
        definition__language=definition["language"],
        definition__geography=definition["geography"],
    )
    for pool in pools:
        same_context = all(
            pool.definition.get(key) == definition[key]
            for key in ("audience", "format", "intent")
        )
        if same_context:
            left = set(definition["topic"].split())
            right = set(pool.definition.get("topic", "").split())
            if left and right and len(left & right) / len(left | right) >= 0.85:
                return pool, False
    identity_definition = {
        **definition, "topic": " ".join(sorted(definition["topic"].split())),
    }
    identity = hashlib.sha256(
        json.dumps(identity_definition, sort_keys=True).encode()
    ).hexdigest()
    name = " ".join(filter(None, [definition["language"], definition["topic"]]))
    return NichePool.objects.get_or_create(
        identity=identity, defaults={"name": name[:255], "definition": definition},
    )


def store_channel(item):
    snippet = item.get("snippet", {})
    playlists = item.get("contentDetails", {}).get("relatedPlaylists", {})
    return PublicChannel.objects.update_or_create(
        youtube_channel_id=item["id"],
        defaults={
            "title": snippet.get("title", ""),
            "description": snippet.get("description", ""),
            "uploads_playlist_id": playlists.get("uploads", ""),
            "language": snippet.get("defaultLanguage", ""),
            "metadata": item,
            "fetched_at": timezone.now(),
            "expires_at": timezone.now() + timedelta(days=7),
        },
    )[0]


def store_videos(items):
    stored = []
    now = timezone.now()
    for item in items:
        snippet = item.get("snippet", {})
        channel = PublicChannel.objects.filter(
            youtube_channel_id=snippet.get("channelId", ""),
        ).first()
        published = parse_datetime(snippet.get("publishedAt", ""))
        if not channel or not published:
            continue
        duration = parse_duration(item.get("contentDetails", {}).get("duration", "PT0S"))
        seconds = max(0, int(duration.total_seconds())) if duration else 0
        stats = item.get("statistics", {})
        if not str(stats.get("viewCount", "")).isdigit():
            # Missing statistics are unavailable, not measured zero views.
            continue
        count_fields = {
            "view_count": "viewCount", "like_count": "likeCount",
            "comment_count": "commentCount",
        }
        counts = {
            field: int(stats.get(api, 0) or 0)
            for field, api in count_fields.items()
        }
        defaults = {
            "channel": channel, "title": snippet.get("title", ""),
            "description": snippet.get("description", ""),
            "published_at": published, "duration_seconds": seconds,
            # Data API exposes no definitive Shorts flag: isolate ambiguous brief videos.
            "format": "brief_unknown" if seconds <= 180 else "long", "metadata": item,
            "fetched_at": now, "expires_at": now + timedelta(days=1), **counts,
        }
        video, _ = YouTubeVideo.objects.update_or_create(
            youtube_video_id=item["id"], defaults=defaults,
        )
        VideoStatSnapshot.objects.create(
            video=video, fetched_at=now,
            expires_at=now + timedelta(days=30), **counts,
        )
        stored.append(video)
    return stored


def _matches(pool, text):
    topic = pool.definition.get("topic", pool.definition.get("core_topic", ""))
    stop_words = {
        "and", "the", "for", "with", "video", "videos", "content", "guide", "vlog",
    }
    tokens = set(_text(topic).split()) - stop_words
    matches = len(tokens & set(_text(text).split()))
    return bool(tokens and matches >= max(1, (len(tokens) + 1) // 2))


def _language_code(value):
    codes = {
        "bangla": "bn", "bengali": "bn", "english": "en", "hindi": "hi",
        "spanish": "es", "japanese": "ja",
    }
    return codes.get(value, value if len(value) == 2 else "")


def video_matches_niche(pool, video):
    return _matches(pool, video.title + " " + video.description)


def _candidate_channels(client, pool, ids):
    channels = []
    expected = _language_code(pool.definition.get("language", ""))
    own_channels = set(pool.creator_profiles.values_list(
        "connection__youtube_channel_id", flat=True,
    ))
    for item in client.channels(list(dict.fromkeys(ids))[:50]):
        if item.get("id") in own_channels:
            continue
        channel = store_channel(item)
        actual = channel.language.split("-")[0].lower()
        if channel.uploads_playlist_id and not (expected and actual and expected != actual):
            channels.append(channel)
    return channels


def _load_uploads(client, channels):
    ids = []
    for channel in channels:
        ids.extend(
            item.get("contentDetails", {}).get("videoId", "")
            for item in client.uploads(channel.uploads_playlist_id)
        )
    unique_ids = list(dict.fromkeys(value for value in ids if value))
    return store_videos(client.videos(unique_ids))


def _age_bucket(video, now):
    days = max(0, (now - video.published_at).days)
    for maximum, label in [(7, "0-7d"), (30, "8-30d"), (90, "31-90d"), (365, "91-365d")]:
        if days <= maximum:
            return label
    return "over-365d"


def discovery_due(pool, now):
    # Empty or failed discovery can recover tomorrow without spending a Search
    # request on each page load. Healthy competitor pools keep monthly discovery.
    has_channels = pool.memberships.filter(relevant=True).exists()
    cooldown = timedelta(days=30 if has_channels else 1)
    return pool.last_search_at is None or pool.last_search_at <= now - cooldown


def calculate_signals(pool, channels):
    now = timezone.now()
    signals = []
    TrendSignal.objects.filter(pool=pool).delete()
    for channel in channels:
        groups = defaultdict(list)
        recent_videos = channel.videos.filter(
            published_at__gte=now - timedelta(days=365), expires_at__gt=now,
        )
        for video in recent_videos:
            groups[(video.format, _age_bucket(video, now))].append(video)
        for (video_format, bucket), videos in groups.items():
            if video_format != "long":
                # Duration alone cannot reliably separate Shorts from long form.
                continue
            baseline_data = {
                "median_views": statistics.median(video.view_count for video in videos),
                "sample_size": len(videos),
                "confidence": min(0.8, len(videos) / 10), "evidence_mode": pool.evidence_mode,
                "fetched_at": now, "expires_at": pool.expires_at,
            }
            CompetitorBaseline.objects.update_or_create(
                channel=channel, format=video_format, age_bucket=bucket,
                defaults=baseline_data,
            )
            for video in videos:
                peers = [other.view_count for other in videos if other.pk != video.pk]
                if len(peers) < 3 or not video_matches_niche(pool, video):
                    continue
                median = statistics.median(peers)
                if median <= 0 or video.view_count / median < 2:
                    continue
                signals.append(TrendSignal.objects.create(
                    pool=pool,
                    video=video, outlier_multiplier=video.view_count / median,
                    details={
                        "baseline_views": median, "sample_size": len(peers),
                        "age_bucket": bucket, "format": video_format,
                        "format_note": "Only videos longer than 180 seconds are scored.",
                    },
                    confidence=min(pool.confidence, len(peers) / 10),
                    evidence_mode=pool.evidence_mode,
                    fetched_at=now, expires_at=pool.expires_at,
                ))
    appearances = defaultdict(set)
    for signal in signals:
        for token in _text(signal.video.title).split():
            if len(token) > 3:
                appearances[token].add(signal.video.channel_id)
    repeated = sorted(token for token, ids in appearances.items() if len(ids) >= 2)
    formats = defaultdict(set)
    for signal in signals:
        formats[signal.video.format].add(signal.video.channel_id)
    for signal in signals:
        signal.details["repeated_topics"] = repeated[:20]
        signal.details["repeated_formats"] = [
            name for name, channels in formats.items() if len(channels) >= 2
        ]
        signal.save(update_fields=["details"])


def refresh_niche_pool(pool_id, rediscover=False, expected_requested_at=None):
    now = timezone.now()
    with transaction.atomic():
        pool = NichePool.objects.select_for_update().get(pk=pool_id)
        if expected_requested_at is not None:
            expected = parse_datetime(expected_requested_at)
            if not expected or pool.refresh_requested_at != expected:
                return pool
        active = (
            pool.refresh_requested_at and
            pool.refresh_requested_at > now - timedelta(minutes=10)
        )
        if pool.status == "running" and active:
            return pool
        pool.status = "running"
        pool.refresh_requested_at = now
        pool.error_message = ""
        do_search = discovery_due(pool, now) and (
            rediscover or not pool.memberships.filter(relevant=True).exists()
        )
        if do_search:
            pool.last_search_at = now
        pool.save()
    client = PublicYouTubeClient(pool)
    try:
        # Audience, format and intent are relevance context, not search keywords.
        # Passing the entire profile to q can eliminate every useful result.
        query = pool.definition.get("topic", "").strip()[:200]
        if not query:
            raise ValueError("A channel topic is required for YouTube discovery.")
        if do_search:
            language = _language_code(pool.definition.get("language", ""))
            geography = pool.definition.get("geography", "")
            country_codes = {"bangladesh": "BD", "united states": "US", "japan": "JP"}
            region = country_codes.get(
                geography, geography.upper() if len(geography) == 2 else "",
            )
            found = client.search(query, language=language, region=region)
            scores = Counter()
            for item in found:
                snippet = item.get("snippet", {})
                text = snippet.get("title", "") + " " + snippet.get("description", "")
                if _matches(pool, text) and snippet.get("channelId"):
                    scores[snippet["channelId"]] += 1
            selected = _candidate_channels(
                client, pool, [key for key, _ in scores.most_common()],
            )[:5]
        else:
            memberships = pool.memberships.filter(
                relevant=True,
            ).select_related("channel")[:5]
            selected = [member.channel for member in memberships]
            expired = [
                channel.youtube_channel_id for channel in selected
                if not channel.expires_at or channel.expires_at <= now
            ]
            if expired:
                refreshed = {
                    channel.youtube_channel_id: channel
                    for channel in _candidate_channels(client, pool, expired)
                }
                selected = [
                    refreshed.get(channel.youtube_channel_id, channel)
                    for channel in selected
                    if channel.youtube_channel_id not in expired
                    or channel.youtube_channel_id in refreshed
                ]
        _load_uploads(client, selected)

        def useful(channel):
            recent = channel.videos.filter(
                published_at__gte=now - timedelta(days=180), fetched_at__gte=now,
            )
            return sum(video_matches_niche(pool, video) for video in recent) >= 2

        selected = [channel for channel in selected if useful(channel)]
        if not selected and do_search:
            try:
                pool.web_context = web_client.search_context(query)
            except Exception:
                pool.web_context = []
            video_ids, channel_ids = web_client.youtube_ids(pool.web_context)
            if video_ids:
                channel_ids.extend(
                    item.get("snippet", {}).get("channelId", "")
                    for item in client.videos(video_ids)
                )
            fallback = _candidate_channels(
                client, pool, [value for value in channel_ids if value],
            )[:5]
            _load_uploads(client, fallback)
            selected = [channel for channel in fallback if useful(channel)]
        count = len(selected)
        if count >= 3:
            pool.evidence_mode = EvidenceMode.EVIDENCE_BACKED
            pool.confidence = 0.75
        elif count:
            pool.evidence_mode = EvidenceMode.LIMITED_EVIDENCE
            pool.confidence = 0.45
        else:
            pool.evidence_mode = EvidenceMode.AI_FALLBACK
            pool.confidence = 0.2
        pool.fetched_at = timezone.now()
        cadence = getattr(settings, "INTELLIGENCE_POOL_REFRESH_HOURS", 24)
        if "breaking news" in pool.definition.get("topic", ""):
            cadence = 6
        elif selected and not any(channel.videos.filter(
            published_at__gte=now - timedelta(days=90)
        ).exists() for channel in selected):
            cadence = 72
        pool.expires_at = pool.fetched_at + timedelta(hours=cadence)
        with transaction.atomic():
            pool.memberships.update(relevant=False)
            for channel in selected:
                membership_data = {
                    "relevant": True, "confidence": pool.confidence,
                    "evidence_mode": pool.evidence_mode,
                    "fetched_at": pool.fetched_at, "expires_at": pool.expires_at,
                }
                NichePoolChannel.objects.update_or_create(
                    pool=pool, channel=channel, defaults=membership_data,
                )
            calculate_signals(pool, selected)
            pool.status = "succeeded"
            pool.refresh_requested_at = None
            pool.save()
        return pool
    except Exception:
        NichePool.objects.filter(pk=pool.pk).update(
            status="failed",
            error_message="Niche refresh failed. Existing evidence remains available.",
            refresh_requested_at=None,
        )
        raise
