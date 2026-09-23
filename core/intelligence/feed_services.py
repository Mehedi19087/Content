"""A shared, daily creator feed; page visits cannot force paid regeneration."""
import hashlib
import json
import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import ValidationError

from .generation_services import generate_ideas
from .models import ChannelDNA, CreatorIdeaFeed


def profile_key(dna):
    value = json.dumps([dna.profile, dna.niche_pool_id], sort_keys=True)
    return hashlib.sha256(value.encode()).hexdigest()


def pending_result():
    return {
        "ideas": [], "status": "preparing", "message": "Preparing your daily ideas.",
        "evidence_mode": "INSUFFICIENT_EVIDENCE", "data_timestamp": None,
        "refresh_status": "not_needed", "creator_refresh_status": "not_needed",
    }


def daily_ideas(*, user_id):
    dna = ChannelDNA.objects.filter(connection__user_id=user_id, confirmed=True).first()
    if dna is None:
        raise ValidationError({"channel_dna": "Confirm your Channel DNA first."})
    now = timezone.now()
    key = profile_key(dna)
    with transaction.atomic():
        # Lock an existing parent even when this is the first feed request.
        ChannelDNA.objects.select_for_update().get(pk=dna.pk)
        feed, _ = CreatorIdeaFeed.objects.get_or_create(dna=dna)
        if feed.requested_at and feed.requested_at > now - timedelta(minutes=10):
            return {**pending_result(), "next_refresh_at": None}
        if feed.next_refresh_at and feed.next_refresh_at > now:
            result = feed.result if feed.profile_key == key else {
                **pending_result(), "status": "scheduled",
                "message": "Your updated profile will be used at the next scheduled refresh.",
            }
            # Do not display expired statistics while a failure cooldown is active.
            result = {**result, "ideas": [idea for idea in result.get("ideas", [])
                if parse_datetime(idea.get("evidence_expires_at", ""))
                and parse_datetime(idea["evidence_expires_at"]) > now]}
            if not result["ideas"] and result.get("status") == "ready":
                result = {**pending_result(), "status": "scheduled",
                          "message": "Your next evidence refresh is scheduled."}
            return {**result, "next_refresh_at": feed.next_refresh_at.isoformat()}
        feed.requested_at = now
        feed.save(update_fields=["requested_at"])
    try:
        ideas = []
        seen = set()
        result = pending_result()
        # Up to twelve candidates, at most four model calls. No unbounded retries.
        for _ in range(2):
            result = generate_ideas(user_id=user_id, count=6, provider_timeout=30)
            for idea in result["ideas"]:
                title = " ".join(idea["idea"].casefold().split())
                if title not in seen:
                    seen.add(title)
                    ideas.append(idea)
            if len(ideas) >= 3 or result["status"] in {"collecting_evidence", "insufficient_evidence"}:
                break
        ideas = ideas[:3]
        expires = [parse_datetime(i["evidence_expires_at"]) for i in ideas]
        next_refresh = min([now + timedelta(days=1)] + expires) if ideas else now + timedelta(hours=1)
        if result.get("status") == "collecting_evidence":
            next_refresh = now + timedelta(minutes=1)
        result = {**result, "ideas": ideas, "status": "ready" if len(ideas) >= 3 else ("limited" if ideas else result["status"]),
                  "message": "" if len(ideas) >= 3 else
                  "Fewer than three ideas passed the evidence checks. We will check again automatically."}
        if len(ideas) < 3:
            next_refresh = min(next_refresh, now + timedelta(hours=1))
        result.pop("generation_summary", None)  # A feed may combine two draft batches.
        if ideas:
            result["data_timestamp"] = min(i["data_timestamp"] for i in ideas)
            result["evidence_mode"] = "LIMITED_EVIDENCE" if any(
                i["evidence_mode"] == "LIMITED_EVIDENCE" for i in ideas
            ) else "EVIDENCE_BACKED"
    except Exception:
        logging.getLogger(__name__).exception("intelligence.daily_feed_failed user_id=%s", user_id)
        retry_at = timezone.now() + timedelta(hours=1)
        failure = {**pending_result(), "status": "scheduled",
                   "message": "Idea preparation is temporarily unavailable. We will retry automatically."}
        CreatorIdeaFeed.objects.filter(pk=feed.pk, requested_at=now).update(
            requested_at=None, next_refresh_at=retry_at,
            profile_key=key, result=failure,
        )
        return {**failure, "next_refresh_at": retry_at.isoformat()}
    # A late request must not overwrite a newer lease or changed profile.
    with transaction.atomic():
        current_dna = ChannelDNA.objects.select_for_update().get(pk=dna.pk)
        if profile_key(current_dna) != key:
            result = {**pending_result(), "status": "scheduled",
                      "message": "Your updated profile will be used at the next scheduled refresh."}
        updated = CreatorIdeaFeed.objects.filter(pk=feed.pk, requested_at=now).update(
            result=result, profile_key=key, requested_at=None, next_refresh_at=next_refresh,
        )
    if not updated:
        return {**pending_result(), "next_refresh_at": None}
    return {**result, "next_refresh_at": next_refresh.isoformat()}
