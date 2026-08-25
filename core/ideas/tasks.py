import logging

from celery import shared_task

from .services import (
    generate_content_package,
    mark_content_package_job_failed,
    mark_content_package_job_succeeded,
    start_content_package_job,
)


logger = logging.getLogger(__name__)


@shared_task(name="ideas.generate_content_package", ignore_result=True)
def generate_content_package_task(job_id: str):
    job = start_content_package_job(job_id=job_id)
    if job is None:
        return

    try:
        result = generate_content_package(**job.request_payload)
    except Exception:
        mark_content_package_job_failed(job_id=job.id)
        logger.exception("ideas.package_job.failed job_id=%s", job.id)
        raise

    mark_content_package_job_succeeded(job_id=job.id, result=result)
    logger.info("ideas.package_job.succeeded job_id=%s", job.id)
