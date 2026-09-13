from django.db import models
from django.utils import timezone


class EvidenceMode(models.TextChoices):
    EVIDENCE_BACKED = "EVIDENCE_BACKED", "Evidence-backed opportunity"
    LIMITED_EVIDENCE = "LIMITED_EVIDENCE", "Early opportunity"
    AI_FALLBACK = "AI_FALLBACK", "AI-suggested idea"


class SourcedRecord(models.Model):
    source = models.CharField(max_length=100, default="youtube_data_api")
    fetched_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True


class DerivedRecord(SourcedRecord):
    model_version = models.CharField(max_length=100, default="none")
    calculation_version = models.CharField(max_length=100, default="v1")
    confidence = models.FloatField(default=0)
    evidence_mode = models.CharField(
        max_length=30, choices=EvidenceMode.choices, default=EvidenceMode.AI_FALLBACK,
    )

    class Meta:
        abstract = True


class NichePool(DerivedRecord):
    identity = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=255)
    definition = models.JSONField(default=dict)
    status = models.CharField(max_length=20, default="pending", db_index=True)
    error_message = models.TextField(blank=True)
    last_search_at = models.DateTimeField(null=True, blank=True)
    refresh_requested_at = models.DateTimeField(null=True, blank=True)
    web_context = models.JSONField(default=list, blank=True)


class PublicChannel(SourcedRecord):
    youtube_channel_id = models.CharField(max_length=100, unique=True)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    uploads_playlist_id = models.CharField(max_length=100, blank=True)
    language = models.CharField(max_length=30, blank=True)
    metadata = models.JSONField(default=dict)


class YouTubeVideo(SourcedRecord):
    youtube_video_id = models.CharField(max_length=100, unique=True)
    channel = models.ForeignKey(
        PublicChannel, on_delete=models.CASCADE, related_name="videos",
    )
    title = models.CharField(max_length=500)
    description = models.TextField(blank=True)
    published_at = models.DateTimeField()
    duration_seconds = models.PositiveIntegerField(default=0)
    format = models.CharField(max_length=20, default="unknown")
    view_count = models.PositiveBigIntegerField(default=0)
    like_count = models.PositiveBigIntegerField(default=0)
    comment_count = models.PositiveBigIntegerField(default=0)
    metadata = models.JSONField(default=dict)


class VideoStatSnapshot(SourcedRecord):
    video = models.ForeignKey(
        YouTubeVideo, on_delete=models.CASCADE, related_name="snapshots",
    )
    view_count = models.PositiveBigIntegerField(default=0)
    like_count = models.PositiveBigIntegerField(default=0)
    comment_count = models.PositiveBigIntegerField(default=0)


class ChannelDNA(DerivedRecord):
    connection = models.OneToOneField(
        "youtube_channels.YouTubeChannel", on_delete=models.CASCADE, related_name="dna",
    )
    profile = models.JSONField(default=dict)
    performance_summary = models.JSONField(default=dict)
    confirmed = models.BooleanField(default=False)
    niche_pool = models.ForeignKey(
        NichePool,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="creator_profiles",
    )
    status = models.CharField(max_length=20, default="pending")
    error_message = models.TextField(blank=True)
    refresh_requested_at = models.DateTimeField(null=True, blank=True)


class NichePoolChannel(DerivedRecord):
    pool = models.ForeignKey(
        NichePool, on_delete=models.CASCADE, related_name="memberships",
    )
    channel = models.ForeignKey(
        PublicChannel, on_delete=models.CASCADE, related_name="memberships",
    )
    relevant = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["pool", "channel"], name="unique_niche_channel",
            ),
        ]


class CompetitorBaseline(DerivedRecord):
    channel = models.ForeignKey(
        PublicChannel, on_delete=models.CASCADE, related_name="baselines",
    )
    format = models.CharField(max_length=20)
    age_bucket = models.CharField(max_length=30)
    median_views = models.FloatField(default=0)
    sample_size = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["channel", "format", "age_bucket"],
                name="unique_competitor_baseline",
            ),
        ]


class TrendSignal(DerivedRecord):
    pool = models.ForeignKey(
        NichePool, on_delete=models.CASCADE, related_name="signals",
    )
    video = models.ForeignKey(
        YouTubeVideo, on_delete=models.CASCADE, related_name="signals",
    )
    outlier_multiplier = models.FloatField(default=0)
    details = models.JSONField(default=dict)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["pool", "video"], name="unique_pool_video_signal",
            ),
        ]


class GeneratedIdea(DerivedRecord):
    dna = models.ForeignKey(
        ChannelDNA, on_delete=models.CASCADE, related_name="generated_ideas",
    )
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)


class IdeaEvidence(SourcedRecord):
    idea = models.ForeignKey(
        GeneratedIdea, on_delete=models.CASCADE, related_name="evidence",
    )
    video = models.ForeignKey(
        YouTubeVideo, on_delete=models.SET_NULL, null=True, blank=True,
    )
    channel = models.ForeignKey(
        PublicChannel, on_delete=models.SET_NULL, null=True, blank=True,
    )


class QuotaLedger(models.Model):
    pool = models.ForeignKey(
        NichePool,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="quota_entries",
    )
    operation = models.CharField(max_length=100)
    search_calls = models.PositiveIntegerField(default=0)
    data_units = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
