from django.contrib import admin

from .models import ContentPackageJob, IdeaCandidate


@admin.register(IdeaCandidate)
class IdeaCandidateAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "category",
        "region_code",
        "trend_score",
        "difficulty",
        "freshness",
        "is_active",
        "generated_at",
    )
    list_filter = ("category", "region_code", "difficulty", "freshness", "is_active")
    search_fields = ("title", "why_now", "audience_promise")
    readonly_fields = ("batch_id", "generated_at", "created_at", "updated_at")


@admin.register(ContentPackageJob)
class ContentPackageJobAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "status", "stage", "created_at", "finished_at")
    list_filter = ("status", "stage")
    search_fields = ("id", "user__username", "user__email", "celery_task_id")
    readonly_fields = (
        "id",
        "request_payload",
        "result",
        "celery_task_id",
        "started_at",
        "finished_at",
        "created_at",
        "updated_at",
    )
