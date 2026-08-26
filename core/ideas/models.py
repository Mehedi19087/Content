import uuid

from django.conf import settings
from django.db import models


class IdeaCandidate(models.Model):
    class Difficulty(models.TextChoices):
        EASY = "EASY", "Easy"
        MEDIUM = "MEDIUM", "Medium"
        HARD = "HARD", "Hard"

    class Freshness(models.TextChoices):
        LOW = "LOW", "Low"
        MEDIUM = "MEDIUM", "Medium"
        HIGH = "HIGH", "High"

    category = models.ForeignKey(
        "categories.Category",
        on_delete=models.CASCADE,
        related_name="idea_candidates",
    )
    batch_id = models.UUIDField(default=uuid.uuid4, db_index=True)
    region_code = models.CharField(max_length=20, default="US", db_index=True)
    title = models.CharField(max_length=255)
    why_now = models.TextField()
    audience_promise = models.TextField()
    suggested_format = models.CharField(max_length=80)
    difficulty = models.CharField(
        max_length=20,
        choices=Difficulty.choices,
        default=Difficulty.MEDIUM,
    )
    freshness = models.CharField(
        max_length=20,
        choices=Freshness.choices,
        default=Freshness.MEDIUM,
    )
    trend_score = models.PositiveSmallIntegerField(default=0)
    source_signal = models.CharField(max_length=255, blank=True)
    source_video_count = models.PositiveIntegerField(default=0)
    evidence_video_ids = models.JSONField(default=list, blank=True)
    risk_flags = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)
    generated_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["category", "region_code", "is_active"]),
            models.Index(fields=["category", "region_code", "-trend_score"]),
            models.Index(fields=["batch_id"]),
        ]
        ordering = ["-trend_score", "-generated_at"]

    def __str__(self):
        return self.title


class ContentPackageJob(models.Model):
    class JobType(models.TextChoices):
        RESEARCH = "research", "Research"
        PACKAGE = "package", "Thumbnail and SEO package"
        SCRIPT = "script", "Script"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job_type = models.CharField(
        max_length=20,
        choices=JobType.choices,
        default=JobType.PACKAGE,
        db_index=True,
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="content_package_jobs",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    stage = models.CharField(max_length=40, default="queued")
    request_payload = models.JSONField()
    result = models.JSONField(null=True, blank=True)
    error_code = models.CharField(max_length=80, blank=True)
    error_message = models.TextField(blank=True)
    celery_task_id = models.CharField(max_length=255, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Studio {self.job_type} job {self.id} ({self.status})"
