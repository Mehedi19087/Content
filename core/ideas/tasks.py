import logging

from celery import shared_task

from .services import (
    generate_content_package,
    generate_script_guide,
    mark_content_package_job_failed,
    mark_content_package_job_succeeded,
    research_youtube_intent_for_idea,
    start_content_package_job,
)
from .models import ContentPackageJob


logger = logging.getLogger(__name__)


@shared_task(name="ideas.generate_content_package", ignore_result=True)
def generate_content_package_task(job_id: str):
    job = start_content_package_job(
        job_id=job_id,
        expected_job_type=ContentPackageJob.JobType.PACKAGE,
        stage="generating_package",
    )
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


@shared_task(name="ideas.generate_youtube_intent", ignore_result=True)
def generate_youtube_intent_task(job_id: str):
    job = start_content_package_job(
        job_id=job_id,
        expected_job_type=ContentPackageJob.JobType.RESEARCH,
        stage="researching_youtube_intent",
    )
    if job is None:
        return

    try:
        result = research_youtube_intent_for_idea(**job.request_payload)
    except Exception:
        mark_content_package_job_failed(
            job_id=job.id,
            error_code="research_failed",
            error_message="YouTube research failed. Please try again.",
        )
        logger.exception("ideas.research_job.failed job_id=%s", job.id)
        raise

    mark_content_package_job_succeeded(job_id=job.id, result=result)
    logger.info("ideas.research_job.succeeded job_id=%s", job.id)


@shared_task(name="ideas.generate_content_script", ignore_result=True)
def generate_content_script_task(job_id: str):
    job = start_content_package_job(
        job_id=job_id,
        expected_job_type=ContentPackageJob.JobType.SCRIPT,
        stage="generating_script",
    )
    if job is None:
        return

    try:
        result = generate_script_guide(**job.request_payload)
    except Exception:
        mark_content_package_job_failed(
            job_id=job.id,
            error_code="script_failed",
            error_message="Script generation failed. Please try again.",
        )
        logger.exception("ideas.script_job.failed job_id=%s", job.id)
        raise

    mark_content_package_job_succeeded(job_id=job.id, result=result)
    logger.info("ideas.script_job.succeeded job_id=%s", job.id)
