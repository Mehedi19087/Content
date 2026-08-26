from __future__ import annotations

import logging
import math
import re
import secrets
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.core import signing
from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from categories.models import Category
from .llm_client import TextGenerationClient
from .models import ContentPackageJob, IdeaCandidate
from .openai_image_client import OpenAIImageClient, upload_creator_reference_image
from .youtube_client import YouTubeClient
from .youtube_suggest_client import YouTubeSuggestClient


MAX_IDEAS_PER_REFRESH = 10
MAX_INTENT_KEYWORDS = 6
THUMBNAIL_HOOK_ANGLES = ("curiosity", "shock", "fear")
CREATOR_IMAGE_TOKEN_SALT = "ideas.creator-image"
CREATOR_IMAGE_TOKEN_MAX_AGE_SECONDS = 60 * 60
BANNED_THUMBNAIL_HOOK_TEXTS = {
    "don't miss this",
    "nobody explains this",
    "this changed everything",
}
THUMBNAIL_RENDERING_BRIEF = """
Intended use: a premium YouTube thumbnail that remains instantly understandable at
320x180 pixels.
Composition: use one dominant focal subject, no more than two supporting visual
elements, clear foreground/midground/background separation, and intentional negative
space for the headline. Use an asymmetric rule-of-thirds or diagonal composition when
it strengthens the idea; do not make a flat collage.
Art direction: choose a specific visual language that fits this video's topic and
audience. Use a controlled two-to-three-color palette, strong subject/background
separation, realistic depth, and purposeful lighting. Tell the story through the
subject, action, and contrast instead of generic decoration. Avoid defaulting to neon
AI graphics, random dashboards, arrows, circles, flames, or shocked faces unless the
video idea genuinely requires them.
Typography: render the requested headline exactly once, with clean bold sans-serif
lettering, correct spelling, strong contrast, and no overlap with the focal subject.
Constraints: original visual design only; do not copy an existing thumbnail, creator,
artwork, or platform image. No extra text, logos, trademarks, watermarks, borders, or
unrelated objects.
""".strip()
logger = logging.getLogger(__name__)


class IdeaCronConfigurationError(RuntimeError):
    pass


BANNED_TITLE_PHRASES = {
    "exploring",
    "the future of",
    "impact on daily life",
    "opportunities and challenges",
    "various industries",
    "daily life",
    "potential is vast",
    "potential impact",
}

WEAK_WHY_NOW_PHRASES = {
    "has been gaining popularity",
    "is becoming increasingly important",
    "their potential is vast",
    "applications in daily life are vast",
    "potential is vast",
}

STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "how",
    "i",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "with",
    "you",
    "your",
}


def get_active_ideas(
    *,
    category_slug: str | None = None,
    region_code: str = "US",
    limit: int = MAX_IDEAS_PER_REFRESH,
) -> QuerySet[IdeaCandidate]:
    filters = {
        "category__is_active": True,
        "region_code": region_code,
        "is_active": True,
    }
    if category_slug:
        filters["category"] = get_active_category_by_slug(category_slug)

    return IdeaCandidate.objects.filter(**filters).order_by(
        "-trend_score",
        "-generated_at",
    )[:limit]


def get_active_idea(*, idea_id: int) -> IdeaCandidate:
    try:
        return IdeaCandidate.objects.get(
            id=idea_id,
            is_active=True,
            category__is_active=True,
        )
    except IdeaCandidate.DoesNotExist as exc:
        raise NotFound("Idea was not found.") from exc


def refresh_ideas_for_category(
    *,
    category_slug: str,
    region_code: str = "US",
    limit: int = MAX_IDEAS_PER_REFRESH,
) -> list[IdeaCandidate]:
    category = get_active_category_by_slug(category_slug)
    validate_category_region(category=category, region_code=region_code)

    youtube_client = YouTubeClient()
    videos = collect_youtube_videos(
        youtube_client=youtube_client,
        category=category,
        region_code=region_code,
    )

    if not videos:
        raise ValidationError(
            {"videos": "No usable YouTube videos found for this category and region."}
        )

    scored_videos = score_videos(videos, category=category)
    clusters = cluster_videos(scored_videos, limit=limit)
    ideas = generate_ideas_with_llm(
        category=category,
        region_code=region_code,
        clusters=clusters,
        limit=limit,
    )

    return save_idea_candidates(
        category=category,
        region_code=region_code,
        ideas=ideas,
        source_video_count=len(scored_videos),
    )


def verify_idea_cron_secret(provided_secret: str | None) -> None:
    configured_secret = settings.IDEA_CRON_SECRET
    if not configured_secret:
        raise IdeaCronConfigurationError("IDEA_CRON_SECRET is not configured.")
    if not provided_secret or not secrets.compare_digest(
        str(provided_secret),
        configured_secret,
    ):
        raise PermissionDenied("Invalid cron secret.")


def refresh_all_ideas_for_cron(
    *,
    region_code: str = "US",
    limit: int = MAX_IDEAS_PER_REFRESH,
) -> dict[str, Any]:
    categories = [
        category
        for category in Category.objects.filter(is_active=True).order_by("id")
        if region_code in category.default_regions
    ]
    if not categories:
        raise ValidationError(
            {"region_code": f"No active categories are enabled for {region_code}."}
        )

    results = []
    for category in categories:
        results.append(
            _refresh_category_with_retry(
                category=category,
                region_code=region_code,
                limit=limit,
            )
        )

    succeeded = sum(result["status"] == "succeeded" for result in results)
    return {
        "region_code": region_code,
        "total_categories": len(results),
        "succeeded": succeeded,
        "failed": len(results) - succeeded,
        "results": results,
    }


def _refresh_category_with_retry(
    *,
    category: Category,
    region_code: str,
    limit: int,
) -> dict[str, Any]:
    max_attempts = max(1, settings.IDEA_CRON_MAX_ATTEMPTS)
    for attempt in range(1, max_attempts + 1):
        try:
            ideas = refresh_ideas_for_category(
                category_slug=category.slug,
                region_code=region_code,
                limit=limit,
            )
            return {
                "category_slug": category.slug,
                "status": "succeeded",
                "attempts": attempt,
                "ideas_created": len(ideas),
                "error": "",
            }
        except Exception as exc:
            retryable = _is_retryable_refresh_error(exc)
            if attempt >= max_attempts or not retryable:
                log_failure = (
                    logger.warning
                    if isinstance(exc, ValidationError)
                    else logger.exception
                )
                log_failure(
                    "ideas.cron.category_failed category=%s attempt=%s "
                    "retryable=%s error=%s",
                    category.slug,
                    attempt,
                    retryable,
                    _format_refresh_error(exc),
                )
                return {
                    "category_slug": category.slug,
                    "status": "failed",
                    "attempts": attempt,
                    "ideas_created": 0,
                    "error": _format_refresh_error(exc),
                }

            delay = min(
                settings.IDEA_CRON_RETRY_BASE_SECONDS * (2 ** (attempt - 1)),
                settings.IDEA_CRON_RETRY_MAX_SECONDS,
            )
            logger.warning(
                "ideas.cron.category_retry category=%s attempt=%s delay=%s",
                category.slug,
                attempt,
                delay,
            )
            time.sleep(delay)

    raise RuntimeError("Unreachable idea refresh retry state.")


def _is_retryable_refresh_error(exc: Exception) -> bool:
    upstream_status = getattr(exc, "upstream_status_code", None)
    if upstream_status is not None:
        return upstream_status in (408, 429) or upstream_status >= 500
    if not isinstance(exc, ValidationError):
        return True

    detail = str(exc.detail).lower()
    transient_markers = (
        "http 408",
        "http 429",
        "http 500",
        "http 502",
        "http 503",
        "http 504",
        "rate limit",
        "timed out",
        "timeout",
        "temporarily unavailable",
        "connection reset",
        "connection refused",
    )
    return any(marker in detail for marker in transient_markers)


