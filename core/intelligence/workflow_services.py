"""Short database reservations keep duplicate HTTP requests off the worker queue."""
from datetime import timedelta
import logging

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException, NotFound

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


def get_niche_pool(user_id):
    from .creator_services import get_dna
    from .services import discovery_due

    dna = get_dna(user_id=user_id)
    if not dna.niche_pool_id:
        raise NotFound("Confirm Channel DNA to select a niche pool.")
    pool = dna.niche_pool
    if pool.status in {"pending", "running"} and not has_active_job(pool, timezone.now()):
        NichePool.objects.filter(
            pk=pool.pk, status=pool.status, refresh_requested_at=pool.refresh_requested_at,
        ).update(
            status="failed", refresh_requested_at=None,
            error_message="YouTube evidence collection timed out. Try again.",
        )
        pool.refresh_from_db()
    pool.next_discovery_at = None
    if not discovery_due(pool, timezone.now()):
        days = 30 if pool.memberships.filter(relevant=True).exists() else 1
        pool.next_discovery_at = pool.last_search_at + timedelta(days=days)
    return pool


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
    from .services import discovery_due

    now = timezone.now()
    with transaction.atomic():
        pool = NichePool.objects.select_for_update().get(pk=pool_id)
        if has_active_job(pool, now):
            return "already_queued"
        should_discover = discovery_due(pool, now) and (
            rediscover or not pool.memberships.filter(relevant=True).exists()
        )
        if not should_discover and not pool.memberships.filter(relevant=True).exists():
            return "discovery_cooldown"
        fresh = (
            pool.expires_at and pool.expires_at > now
            and pool.fetched_at > now - timedelta(hours=24)
        )
        if not should_discover and fresh:
            return "fresh"
        pool.refresh_requested_at = now
        pool.status = "pending"
        pool.error_message = ""
        pool.save(update_fields=["refresh_requested_at", "status", "error_message"])
    try:
        refresh_pool_task.apply_async(
            args=[pool_id],
            kwargs={"rediscover": bool(should_discover), "requested_at": now.isoformat()},
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
    from .services import discovery_due

    now = timezone.now()
    results = {}
    pools = NichePool.objects.filter(creator_profiles__confirmed=True).distinct()
    for pool in pools.iterator():
        should_discover = discovery_due(pool, now)
        if should_discover or pool.expires_at is None or pool.expires_at <= now:
            results[pool.pk] = queue_pool_refresh(pool.pk, rediscover=should_discover)
    return results
