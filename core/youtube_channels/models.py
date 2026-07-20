from django.conf import settings
from django.db import models


class YouTubeChannel(models.Model):
    class Status(models.TextChoices):
        CONNECTED = "CONNECTED", "Connected"
        REAUTH_REQUIRED = "REAUTH_REQUIRED", "Reauthorization required"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="youtube_channel",
    )
    youtube_channel_id = models.CharField(max_length=100, unique=True)
    title = models.CharField(max_length=255)
    thumbnail_url = models.URLField(max_length=1000, blank=True)
    uploads_playlist_id = models.CharField(max_length=100)
    encrypted_refresh_token = models.TextField()
    granted_scopes = models.JSONField(default=list, blank=True)
    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.CONNECTED,
        db_index=True,
    )
    subscriber_count = models.PositiveBigIntegerField(default=0)
    video_count = models.PositiveBigIntegerField(default=0)
    view_count = models.PositiveBigIntegerField(default=0)
    last_analyzed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title


class YouTubeChannelAnalysis(models.Model):
    channel = models.OneToOneField(
        YouTubeChannel,
        on_delete=models.CASCADE,
        related_name="analysis",
    )
    period_start = models.DateField()
    period_end = models.DateField()
    videos_analyzed = models.PositiveSmallIntegerField(default=0)
    summary = models.JSONField(default=dict)
    top_videos = models.JSONField(default=list)
    weak_videos = models.JSONField(default=list)
    content_gaps = models.JSONField(default=list)
    recommendations = models.JSONField(default=list)
    raw_metrics = models.JSONField(default=dict)
    generated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Analysis for {self.channel.title}"
