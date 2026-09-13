import logging

from celery import shared_task

from .workflow_services import (
    finish_creator_analysis,
    queue_creator_analysis,
    queue_pool_refresh,
    refresh_due_pools,
    start_creator_analysis,
)


logger = logging.getLogger(__name__)


@shared_task(name="intelligence.analyze_creator", ignore_result=True)
def analyze_creator_task(user_id, *, dna_id, requested_at):
    from .creator_services import analyze_creator

    lease = {"dna_id": dna_id, "requested_at": requested_at}
    if not start_creator_analysis(user_id, **lease):
        return
    try:
        analyze_creator(user_id=user_id)
    except Exception:
        finish_creator_analysis(user_id, failed=True, **lease)
        logger.exception("intelligence.creator_analysis_failed user_id=%s", user_id)
        raise
    finish_creator_analysis(user_id, **lease)


@shared_task(name="intelligence.refresh_pool", ignore_result=True)
def refresh_pool_task(pool_id, *, rediscover=False, requested_at=None):
    from .services import refresh_niche_pool

    try:
        refresh_niche_pool(
            pool_id, rediscover=rediscover, expected_requested_at=requested_at,
        )
    except Exception:
        logger.exception("intelligence.pool_refresh_failed pool_id=%s", pool_id)
        raise


@shared_task(name="intelligence.refresh_due_pools", ignore_result=True)
def refresh_due_pools_task():
    refresh_due_pools()
