from django.contrib import admin

from .models import YouTubeChannel, YouTubeChannelAnalysis


@admin.register(YouTubeChannel)
class YouTubeChannelAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "user",
        "status",
        "subscriber_count",
        "last_analyzed_at",
    )
    search_fields = ("title", "youtube_channel_id", "user__email")
    readonly_fields = ("created_at", "updated_at", "last_analyzed_at")
    exclude = ("encrypted_refresh_token",)


@admin.register(YouTubeChannelAnalysis)
class YouTubeChannelAnalysisAdmin(admin.ModelAdmin):
    list_display = ("channel", "period_start", "period_end", "videos_analyzed")
    readonly_fields = ("generated_at",)