def _format_refresh_error(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return str(exc.detail)[:1000]
    return str(exc)[:1000] or exc.__class__.__name__


def research_youtube_intent_for_idea(
    *,
    idea: str,
    region_code: str = "US",
    language_code: str = "en",
    max_results: int = 5,
) -> dict[str, Any]:
    query = build_youtube_intent_query(idea)
    youtube_client = YouTubeClient()

    def fetch_suggestions():
        return _timed_research_provider_call(
            provider="youtube_suggest",
            operation="fetch_suggestions",
            callback=lambda: YouTubeSuggestClient().fetch_suggestions(
                query=query,
                region_code=region_code,
                language_code=language_code,
            ),
        )

    def search_videos():
        return _timed_research_provider_call(
            provider="youtube",
            operation="search_videos",
            callback=lambda: youtube_client.search_videos_by_query(
                query=query,
                region_code=region_code,
                language_code=language_code,
                max_results=max_results,
            ),
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        suggestions_future = executor.submit(fetch_suggestions)
        search_future = executor.submit(search_videos)
        search_suggestions = suggestions_future.result()
        search_results = search_future.result()

    video_ids = [item["video_id"] for item in search_results if item.get("video_id")]

    if not video_ids:
        raise ValidationError({"youtube_results": "No YouTube videos found for this idea."})

    videos = _timed_research_provider_call(
        provider="youtube",
        operation="fetch_video_details",
        callback=lambda: youtube_client.fetch_videos_by_ids(video_ids),
    )
    if not videos:
        raise ValidationError(
            {"youtube_results": "No YouTube video details found for this idea."}
        )

    normalized_videos = normalize_intent_videos(videos)
    if not normalized_videos:
        raise ValidationError(
            {"youtube_results": "No usable YouTube video metadata found for this idea."}
        )

    return analyze_youtube_intent(
        idea=idea,
        query=query,
        videos=normalized_videos,
        search_suggestions=search_suggestions,
    )


def _timed_research_provider_call(*, provider: str, operation: str, callback):
    started_at = time.perf_counter()
    outcome = "failed"
    try:
        result = callback()
        outcome = "succeeded"
        return result
    finally:
        logging.getLogger("ideas.performance").info(
            "ideas.provider_timing provider=%s operation=%s outcome=%s "
            "duration_seconds=%.3f",
            provider,
            operation,
            outcome,
            time.perf_counter() - started_at,
        )


def build_youtube_intent_query(idea: str) -> str:
    words = [
        word
        for word in re.findall(r"[a-zA-Z0-9]+", idea.lower())
        if word not in STOP_WORDS and len(word) > 1
    ]
    return " ".join(words[:8]) or idea.strip()


def normalize_intent_videos(videos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized_videos = []

    for video in videos:
        snippet = video.get("snippet", {})
        statistics = video.get("statistics", {})
        title = snippet.get("title", "").strip()
        description = snippet.get("description", "").strip()
        if not title:
            continue

        normalized_videos.append(
            {
                "video_id": video.get("id", ""),
                "title": title,
                "description": description,
                "channel_title": snippet.get("channelTitle", ""),
                "view_count": parse_int(statistics.get("viewCount")),
                "like_count": parse_int(statistics.get("likeCount")),
                "thumbnail_url": get_thumbnail_url(snippet),
                "tags": normalize_string_list(snippet.get("tags", [])),
            }
        )

    return normalized_videos


def analyze_youtube_intent(
    *,
    idea: str,
    query: str,
    videos: list[dict[str, Any]],
    search_suggestions: list[str] | None = None,
) -> dict[str, Any]:
    search_suggestions = normalize_string_list(search_suggestions or [])
    relevant_videos = filter_relevant_intent_videos(
        idea=idea,
        videos=videos,
    )
    relevant_suggestions = filter_relevant_phrases(
        idea=idea,
        phrases=search_suggestions,
    )
    analysis = generate_contextual_intent_analysis(
        idea=idea,
        query=query,
        videos=relevant_videos,
        search_suggestions=relevant_suggestions,
    )

    return {
        **analysis,
        "search_suggestions": relevant_suggestions,
    }


def generate_contextual_intent_analysis(
    *,
    idea: str,
    query: str,
    videos: list[dict[str, Any]],
    search_suggestions: list[str],
) -> dict[str, Any]:
    system_prompt = """
You are a YouTube audience-research and packaging strategist. Analyze the exact video
idea against only the supplied YouTube evidence. Return strict JSON with exactly these
top-level keys: viewer_intent, content_type, title_patterns, emotional_angles,
thumbnail_subjects, thumbnail_hooks, seo_keywords.

Grounding rules:
- Treat the video idea as the primary topic and promise.
- Discard evidence that is topically unrelated, even if YouTube returned it.
- Do not invent search demand, audience behavior, features, results, or facts.
- Make every field specific enough that it would not fit an unrelated video title.

Field rules:
- viewer_intent: one concise sentence describing the exact outcome, question, or
  tension this title's likely viewer wants resolved. Do not use a generic template.
- content_type: one precise format description for this title, not a broad fixed
  bucket when a more specific format is supported.
- title_patterns: exactly 3 concise reusable title structures grounded in recurring
  structures in the relevant evidence. Use placeholders such as [topic], [number],
  [result], or [constraint]; do not copy an evidence title.
- emotional_angles: exactly 3 distinct, title-specific viewer motivations or tensions.
  Explain each in a short phrase; avoid generic labels unsupported by the title.
- thumbnail_subjects: exactly 3 concise, concrete, visually renderable subject
  descriptions.
- thumbnail_subjects must help communicate this exact title and viewer promise.
- Prefer specific people, products, tools, objects, actions, outcomes, or visual
  metaphors named or clearly implied by the title and research.
- Make the three subjects work together in one uncluttered thumbnail composition.
- Do not return generic stock concepts such as a random laptop user, AI robot,
  glowing brain, busy workspace, arrows, or money unless the title specifically
  requires that exact subject.
- Do not include thumbnail text, logos, camera directions, art style, lighting,
  layout instructions, or explanations.
- Do not copy the subjects of evidence thumbnails; use evidence titles only to
  understand topic context.
- thumbnail_hooks: exactly 3 objects with keys angle and text. Use each angle exactly
  once: curiosity, shock, and fear. Each text must be 2 to 5 words, specific to the
  video title and viewer intent, easy to read at thumbnail size, and meaningfully
  different from the other two. Do not repeat the full title, use generic clickbait
  such as "Nobody Explains This", or promise a fact/result unsupported by evidence.
- seo_keywords: 4 to 6 natural search phrases tightly relevant to the exact idea.
  Prefer supported phrases from search suggestions, titles, and tags. Exclude
  unrelated phrases and generic standalone words such as idea, video, or tutorial.
""".strip()
    evidence = [
        {
            "title": video.get("title", ""),
            "description": video.get("description", "")[:300],
            "tags": normalize_string_list(video.get("tags", []))[:8],
            "view_count": video.get("view_count", 0),
            "like_count": video.get("like_count", 0),
        }
        for video in videos[:5]
    ]
    user_payload = {
        "video_title": idea,
        "youtube_query": query,
        "relevant_search_suggestions": search_suggestions[:5],
        "relevant_youtube_evidence": evidence,
    }
    fallback = build_contextual_intent_fallback(
        idea=idea,
        query=query,
        videos=videos,
        search_suggestions=search_suggestions,
    )

    try:
        generated = TextGenerationClient().generate_json(
            system_prompt=system_prompt,
            user_payload=user_payload,
            temperature=0.35,
        )
    except ValidationError:
        logger.warning(
            "Contextual intent generation failed; using evidence-derived fallback."
        )
        return fallback

    generated = generated if isinstance(generated, dict) else {}
    generated_keywords = normalize_generated_list(
        generated.get("seo_keywords"),
        fallback["seo_keywords"],
        limit=6,
    )
    grounded_keywords = filter_relevant_phrases(
        idea=idea,
        phrases=generated_keywords,
    )
    return {
        "viewer_intent": normalize_generated_text(
            generated.get("viewer_intent"),
            fallback["viewer_intent"],
        ),
        "content_type": normalize_generated_text(
            generated.get("content_type"),
            fallback["content_type"],
        ),
        "title_patterns": normalize_generated_list(
            generated.get("title_patterns"),
            fallback["title_patterns"],
            limit=3,
        ),
        "emotional_angles": normalize_generated_list(
            generated.get("emotional_angles"),
            fallback["emotional_angles"],
            limit=3,
        ),
        "thumbnail_subjects": normalize_generated_list(
            generated.get("thumbnail_subjects"),
            fallback["thumbnail_subjects"],
            limit=3,
        ),
        "thumbnail_hooks": normalize_thumbnail_hooks(
            generated.get("thumbnail_hooks"),
            fallback=fallback["thumbnail_hooks"],
        ),
        "seo_keywords": grounded_keywords or fallback["seo_keywords"],
    }


def build_contextual_intent_fallback(
    *,
    idea: str,
    query: str,
    videos: list[dict[str, Any]],
    search_suggestions: list[str],
) -> dict[str, Any]:
    evidence_titles = [video["title"] for video in videos if video.get("title")]
    patterns = [generalize_evidence_title(title, idea) for title in evidence_titles[:3]]
    patterns = [pattern for pattern in patterns if pattern]
    keywords = extract_seo_keywords(
        idea=idea,
        videos=videos,
        search_suggestions=search_suggestions,
    )
    search_context = ", ".join(search_suggestions[:2]) or query
    return {
        "viewer_intent": (
            f"Viewers researching {search_context} want the specific promise in "
            f"'{idea}' demonstrated clearly."
        ),
        "content_type": f"Evidence-based video matching the promise in '{idea}'",
        "title_patterns": patterns or [generalize_evidence_title(idea, idea)],
        "emotional_angles": [],
        "thumbnail_subjects": [idea.strip()],
        "thumbnail_hooks": build_thumbnail_hook_fallbacks(
            keywords[0] if keywords else idea
        ),
        "seo_keywords": keywords or [query],
    }


def normalize_generated_text(value: Any, fallback: str) -> str:
    normalized = str(value).strip() if value is not None else ""
    return normalized or fallback


def normalize_generated_list(value: Any, fallback: list[str], *, limit: int) -> list[str]:
    items = normalize_string_list(value)
    unique_items = list(dict.fromkeys(items))
    return (unique_items or fallback)[:limit]


def normalize_thumbnail_hooks(
    value: Any,
    *,
    fallback: list[dict[str, str]],
) -> list[dict[str, str]]:
    hooks_by_angle: dict[str, dict[str, str]] = {}
    used_text = set()

    if isinstance(value, list):
        for item in value:
            if not isinstance(item, dict):
                continue
            angle = str(item.get("angle", "")).strip().lower()
            text = " ".join(str(item.get("text", "")).split()).strip()
            word_count = len(text.split())
            normalized_text = text.casefold()
            if (
                angle not in THUMBNAIL_HOOK_ANGLES
                or angle in hooks_by_angle
                or not 2 <= word_count <= 5
                or len(text) > 40
                or normalized_text in used_text
                or normalized_text in BANNED_THUMBNAIL_HOOK_TEXTS
            ):
                continue
            hooks_by_angle[angle] = {"angle": angle, "text": text}
            used_text.add(normalized_text)

    for hook in fallback:
        angle = hook["angle"]
        if angle not in hooks_by_angle:
            hooks_by_angle[angle] = hook

    return [hooks_by_angle[angle] for angle in THUMBNAIL_HOOK_ANGLES]


def build_thumbnail_hook_fallbacks(topic_source: str) -> list[dict[str, str]]:
    topic = extract_short_topic(topic_source).title()
    return [
        {"angle": "curiosity", "text": f"Inside {topic}"},
        {"angle": "shock", "text": f"The {topic} Reality"},
        {"angle": "fear", "text": f"{topic} Mistakes"},
    ]


def intent_topic_terms(idea: str) -> set[str]:
    generic_terms = {
        "best",
        "guide",
        "idea",
        "ideas",
        "review",
        "test",
        "tested",
        "top",
        "tutorial",
        "video",
    }
    return {
        word
        for word in re.findall(r"[a-zA-Z0-9]+", idea.lower())
        if word not in STOP_WORDS
        and word not in generic_terms
        and not word.isdigit()
        and len(word) > 2
    }


def filter_relevant_phrases(*, idea: str, phrases: list[str]) -> list[str]:
    topic_terms = intent_topic_terms(idea)
    if not topic_terms:
        return phrases
    return [
        phrase
        for phrase in phrases
        if topic_terms.intersection(re.findall(r"[a-zA-Z0-9]+", phrase.lower()))
    ]


def filter_relevant_intent_videos(
    *,
    idea: str,
    videos: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    topic_terms = intent_topic_terms(idea)
    if not topic_terms:
        return videos
    relevant = []
    for video in videos:
        evidence_text = " ".join(
            [
                str(video.get("title", "")),
                str(video.get("description", ""))[:300],
                " ".join(normalize_string_list(video.get("tags", []))),
            ]
        ).lower()
        evidence_terms = set(re.findall(r"[a-zA-Z0-9]+", evidence_text))
        if topic_terms.intersection(evidence_terms):
            relevant.append(video)
    return relevant


def generalize_evidence_title(title: str, idea: str) -> str:
    pattern = re.sub(r"\b\d+\b", "[number]", title.strip())
    for term in sorted(intent_topic_terms(idea), key=len, reverse=True):
        pattern = re.sub(rf"\b{re.escape(term)}\b", "[topic]", pattern, flags=re.I)
    pattern = re.sub(r"(?:\[topic\]\s*){2,}", "[topic] ", pattern)
    return " ".join(pattern.split()).strip()


def prepare_thumbnail_from_intent(
    *,
    idea: str,
    youtube_intent: dict[str, Any],
) -> dict[str, Any]:
    subjects = normalize_string_list(youtube_intent.get("thumbnail_subjects", []))
    emotional_angles = normalize_string_list(youtube_intent.get("emotional_angles", []))
    seo_keywords = normalize_string_list(youtube_intent.get("seo_keywords", []))
    thumbnail_hooks = normalize_thumbnail_hooks(
        youtube_intent.get("thumbnail_hooks"),
        fallback=build_thumbnail_hook_fallbacks(
            seo_keywords[0] if seo_keywords else idea
        ),
    )
    content_type = str(youtube_intent.get("content_type", "")).strip()
    viewer_intent = str(youtube_intent.get("viewer_intent", "")).strip()

    subject_plan = build_thumbnail_subject_plan(
        subjects=subjects,
        idea=idea,
    )
    hook_cards = build_thumbnail_hook_cards(
        idea=idea,
        content_type=content_type,
        viewer_intent=viewer_intent,
        emotional_angles=emotional_angles,
        seo_keywords=seo_keywords,
        thumbnail_hooks=thumbnail_hooks,
    )

    return {
        "hook_cards": hook_cards,
        "subject_plan": subject_plan,
        "image_preparation": build_image_preparation(subject_plan),
        "creator_image": {
            "ask_user_for_own_image": True,
            "source": "profile_or_upload",
            "question": "Do you want to use your own image in the thumbnail?",
        },
    }


def build_thumbnail_subject_plan(
    *,
    subjects: list[str],
    idea: str,
) -> list[dict[str, Any]]:
    subject_plan = []
    selected_subjects = subjects[:3] or [idea.strip()]

    for subject in selected_subjects:
        subject_type = detect_thumbnail_subject_type(subject)
        source = "ai_generate"
        ai_prompt = build_subject_image_prompt(
            subject=subject,
            subject_type=subject_type,
            idea=idea,
        )

        subject_plan.append(
            {
                "type": subject_type,
                "role": "supporting_subject",
                "description": subject,
                "count": 1,
                "source": source,
                "ai_prompt": ai_prompt,
            }
        )

    return subject_plan


def detect_thumbnail_subject_type(subject: str) -> str:
    subject_lower = subject.lower()
    human_markers = (
        "person",
        "man",
        "woman",
        "boy",
        "girl",
        "student",
        "creator",
        "worker",
        "human",
        "face",
    )
    return "human" if any(marker in subject_lower for marker in human_markers) else "object"


def build_subject_image_prompt(
    *,
    subject: str,
    subject_type: str,
    idea: str,
) -> str:
    if subject_type == "human":
        return (
            f"Generate a photorealistic {subject} for a YouTube thumbnail about "
            f"{idea}. Clear facial expression, dramatic high contrast lighting, "
            "real camera look, clean composition, no text."
        )
    return (
        f"Generate a photorealistic object/scene of {subject} for a YouTube thumbnail "
        f"about {idea}. High contrast, clear shape, realistic detail, clean composition, "
        "no text."
    )


def build_image_preparation(subject_plan: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "uses_google_search": False,
        "all_non_creator_subjects_generated_by_ai": True,
        "ask_user_for_own_image": True,
        "ai_subject_prompts": [
            subject["ai_prompt"]
            for subject in subject_plan
            if subject.get("ai_prompt")
        ],
    }


def generate_content_package(
    *,
    idea: str,
    youtube_intent: dict[str, Any],
    selected_hook: dict[str, Any],
    subject_plan: list[dict[str, Any]],
    creator_image_choice: dict[str, Any] | None = None,
) -> dict[str, Any]:
    creator_image_choice = creator_image_choice or {}
    package_plan = generate_package_plan_with_llm(
        idea=idea,
        youtube_intent=youtube_intent,
        selected_hook=selected_hook,
        subject_plan=subject_plan,
        creator_image_choice=creator_image_choice,
    )
    thumbnail_prompt = package_plan["thumbnail_prompt"]
    creator_image_url = str(creator_image_choice.get("image_url", "")).strip()
    if creator_image_url:
        thumbnail_prompt = (
            "Use the uploaded creator photo as the identity reference. Preserve the "
            "creator's recognizable facial identity while adapting pose, expression, "
            "lighting, clothing, and background to the thumbnail composition. "
            f"{thumbnail_prompt}"
        )
    thumbnail_asset = OpenAIImageClient().generate_thumbnail(
        prompt=thumbnail_prompt,
        filename_prefix=slugify_phrase(idea),
        reference_image_url=creator_image_url,
    )

    return {
        "thumbnail": {
            "url": thumbnail_asset["url"],
            "public_id": thumbnail_asset["public_id"],
            "model": thumbnail_asset["model"],
            "size": thumbnail_asset["size"],
            "quality": thumbnail_asset["quality"],
            "selected_hook": selected_hook,
            "prompt": thumbnail_prompt,
            "used_subjects": subject_plan,
        },
        "seo": package_plan["seo"],
        "edit_options": package_plan["edit_options"],
    }


def create_content_package_job(*, user, request_payload: dict[str, Any]):
    request_payload = dict(request_payload)
    request_payload["creator_image_choice"] = resolve_creator_image_choice(
        user=user,
        creator_image_choice=request_payload.get("creator_image_choice", {}),
    )
    return ContentPackageJob.objects.create(
        user=user,
        job_type=ContentPackageJob.JobType.PACKAGE,
        request_payload=request_payload,
    )


def upload_creator_image(*, user, image_file) -> dict[str, str]:
    asset = upload_creator_reference_image(
        image_file=image_file,
        user_id=user.id,
    )
    asset_token = signing.dumps(
        {
            "user_id": user.id,
            "url": asset["url"],
            "public_id": asset["public_id"],
        },
        salt=CREATOR_IMAGE_TOKEN_SALT,
        compress=True,
    )
    return {"url": asset["url"], "asset_token": asset_token}


def resolve_creator_image_choice(
    *,
    user,
    creator_image_choice: dict[str, Any],
) -> dict[str, Any]:
    if not creator_image_choice or creator_image_choice.get("skip_creator_image"):
        return {"skip_creator_image": True}

    asset_token = str(creator_image_choice.get("asset_token", "")).strip()
    if not asset_token:
        raise ValidationError(
            {"creator_image_choice": "Upload a creator image before generating."}
        )
    try:
        asset = signing.loads(
            asset_token,
            salt=CREATOR_IMAGE_TOKEN_SALT,
            max_age=CREATOR_IMAGE_TOKEN_MAX_AGE_SECONDS,
        )
    except signing.SignatureExpired as exc:
        raise ValidationError(
            {"creator_image_choice": "Creator image upload expired. Upload it again."}
        ) from exc
    except signing.BadSignature as exc:
        raise ValidationError(
            {"creator_image_choice": "Creator image upload is invalid."}
        ) from exc

    if asset.get("user_id") != user.id:
        raise ValidationError(
            {"creator_image_choice": "Creator image upload is invalid."}
        )
    image_url = str(asset.get("url", "")).strip()
    public_id = str(asset.get("public_id", "")).strip()
    expected_prefix = f"creatorintent/creator_images/{user.id}/"
    if not image_url.startswith("https://res.cloudinary.com/") or not public_id.startswith(
        expected_prefix
    ):
        raise ValidationError(
            {"creator_image_choice": "Creator image upload is invalid."}
        )
    return {
        "skip_creator_image": False,
        "image_url": image_url,
        "public_id": public_id,
    }


def create_or_reuse_research_job(*, user, request_payload: dict[str, Any]):
    active_job = (
        ContentPackageJob.objects.filter(
            user=user,
            job_type=ContentPackageJob.JobType.RESEARCH,
            request_payload=request_payload,
            status__in=(
                ContentPackageJob.Status.PENDING,
                ContentPackageJob.Status.PROCESSING,
            ),
        )
        .order_by("-created_at")
        .first()
    )
    if active_job:
        return active_job, False

    cached_after = timezone.now() - timedelta(
        seconds=settings.YOUTUBE_RESEARCH_CACHE_SECONDS
    )
    cached_job = (
        ContentPackageJob.objects.filter(
            user=user,
            job_type=ContentPackageJob.JobType.RESEARCH,
            request_payload=request_payload,
            status=ContentPackageJob.Status.SUCCEEDED,
            finished_at__gte=cached_after,
        )
        .order_by("-finished_at")
        .first()
    )
    if cached_job and research_result_has_personalized_hooks(cached_job.result):
        return cached_job, False

    return (
        ContentPackageJob.objects.create(
            user=user,
            job_type=ContentPackageJob.JobType.RESEARCH,
            request_payload=request_payload,
        ),
        True,
    )


def research_result_has_personalized_hooks(result: Any) -> bool:
    if not isinstance(result, dict):
        return False
    hooks = result.get("thumbnail_hooks")
    if not isinstance(hooks, list):
        return False
    angles = {
        str(hook.get("angle", "")).strip().lower()
        for hook in hooks
        if isinstance(hook, dict) and str(hook.get("text", "")).strip()
    }
    return angles == set(THUMBNAIL_HOOK_ANGLES)


def create_script_job(*, user, request_payload: dict[str, Any]):
    return ContentPackageJob.objects.create(
        user=user,
        job_type=ContentPackageJob.JobType.SCRIPT,
        request_payload=request_payload,
    )


def get_content_package_job(*, user, job_id):
    try:
        job = ContentPackageJob.objects.get(id=job_id, user=user)
    except ContentPackageJob.DoesNotExist as exc:
        raise NotFound("Content package job was not found.") from exc

    stale_before = timezone.now() - timedelta(
        seconds=settings.CONTENT_PACKAGE_JOB_STALE_SECONDS
    )
    is_stale_pending = (
        job.status == ContentPackageJob.Status.PENDING
        and job.created_at < stale_before
    )
    is_stale_processing = (
        job.status == ContentPackageJob.Status.PROCESSING
        and job.started_at
        and job.started_at < stale_before
    )
    if is_stale_pending or is_stale_processing:
        ContentPackageJob.objects.filter(id=job.id, status=job.status).update(
            status=ContentPackageJob.Status.FAILED,
            stage="failed",
            error_code="generation_timed_out",
            error_message="Content package generation timed out. Please try again.",
            finished_at=timezone.now(),
            updated_at=timezone.now(),
        )
        job.refresh_from_db()
    return job


def mark_content_package_job_dispatched(*, job_id, task_id: str):
    ContentPackageJob.objects.filter(id=job_id).update(
        celery_task_id=task_id,
        updated_at=timezone.now(),
    )


def mark_content_package_job_queue_failed(*, job_id):
    ContentPackageJob.objects.filter(
        id=job_id,
        status=ContentPackageJob.Status.PENDING,
    ).update(
        status=ContentPackageJob.Status.FAILED,
        stage="failed",
        error_code="queue_unavailable",
        error_message="The background job could not be started. Please try again.",
        finished_at=timezone.now(),
        updated_at=timezone.now(),
    )


def start_content_package_job(
    *,
    job_id,
    expected_job_type=ContentPackageJob.JobType.PACKAGE,
    stage="generating_package",
):
    with transaction.atomic():
        try:
            job = ContentPackageJob.objects.select_for_update().get(id=job_id)
        except ContentPackageJob.DoesNotExist:
            logger.warning("ideas.package_job.not_found job_id=%s", job_id)
            return None

        if (
            job.status != ContentPackageJob.Status.PENDING
            or job.job_type != expected_job_type
        ):
            logger.info(
                "ideas.package_job.skipped job_id=%s status=%s",
                job_id,
                job.status,
            )
            return None

        job.status = ContentPackageJob.Status.PROCESSING
        job.stage = stage
        job.started_at = timezone.now()
        job.error_code = ""
        job.error_message = ""
        job.save(
            update_fields=[
                "status",
                "stage",
                "started_at",
                "error_code",
                "error_message",
                "updated_at",
            ]
        )
        return job


def mark_content_package_job_succeeded(*, job_id, result: dict[str, Any]):
    ContentPackageJob.objects.filter(
        id=job_id,
        status=ContentPackageJob.Status.PROCESSING,
    ).update(
        status=ContentPackageJob.Status.SUCCEEDED,
        stage="completed",
        result=result,
        finished_at=timezone.now(),
        updated_at=timezone.now(),
    )


def mark_content_package_job_failed(
    *,
    job_id,
    error_code="generation_failed",
    error_message="Generation failed. Please try again.",
):
    ContentPackageJob.objects.filter(
        id=job_id,
        status=ContentPackageJob.Status.PROCESSING,
    ).update(
        status=ContentPackageJob.Status.FAILED,
        stage="failed",
        error_code=error_code,
        error_message=error_message,
        finished_at=timezone.now(),
        updated_at=timezone.now(),
    )


def generate_package_plan_with_llm(
    *,
    idea: str,
    youtube_intent: dict[str, Any],
    selected_hook: dict[str, Any],
    subject_plan: list[dict[str, Any]],
    creator_image_choice: dict[str, Any],
) -> dict[str, Any]:
    system_prompt = """
You are a senior YouTube content strategist. Create one cohesive content package that
matches the video idea, researched viewer intent, selected hook, and visual direction.
Return strict JSON with exactly these top-level keys: thumbnail_prompt, seo,
edit_options.

thumbnail_prompt rules:
- Target a 16:9 YouTube thumbnail.
- Write thumbnail_prompt as a concise production creative brief in this order:
  scene and concept, focal subject and action, composition, lighting and color,
  typography, then exclusions.
- Make every visual choice specific to this video's topic, audience, viewer intent,
  and selected hook. Avoid a reusable generic thumbnail concept.
- Use one dominant focal subject and no more than two supporting visual elements.
- Create depth with a distinct foreground, midground, and background instead of a
  flat collage.
- Choose a deliberate topic-appropriate visual language; do not default every topic
  to neon AI graphics, dashboards, arrows, circles, or exaggerated shocked faces.
- Use photorealistic subjects, a controlled two-to-three-color palette, purposeful
  lighting, and strong subject/background separation.
- Ensure the core idea and text remain understandable at a 320x180 preview size.
- Render the selected thumbnail text exactly as provided.
- Place the selected text in the most readable negative space based on the visual composition.
- Do not force the text to the left, right, top, or bottom.
- The selected text must be large, bold, readable, correctly spelled, and visually balanced.
- The selected text must not cover faces, eyes, hands, the main object, or the core emotion.
- Do not add any other text, captions, labels, letters, watermarks, or logos.
- Use a dark contrast area behind the selected text so it is readable at mobile size.
- Do not mention copyrighted logos unless the user explicitly provided them.
- Create an original design. Do not copy a specific creator, thumbnail, artwork, or
  platform image.

seo rules:
- seo must include title, description, tags, hashtags, keywords.
- title should be clickable but honest.
- description should start with two strong SEO lines.
- tags and keywords must be arrays.

edit_options must be 4 short strings.
""".strip()
    user_payload = {
        "idea": idea,
        "youtube_intent": youtube_intent,
        "selected_hook": selected_hook,
        "subject_plan": subject_plan,
        "creator_image_choice": creator_image_choice,
        "output_requirements": {
            "thumbnail_size": "16:9",
            "thumbnail_text": selected_hook.get("thumbnail_text", ""),
            "seo_language": "English",
        },
    }
    generated = TextGenerationClient().generate_json(
        system_prompt=system_prompt,
        user_payload=user_payload,
        temperature=0.25,
    )
    return normalize_generated_package_plan(
        generated=generated,
        idea=idea,
        youtube_intent=youtube_intent,
        selected_hook=selected_hook,
        subject_plan=subject_plan,
    )


def normalize_generated_package_plan(
    *,
    generated: Any,
    idea: str,
    youtube_intent: dict[str, Any],
    selected_hook: dict[str, Any],
    subject_plan: list[dict[str, Any]],
) -> dict[str, Any]:
    generated = generated if isinstance(generated, dict) else {}
    thumbnail_text = str(selected_hook.get("thumbnail_text", "")).strip()
    fallback_prompt = build_fallback_thumbnail_prompt(
        idea=idea,
        youtube_intent=youtube_intent,
        selected_hook=selected_hook,
        subject_plan=subject_plan,
    )
    thumbnail_prompt = str(generated.get("thumbnail_prompt", "")).strip()
    if not thumbnail_prompt or thumbnail_text not in thumbnail_prompt:
        thumbnail_prompt = fallback_prompt
    thumbnail_prompt = apply_thumbnail_rendering_brief(thumbnail_prompt)

    seo = generated.get("seo", {})
    if not isinstance(seo, dict):
        seo = {}
    seo = normalize_seo_package(
        seo=seo,
        idea=idea,
        youtube_intent=youtube_intent,
    )
    edit_options = normalize_string_list(generated.get("edit_options", []))
    if len(edit_options) < 4:
        edit_options = [
            "Change thumbnail text",
            "Use my face",
            "Regenerate with stronger emotion",
            "Replace background",
        ]

    return {
        "thumbnail_prompt": thumbnail_prompt,
        "seo": seo,
        "edit_options": edit_options[:4],
    }


def generate_script_guide(
    *,
    idea: str,
    youtube_intent: dict[str, Any],
    seo: dict[str, Any] | None = None,
) -> dict[str, Any]:
    system_prompt = """
You are a senior YouTube script strategist. Create a flexible creator talking guide,
not a word-for-word screenplay. Ground it in the exact video idea, viewer intent, and
SEO package supplied by the user. Never invent personal experience, product testing,
statistics, quotes, or factual claims. Put unsupported facts in facts_to_verify.

Return strict JSON using exactly this shape:
{
  "format": "creator_talking_guide",
  "audience_goal": "string",
  "core_message": "string",
  "opening": {
    "viewer_need": "string",
    "hook_guidance": "string",
    "promise": "string"
  },
  "sections": [
    {
      "heading": "string",
      "viewer_question": "string",
      "talking_points": ["string"],
      "proof_or_example": "string",
      "retention_bridge": "string"
    }
  ],
  "closing": {
    "key_takeaway": "string",
    "call_to_action": "string"
  },
  "delivery_notes": ["string"],
  "facts_to_verify": ["string"],
  "estimated_duration_minutes": 8
}

Provide 4 to 7 specific sections. Each section must answer a real viewer question and
move toward the promised outcome. Keep the guide concise and useful while recording.
""".strip()
    generated = TextGenerationClient().generate_json(
        system_prompt=system_prompt,
        user_payload={
            "idea": idea,
            "youtube_intent": youtube_intent,
            "seo": seo or {},
        },
        temperature=0.25,
    )
    return normalize_script_guide(
        script=generated,
        idea=idea,
        youtube_intent=youtube_intent,
    )


def normalize_script_guide(
    *,
    script: Any,
    idea: str,
    youtube_intent: dict[str, Any],
) -> dict[str, Any]:
    fallback = build_fallback_script_guide(
        idea=idea,
        youtube_intent=youtube_intent,
    )
    if not isinstance(script, dict):
        return fallback

    opening = script.get("opening")
    opening = opening if isinstance(opening, dict) else {}
    closing = script.get("closing")
    closing = closing if isinstance(closing, dict) else {}

    sections = []
    raw_sections = script.get("sections")
    if isinstance(raw_sections, list):
        for section in raw_sections[:7]:
            if not isinstance(section, dict):
                continue
            heading = str(section.get("heading", "")).strip()
            talking_points = normalize_string_list(section.get("talking_points", []))
            if not heading or not talking_points:
                continue
            sections.append(
                {
                    "heading": heading,
                    "viewer_question": str(
                        section.get("viewer_question", "")
                    ).strip(),
                    "talking_points": talking_points[:6],
                    "proof_or_example": str(
                        section.get("proof_or_example", "")
                    ).strip(),
                    "retention_bridge": str(
                        section.get("retention_bridge", "")
                    ).strip(),
                }
            )

    if not sections:
        sections = fallback["sections"]

    try:
        estimated_duration = int(script.get("estimated_duration_minutes", 8))
    except (TypeError, ValueError):
        estimated_duration = 8

    return {
        "format": "creator_talking_guide",
        "audience_goal": str(script.get("audience_goal", "")).strip()
        or fallback["audience_goal"],
        "core_message": str(script.get("core_message", "")).strip()
        or fallback["core_message"],
        "opening": {
            "viewer_need": str(opening.get("viewer_need", "")).strip()
            or fallback["opening"]["viewer_need"],
            "hook_guidance": str(opening.get("hook_guidance", "")).strip()
            or fallback["opening"]["hook_guidance"],
            "promise": str(opening.get("promise", "")).strip()
            or fallback["opening"]["promise"],
        },
        "sections": sections,
        "closing": {
            "key_takeaway": str(closing.get("key_takeaway", "")).strip()
            or fallback["closing"]["key_takeaway"],
            "call_to_action": str(closing.get("call_to_action", "")).strip()
            or fallback["closing"]["call_to_action"],
        },
        "delivery_notes": normalize_string_list(script.get("delivery_notes", []))
        or fallback["delivery_notes"],
        "facts_to_verify": normalize_string_list(script.get("facts_to_verify", [])),
        "estimated_duration_minutes": max(1, min(30, estimated_duration)),
    }


def build_fallback_script_guide(
    *,
    idea: str,
    youtube_intent: dict[str, Any],
) -> dict[str, Any]:
    viewer_intent = str(youtube_intent.get("viewer_intent", "")).strip()
    audience_goal = viewer_intent or f"Understand the practical value of {idea}."
    return {
        "format": "creator_talking_guide",
        "audience_goal": audience_goal,
        "core_message": f"Give viewers a clear, useful answer about {idea}.",
        "opening": {
            "viewer_need": audience_goal,
            "hook_guidance": (
                "Open with the viewer's most urgent question, then explain why the "
                "answer matters now."
            ),
            "promise": f"Promise a practical, honest explanation of {idea}.",
        },
        "sections": [
            {
                "heading": "Clarify the viewer's problem",
                "viewer_question": "Why should this topic matter to me?",
                "talking_points": [
                    "Describe the viewer's current situation and desired outcome.",
                    "Explain the gap this video will help them close.",
                ],
                "proof_or_example": (
                    "Use a realistic scenario; verify any factual claim before recording."
                ),
                "retention_bridge": "Preview the practical answer coming next.",
            },
            {
                "heading": "Deliver the practical answer",
                "viewer_question": "What should I understand or do?",
                "talking_points": [
                    f"Break {idea} into clear, useful decisions or steps.",
                    "Explain tradeoffs, limitations, and who each option is for.",
                ],
                "proof_or_example": (
                    "Demonstrate with an example the creator can support honestly."
                ),
                "retention_bridge": "Lead into the most important mistake to avoid.",
            },
            {
                "heading": "Help the viewer apply it",
                "viewer_question": "How do I use this after the video?",
                "talking_points": [
                    "Summarize the decision the viewer can make immediately.",
                    "Give a simple next step and set realistic expectations.",
                ],
                "proof_or_example": "Offer a short checklist or before-and-after scenario.",
                "retention_bridge": "Transition naturally to the final takeaway.",
            },
        ],
        "closing": {
            "key_takeaway": f"Restate the most useful lesson about {idea}.",
            "call_to_action": (
                "Invite viewers to share their situation or try the most relevant next step."
            ),
        },
        "delivery_notes": [
            "Use your own words and natural speaking style.",
            "Prefer concrete examples over broad claims.",
            "Keep the pace focused on the viewer's promised outcome.",
        ],
        "facts_to_verify": [],
        "estimated_duration_minutes": 8,
    }


def build_fallback_thumbnail_prompt(
    *,
    idea: str,
    youtube_intent: dict[str, Any],
    selected_hook: dict[str, Any],
    subject_plan: list[dict[str, Any]],
) -> str:
    subject_descriptions = ", ".join(
        str(subject.get("description", "")).strip()
        for subject in subject_plan
        if subject.get("description")
    )
    thumbnail_text = selected_hook.get("thumbnail_text", "")
    viewer_intent = youtube_intent.get("viewer_intent", "")
    return (
        "Create a photorealistic 16:9 YouTube thumbnail. "
        f"Video idea: {idea}. Viewer intent: {viewer_intent}. "
        f"Main visual subjects: {subject_descriptions}. "
        f"Render this exact thumbnail text inside the image: {thumbnail_text}. "
        "Dramatic high contrast lighting, clear emotional expression, professional "
        "creator thumbnail style, strong focal hierarchy, large bold white/yellow text "
        "placed in the most readable empty space, dark stroke or shadow behind text, "
        "correct spelling, readable at mobile size, do not cover face, eyes, hands, "
        "main object, or core emotion, no extra text, no logos."
    )


def apply_thumbnail_rendering_brief(thumbnail_prompt: str) -> str:
    return (
        f"Scene and concept:\n{thumbnail_prompt.strip()}\n\n"
        f"Production direction:\n{THUMBNAIL_RENDERING_BRIEF}"
    )


def normalize_seo_package(
    *,
    seo: dict[str, Any],
    idea: str,
    youtube_intent: dict[str, Any],
) -> dict[str, Any]:
    keywords = normalize_string_list(
        seo.get("keywords") or youtube_intent.get("seo_keywords", [])
    )
    tags = normalize_string_list(seo.get("tags") or keywords)
    hashtags = normalize_string_list(seo.get("hashtags", []))
    if not hashtags:
        hashtags = [
            f"#{keyword.replace(' ', '')}"
            for keyword in keywords[:3]
            if keyword
        ]

    title = str(seo.get("title", "")).strip() or idea
    description = str(seo.get("description", "")).strip()
    if not description:
        description = (
            f"{idea}\n\n"
            f"{youtube_intent.get('viewer_intent', 'This video explains the topic clearly.')}"
        )

    return {
        "title": title[:100],
        "description": description,
        "tags": tags[:15],
        "hashtags": hashtags[:5],
        "keywords": keywords[:10],
    }


def build_thumbnail_hook_cards(
    *,
    idea: str,
    content_type: str,
    viewer_intent: str,
    emotional_angles: list[str],
    seo_keywords: list[str],
    thumbnail_hooks: list[dict[str, str]],
) -> list[dict[str, str]]:
    topic = seo_keywords[0] if seo_keywords else extract_short_topic(idea)
    hook_text_by_angle = {
        hook["angle"]: hook["text"]
        for hook in thumbnail_hooks
        if hook.get("angle") and hook.get("text")
    }
    angle_order = choose_thumbnail_angle_order(
        content_type=content_type,
        emotional_angles=emotional_angles,
    )
    cards = []

    for angle in angle_order[:3]:
        cards.append(
            {
                "id": angle.replace(" ", "_"),
                "angle": angle,
                "label": angle.title(),
                "thumbnail_text": build_thumbnail_text(
                    angle=angle,
                    topic=topic,
                    content_type=content_type,
                    personalized_text=hook_text_by_angle.get(angle),
                ),
                "reason": build_thumbnail_hook_reason(
                    angle=angle,
                    viewer_intent=viewer_intent,
                ),
            }
        )

    return cards


def choose_thumbnail_angle_order(
    *,
    content_type: str,
    emotional_angles: list[str],
) -> list[str]:
    # Keep the comparison stable in the UI while personalizing the copy inside
    # each strategy. The arguments remain part of the service contract for
    # backward compatibility with existing callers.
    return list(THUMBNAIL_HOOK_ANGLES)


def build_thumbnail_text(
    *,
    angle: str,
    topic: str,
    content_type: str,
    personalized_text: str | None = None,
) -> str:
    if personalized_text:
        return personalized_text

    topic_words = topic.split()[:2]
    short_topic = " ".join(topic_words).title() if topic_words else "This"

    if angle == "fear":
        if "warning" in content_type.lower():
            return f"Avoid This {short_topic} Mistake"
        return f"{short_topic} Mistakes"
    if angle == "shock":
        return f"The {short_topic} Reality"
    if angle == "result":
        return f"{short_topic} Works"
    return f"Inside {short_topic}"


def build_thumbnail_hook_reason(*, angle: str, viewer_intent: str) -> str:
    if angle == "fear":
        return f"Uses risk or mistake tension around the viewer need: {viewer_intent}"
    if angle == "shock":
        return f"Creates a strong surprise promise around the viewer need: {viewer_intent}"
    if angle == "result":
        return f"Focuses on the practical outcome the viewer wants: {viewer_intent}"
    return f"Opens a curiosity gap around the viewer need: {viewer_intent}"


def extract_short_topic(idea: str) -> str:
    words = [
        word
        for word in re.findall(r"[a-zA-Z0-9]+", idea.lower())
        if word not in STOP_WORDS and len(word) > 2
    ]
    return " ".join(words[:2]) or "this topic"


def extract_seo_keywords(
    *,
    idea: str,
    videos: list[dict[str, Any]],
    search_suggestions: list[str] | None = None,
) -> list[str]:
    search_suggestions = normalize_string_list(search_suggestions or [])
    keyword_counter: Counter[str] = Counter()
    phrase_counter: Counter[str] = Counter()

    for source in [idea] + search_suggestions + [video["title"] for video in videos]:
        words = [
            word
            for word in re.findall(r"[a-zA-Z0-9]+", source.lower())
            if word not in STOP_WORDS and (len(word) > 2 or word == "ai")
        ]
        keyword_counter.update(words)
        for index in range(len(words) - 1):
            phrase_counter[" ".join(words[index : index + 2])] += 1
        for index in range(len(words) - 2):
            phrase_counter[" ".join(words[index : index + 3])] += 1

    for video in videos:
        for tag in video.get("tags", [])[:10]:
            normalized_tag = " ".join(
                word
                for word in re.findall(r"[a-zA-Z0-9]+", tag.lower())
                if word not in STOP_WORDS and (len(word) > 2 or word == "ai")
            )
            if normalized_tag:
                phrase_counter[normalized_tag] += 2

    exact_search_keywords = []
    for suggestion in search_suggestions[:3]:
        normalized_suggestion = " ".join(
            word
            for word in re.findall(r"[a-zA-Z0-9]+", suggestion.lower())
            if word not in STOP_WORDS and (len(word) > 2 or word == "ai")
        )
        if normalized_suggestion:
            exact_search_keywords.append(normalized_suggestion)

    keywords = exact_search_keywords + [
        phrase
        for phrase, _count in phrase_counter.most_common(10)
        if len(phrase.split()) > 1
    ]
    keywords.extend(
        word for word, _count in keyword_counter.most_common(10) if word not in keywords
    )

    return list(dict.fromkeys(keywords))[:MAX_INTENT_KEYWORDS]


def get_active_category_by_slug(slug: str) -> Category:
    try:
        return Category.objects.get(slug=slug, is_active=True)
    except Category.DoesNotExist:
        raise NotFound("Category not found.")


def validate_category_region(*, category: Category, region_code: str) -> None:
    if region_code not in category.default_regions:
        raise ValidationError(
            {
                "region_code": (
                    f"{region_code} is not enabled for {category.name}. "
                    f"Allowed regions: {category.default_regions}."
                )
            }
        )


def collect_youtube_videos(
    *,
    youtube_client: YouTubeClient,
    category: Category,
    region_code: str,
) -> list[dict[str, Any]]:
    published_after = (timezone.now() - timedelta(days=14)).isoformat().replace(
        "+00:00",
        "Z",
    )
    source_meta_by_video_id: dict[str, dict[str, set[str]]] = {}

    popular_videos = youtube_client.fetch_most_popular_videos(
        category_ids=category.youtube_category_ids,
        region_code=region_code,
    )
    search_results = youtube_client.search_videos_by_keywords(
        keywords=category.search_keywords,
        category_ids=category.youtube_category_ids,
        region_code=region_code,
        published_after=published_after,
    )

    candidate_ids: list[str] = []
    for video in popular_videos:
        video_id = video.get("id")
        if not video_id:
            continue
        candidate_ids.append(video_id)
        merge_source_meta(
            source_meta_by_video_id,
            video_id=video_id,
            source_type="most_popular",
            keyword="",
        )

    for item in search_results:
        video_id = item.get("video_id")
        if not video_id:
            continue
        candidate_ids.append(video_id)
        merge_source_meta(
            source_meta_by_video_id,
            video_id=video_id,
            source_type="search",
            keyword=item.get("_matched_keyword", ""),
        )

    detailed_videos = youtube_client.fetch_videos_by_ids(candidate_ids)
    normalized_videos = []
    for video in detailed_videos:
        video_id = video.get("id")
        if not video_id:
            continue

        source_meta = source_meta_by_video_id.get(
            video_id,
            {"source_types": set(), "matched_keywords": set()},
        )
        normalized = normalize_youtube_video(
            video=video,
            category=category,
            region_code=region_code,
            source_types=source_meta["source_types"],
            matched_keywords=source_meta["matched_keywords"],
        )
        if normalized:
            normalized_videos.append(normalized)

    return normalized_videos


def merge_source_meta(
    source_meta_by_video_id: dict[str, dict[str, set[str]]],
    *,
    video_id: str,
    source_type: str,
    keyword: str,
) -> None:
    meta = source_meta_by_video_id.setdefault(
        video_id,
        {"source_types": set(), "matched_keywords": set()},
    )
    if source_type:
        meta["source_types"].add(source_type)
    if keyword:
        meta["matched_keywords"].add(keyword)


def normalize_youtube_video(
    *,
    video: dict[str, Any],
    category: Category,
    region_code: str,
    source_types: set[str],
    matched_keywords: set[str],
) -> dict[str, Any] | None:
    snippet = video.get("snippet", {})
    statistics = video.get("statistics", {})
    content_details = video.get("contentDetails", {})
    title = snippet.get("title", "")
    description = snippet.get("description", "")
    if not is_mostly_ascii_text(title):
        return None

    text_for_filtering = f"{title} {description}".lower()

    matched_keyword_list = sorted(matched_keywords)
    if not matched_keyword_list:
        matched_keyword_list = [
            keyword
            for keyword in category.search_keywords
            if keyword.lower() in text_for_filtering
        ]
    if not matched_keyword_list:
        return None

    return {
        "video_id": video.get("id"),
        "title": title,
        "description": description,
        "channel_title": snippet.get("channelTitle", ""),
        "published_at": parse_youtube_datetime(snippet.get("publishedAt")),
        "youtube_category_id": snippet.get("categoryId", ""),
        "view_count": parse_int(statistics.get("viewCount")),
        "like_count": parse_int(statistics.get("likeCount")),
        "comment_count": parse_int(statistics.get("commentCount")),
        "duration_seconds": parse_duration_seconds(content_details.get("duration")),
        "thumbnail_url": get_thumbnail_url(snippet),
        "matched_keywords": matched_keyword_list,
        "negative_keyword_hits": [
            keyword
            for keyword in category.negative_keywords
            if keyword.lower() in text_for_filtering
        ],
        "source_types": sorted(source_types),
        "region_code": region_code,
    }


def score_videos(
    videos: list[dict[str, Any]],
    *,
    category: Category,
) -> list[dict[str, Any]]:
    scored_videos = []

    for video in videos:
        days_since_published = max(
            (timezone.now() - video["published_at"]).total_seconds() / 86400,
            1,
        )
        views_per_day = video["view_count"] / days_since_published
        engagement_rate = (
            (video["like_count"] + video["comment_count"]) / max(video["view_count"], 1)
        )

        views_velocity_score = min(35, int(math.log10(views_per_day + 1) * 7))
        engagement_score = min(20, int(engagement_rate * 1000))
        freshness_score = calculate_freshness_score(days_since_published)
        keyword_match_score = min(15, len(video["matched_keywords"]) * 5)
        source_strength_score = 10 if len(video["source_types"]) > 1 else 5
        negative_keyword_penalty = min(30, len(video["negative_keyword_hits"]) * 10)

        trend_score = max(
            0,
            min(
                100,
                views_velocity_score
                + engagement_score
                + freshness_score
                + keyword_match_score
                + source_strength_score
                - negative_keyword_penalty,
            ),
        )
        video["trend_score"] = trend_score
        video["trend_reasons"] = build_trend_reasons(
            video=video,
            views_per_day=views_per_day,
            engagement_rate=engagement_rate,
        )
        scored_videos.append(video)

    return sorted(scored_videos, key=lambda item: item["trend_score"], reverse=True)


def calculate_freshness_score(days_since_published: float) -> int:
    if days_since_published <= 3:
        return 20
    if days_since_published <= 7:
        return 15
    if days_since_published <= 14:
        return 10
    return 3


def build_trend_reasons(
    *,
    video: dict[str, Any],
    views_per_day: float,
    engagement_rate: float,
) -> list[str]:
    reasons = [
        f"{int(views_per_day):,} views per day",
        f"{engagement_rate:.2%} engagement rate",
    ]
    if video["matched_keywords"]:
        reasons.append(f"Matched keywords: {', '.join(video['matched_keywords'][:3])}")
    if len(video["source_types"]) > 1:
        reasons.append("Found in both popular and niche search signals")
    return reasons


def cluster_videos(
    videos: list[dict[str, Any]],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    clusters_by_key: dict[str, dict[str, Any]] = {}

    for video in videos:
        cluster_key = get_cluster_key(video)
        cluster = clusters_by_key.setdefault(
            cluster_key,
            {
                "cluster_key": cluster_key,
                "cluster_title": cluster_key.replace("-", " ").title(),
                "trend_score": 0,
                "evidence_video_ids": [],
                "evidence_titles": [],
                "trend_reasons": [],
            },
        )
        cluster["trend_score"] = max(cluster["trend_score"], video["trend_score"])
        cluster["evidence_video_ids"].append(video["video_id"])
        cluster["evidence_titles"].append(video["title"])
        cluster["trend_reasons"].extend(video["trend_reasons"])

    clusters = sorted(
        clusters_by_key.values(),
        key=lambda item: item["trend_score"],
        reverse=True,
    )

    for cluster in clusters:
        cluster["evidence_video_ids"] = cluster["evidence_video_ids"][:5]
        cluster["evidence_titles"] = cluster["evidence_titles"][:5]
        cluster["trend_reasons"] = list(dict.fromkeys(cluster["trend_reasons"]))[:5]

    return clusters[:limit]


def get_cluster_key(video: dict[str, Any]) -> str:
    if video["matched_keywords"]:
        return slugify_phrase(video["matched_keywords"][0])

    words = [
        word
        for word in re.findall(r"[a-zA-Z0-9]+", video["title"].lower())
        if word not in STOP_WORDS and len(word) > 2
    ]
    if not words:
        return "general-trend"
    return slugify_phrase(" ".join(words[:3]))


def generate_ideas_with_llm(
    *,
    category: Category,
    region_code: str,
    clusters: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    if not clusters:
        raise ValidationError({"clusters": "No trend clusters were found."})

    system_prompt = """
You generate honest, specific YouTube video idea candidates for small and medium creators.
Return strict JSON with one top-level key: ideas.
ideas must be an array of objects with:
title, why_now, audience_promise, suggested_format, difficulty, freshness, risk_flags, evidence_video_ids.

Title rules:
- Write YouTube-ready video ideas, not essay topics.
- Use concrete formats like "I Tested...", "7 ...", "How I Would...", "X vs Y", "What Happened When...".
- Mention a concrete object, workflow, tool, audience, result, or constraint.
- Do not copy source titles exactly.
- Do not quote source titles inside why_now; summarize aggregate signals instead.
- Do not use vague titles starting with "Exploring", "The Future of", "The Impact of", or "Opportunities and Challenges".
- Do not invent fake guarantees, income promises, medical claims, or manipulative clickbait.

why_now rules:
- Explain the trend using the evidence cluster.
- Do not say only "is gaining popularity" or "is becoming important".
- Do not mention raw evidence titles.
- Mention recent YouTube signals, views, comments, repeated topic patterns, or search interest.

difficulty must be EASY, MEDIUM, or HARD.
freshness must be LOW, MEDIUM, or HIGH.
""".strip()
    user_payload = {
        "niche": category.name,
        "region_code": region_code,
        "max_ideas": limit,
        "clusters": clusters,
        "quality_rules": [
            "Create practical ideas a small or medium creator can make.",
            "Base each idea on the evidence cluster.",
            "Do not promise guaranteed income, health results, or impossible outcomes.",
            "Do not copy any evidence title exactly.",
            "Prefer test, comparison, tutorial, teardown, case study, or checklist formats.",
            "Reject vague essay topics like impact, future, opportunities, challenges, and daily life.",
        ],
        "good_title_examples": [
            "I Tested 5 AI Agents That Can Automate Creator Workflows",
            "7 ChatGPT Workflows That Save Small Creators Time",
            "AI Automation Tools I Would Actually Use This Week",
            "ChatGPT vs AI Agents: Which One Helps Creators More?",
        ],
        "bad_title_examples": [
            "Exploring ChatGPT's Impact on Daily Life",
            "The Future of AI Agents: Opportunities and Challenges",
            "Automating Repetitive Tasks with AI",
        ],
    }

    generated = TextGenerationClient().generate_json(
        system_prompt=system_prompt,
        user_payload=user_payload,
    )
    ideas = generated.get("ideas", []) if isinstance(generated, dict) else []
    validated_ideas = validate_generated_ideas(
        ideas=ideas,
        clusters=clusters,
        region_code=region_code,
        limit=limit,
    )

    if len(validated_ideas) < limit:
        validated_ideas = fill_missing_ideas_from_clusters(
            ideas=validated_ideas,
            clusters=clusters,
            region_code=region_code,
            limit=limit,
        )

    return validated_ideas


def validate_generated_ideas(
    *,
    ideas: list[dict[str, Any]],
    clusters: list[dict[str, Any]],
    region_code: str,
    limit: int,
) -> list[dict[str, Any]]:
    evidence_titles = {
        title.strip().lower()
        for cluster in clusters
        for title in cluster.get("evidence_titles", [])
    }
    evidence_ids = {
        video_id
        for cluster in clusters
        for video_id in cluster.get("evidence_video_ids", [])
    }
    cluster_by_evidence_id = {
        video_id: cluster
        for cluster in clusters
        for video_id in cluster.get("evidence_video_ids", [])
    }
    valid_ideas = []

    for idea in ideas:
        title = str(idea.get("title", "")).strip()
        if (
            not title
            or title.lower() in evidence_titles
            or is_vague_title(title)
            or not looks_like_creator_video_idea(title)
        ):
            continue

        idea_evidence_ids = [
            video_id
            for video_id in idea.get("evidence_video_ids", [])
            if video_id in evidence_ids
        ]
        if not idea_evidence_ids:
            idea_evidence_ids = clusters[len(valid_ideas) % len(clusters)][
                "evidence_video_ids"
            ]

        first_cluster = cluster_by_evidence_id.get(idea_evidence_ids[0], clusters[0])
        idea_evidence_ids = idea_evidence_ids[:5]
        why_now = str(idea.get("why_now", "")).strip()
        if (
            is_weak_why_now(why_now)
            or contains_non_ascii(why_now)
            or mentions_evidence_title(why_now, first_cluster)
        ):
            why_now = build_evidence_why_now(first_cluster)

        audience_promise = str(idea.get("audience_promise", "")).strip()
        if not audience_promise:
            audience_promise = build_default_audience_promise(first_cluster)

        source_signal = build_source_signal(
            evidence_count=len(idea_evidence_ids),
            region_code=region_code,
        )
        valid_ideas.append(
            {
                "title": title[:255],
                "why_now": why_now,
                "audience_promise": audience_promise,
                "suggested_format": str(
                    idea.get("suggested_format", "Explainer")
                ).strip()[:80],
                "difficulty": normalize_choice(
                    idea.get("difficulty"),
                    IdeaCandidate.Difficulty.values,
                    IdeaCandidate.Difficulty.MEDIUM,
                ),
                "freshness": normalize_choice(
                    idea.get("freshness"),
                    IdeaCandidate.Freshness.values,
                    IdeaCandidate.Freshness.MEDIUM,
                ),
                "trend_score": first_cluster["trend_score"],
                "source_signal": source_signal,
                "evidence_video_ids": idea_evidence_ids,
                "risk_flags": normalize_string_list(idea.get("risk_flags", [])),
            }
        )

        if len(valid_ideas) >= limit:
            break

    return valid_ideas


def fill_missing_ideas_from_clusters(
    *,
    ideas: list[dict[str, Any]],
    clusters: list[dict[str, Any]],
    region_code: str,
    limit: int,
) -> list[dict[str, Any]]:
    existing_titles = {idea["title"].lower() for idea in ideas}

    for cluster in clusters:
        if len(ideas) >= limit:
            break

        fallback_idea = build_fallback_idea_from_cluster(
            cluster,
            region_code=region_code,
        )
        if fallback_idea["title"].lower() in existing_titles:
            continue

        ideas.append(fallback_idea)
        existing_titles.add(fallback_idea["title"].lower())

    if not ideas:
        raise ValidationError(
            {"llm_response": "No valid idea candidates were created."}
        )

    return ideas


def build_fallback_idea_from_cluster(
    cluster: dict[str, Any],
    *,
    region_code: str,
) -> dict[str, Any]:
    topic = humanize_cluster_topic(cluster)
    evidence_video_ids = cluster.get("evidence_video_ids", [])[:5]

    if "agent" in topic.lower():
        title = f"I Tested AI Agents That Can Automate Creator Tasks"
        suggested_format = "Test / workflow"
    elif "chatgpt" in topic.lower():
        title = f"7 ChatGPT Workflows Small Creators Can Use This Week"
        suggested_format = "Tutorial / checklist"
    elif "tool" in topic.lower():
        title = f"I Tested {topic} So Creators Know What Actually Works"
        suggested_format = "Test / comparison"
    else:
        title = f"How I Would Use {topic} for a Real Creator Workflow"
        suggested_format = "Tutorial / case study"

    return {
        "title": title[:255],
        "why_now": build_evidence_why_now(cluster),
        "audience_promise": build_default_audience_promise(cluster),
        "suggested_format": suggested_format,
        "difficulty": IdeaCandidate.Difficulty.MEDIUM,
        "freshness": IdeaCandidate.Freshness.HIGH,
        "trend_score": cluster["trend_score"],
        "source_signal": build_source_signal(
            evidence_count=len(evidence_video_ids),
            region_code=region_code,
        ),
        "evidence_video_ids": evidence_video_ids,
        "risk_flags": [],
    }


def humanize_cluster_topic(cluster: dict[str, Any]) -> str:
    cluster_title = str(cluster.get("cluster_title", "")).strip()
    if cluster_title and cluster_title.lower() != "general trend":
        return cluster_title
    cluster_key = str(cluster.get("cluster_key", "")).replace("-", " ").strip()
    return cluster_key.title() if cluster_key else "This Trend"


def build_evidence_why_now(cluster: dict[str, Any]) -> str:
    trend_reasons = cluster.get("trend_reasons", [])
    if trend_reasons:
        return (
            "Recent US YouTube videos in this topic show measurable traction: "
            f"{'; '.join(trend_reasons[:2])}."
        )
    return "Recent US YouTube videos are repeatedly covering this topic with strong trend signals."


def build_default_audience_promise(cluster: dict[str, Any]) -> str:
    topic = humanize_cluster_topic(cluster).lower()
    return f"Help viewers understand which {topic} ideas are practical enough to try now."


def build_source_signal(*, evidence_count: int, region_code: str) -> str:
    if evidence_count == 1:
        return f"Based on 1 recent {region_code} YouTube trend signal"
    return f"Based on {evidence_count} recent {region_code} YouTube trend signals"


def is_vague_title(title: str) -> bool:
    title_lower = title.lower()
    return any(phrase in title_lower for phrase in BANNED_TITLE_PHRASES)


def looks_like_creator_video_idea(title: str) -> bool:
    title_lower = title.lower()
    creator_markers = (
        "i tested",
        "tested",
        "how ",
        "what happened",
        "vs",
        "tools",
        "workflow",
        "workflows",
        "checklist",
        "guide",
        "tutorial",
        "mistakes",
        "for creators",
        "small creators",
    )
    has_number = bool(re.search(r"\d+", title))
    has_marker = any(marker in title_lower for marker in creator_markers)
    return has_number or has_marker


def is_weak_why_now(why_now: str) -> bool:
    if not why_now:
        return True
    why_now_lower = why_now.lower()
    return any(phrase in why_now_lower for phrase in WEAK_WHY_NOW_PHRASES)


def mentions_evidence_title(why_now: str, cluster: dict[str, Any]) -> bool:
    why_now_lower = why_now.lower()
    for title in cluster.get("evidence_titles", []):
        title_lower = str(title).strip().lower()
        if title_lower and title_lower in why_now_lower:
            return True
    return False


def contains_non_ascii(value: str) -> bool:
    return any(ord(character) > 127 for character in value)


def is_mostly_ascii_text(value: str) -> bool:
    if not value:
        return False
    ascii_count = sum(1 for character in value if ord(character) < 128)
    return ascii_count / len(value) >= 0.9


def normalize_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def save_idea_candidates(
    *,
    category: Category,
    region_code: str,
    ideas: list[dict[str, Any]],
    source_video_count: int,
) -> list[IdeaCandidate]:
    batch_id = uuid.uuid4()
    expires_at = timezone.now() + timedelta(hours=settings.IDEA_EXPIRY_HOURS)

    with transaction.atomic():
        IdeaCandidate.objects.filter(
            category=category,
            region_code=region_code,
            is_active=True,
        ).update(is_active=False)

        idea_candidates = [
            IdeaCandidate(
                category=category,
                batch_id=batch_id,
                region_code=region_code,
                title=idea["title"],
                why_now=idea["why_now"],
                audience_promise=idea["audience_promise"],
                suggested_format=idea["suggested_format"],
                difficulty=idea["difficulty"],
                freshness=idea["freshness"],
                trend_score=idea["trend_score"],
                source_signal=idea["source_signal"],
                source_video_count=source_video_count,
                evidence_video_ids=idea["evidence_video_ids"],
                risk_flags=idea["risk_flags"],
                is_active=True,
                expires_at=expires_at,
            )
            for idea in ideas
        ]
        return list(IdeaCandidate.objects.bulk_create(idea_candidates))


def parse_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def parse_youtube_datetime(value: str | None):
    if not value:
        return timezone.now()
    return timezone.datetime.fromisoformat(value.replace("Z", "+00:00"))


def parse_duration_seconds(value: str | None) -> int:
    if not value:
        return 0

    match = re.fullmatch(
        r"P(?:(?P<days>\d+)D)?T?(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?",
        value,
    )
    if not match:
        return 0

    parts = {key: parse_int(val) for key, val in match.groupdict().items()}
    return (
        parts["days"] * 86400
        + parts["hours"] * 3600
        + parts["minutes"] * 60
        + parts["seconds"]
    )


def get_thumbnail_url(snippet: dict[str, Any]) -> str:
    thumbnails = snippet.get("thumbnails", {})
    for key in ("maxres", "standard", "high", "medium", "default"):
        url = thumbnails.get(key, {}).get("url")
        if url:
            return url
    return ""


def slugify_phrase(value: str) -> str:
    words = re.findall(r"[a-zA-Z0-9]+", value.lower())
    return "-".join(words[:5]) or "general-trend"


def normalize_choice(value: Any, allowed_values: list[str], default: str) -> str:
    value = str(value or "").upper()
    return value if value in allowed_values else default
