"""Short database reservations keep duplicate HTTP requests off the worker queue."""
from datetime import timedelta
import logging

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException

from youtube_channels.services import get_youtube_channel

from .models import ChannelDNA, NichePool


logger = logging.getLogger(__name__)
LEASE_SECONDS = 600


class QueueUnavailable(APIException):
    status_code = 503
    default_detail = "Background processing is unavailable. Please try again."
    default_code = "queue_unavailable"


def has_active_job(record, now):
    return (
        record.status in ("pending", "running")
        and record.refresh_requested_at
        and record.refresh_requested_at > now - timedelta(seconds=LEASE_SECONDS)
    )


def queue_creator_analysis(*, user_id):
    from .tasks import analyze_creator_task

    connection = get_youtube_channel(user_id=user_id)
    now = timezone.now()
    with transaction.atomic():
        # Lock the existing connection even on the first DNA creation.
        type(connection).objects.select_for_update().get(pk=connection.pk)
        dna, _ = ChannelDNA.objects.get_or_create(connection=connection)
        if has_active_job(dna, now):
            return dna
        dna.status = "pending"
        dna.error_message = ""
        dna.refresh_requested_at = now
        dna.save(update_fields=["status", "error_message", "refresh_requested_at"])
    try:
        analyze_creator_task.apply_async(
            args=[user_id],
            kwargs={"dna_id": dna.pk, "requested_at": now.isoformat()},
            retry=False,
        )
    except Exception as exc:
        ChannelDNA.objects.filter(pk=dna.pk, refresh_requested_at=now).update(
            status="failed", error_message="Background processing is unavailable.",
            refresh_requested_at=None,
        )
        logger.warning("intelligence.creator_queue_failed user_id=%s", user_id)
        raise QueueUnavailable() from exc
    return dna


def queue_pool_refresh(pool_id, *, rediscover=False):
    from .tasks import refresh_pool_task

    now = timezone.now()
    with transaction.atomic():
        pool = NichePool.objects.select_for_update().get(pk=pool_id)
        if has_active_job(pool, now):
            return "already_queued"
        discovery_due = rediscover and (
            pool.last_search_at is None
            or pool.last_search_at <= now - timedelta(days=30)
        )
        if not discovery_due and pool.expires_at and pool.expires_at > now:
            return "fresh"
        pool.refresh_requested_at = now
        pool.status = "pending"
        pool.error_message = ""
        pool.save(update_fields=["refresh_requested_at", "status", "error_message"])
    try:
        refresh_pool_task.apply_async(
            args=[pool_id],
            kwargs={"rediscover": bool(discovery_due), "requested_at": now.isoformat()},
            retry=False,
        )
    except Exception:
        NichePool.objects.filter(pk=pool_id, refresh_requested_at=now).update(
            status="failed", error_message="Background processing is unavailable.",
            refresh_requested_at=None,
        )
        logger.warning("intelligence.pool_queue_failed pool_id=%s", pool_id)
        return "queue_unavailable"
    return "queued"


def start_creator_analysis(user_id, *, dna_id, requested_at):
    return ChannelDNA.objects.filter(
        pk=dna_id, connection__user_id=user_id, status="pending",
        refresh_requested_at=requested_at,
    ).update(status="running") == 1


def finish_creator_analysis(user_id, *, dna_id, requested_at, failed=False):
    ChannelDNA.objects.filter(
        pk=dna_id, connection__user_id=user_id, refresh_requested_at=requested_at,
    ).update(
        status="failed" if failed else "succeeded",
        error_message="Channel analysis failed. Please try again." if failed else "",
        refresh_requested_at=None,
    )


def refresh_due_pools():
    now = timezone.now()
    results = {}
    pools = NichePool.objects.filter(creator_profiles__confirmed=True).distinct()
    for pool in pools.iterator():
        discovery_due = (
            pool.last_search_at is None
            or pool.last_search_at <= now - timedelta(days=30)
        )
        if discovery_due or pool.expires_at is None or pool.expires_at <= now:
            results[pool.pk] = queue_pool_refresh(pool.pk, rediscover=discovery_due)
    return results
