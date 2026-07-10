import uuid

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
