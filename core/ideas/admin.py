from django.contrib import admin

from .models import IdeaCandidate


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
