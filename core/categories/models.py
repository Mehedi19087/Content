from django.db import models


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.CharField(max_length=120, unique=True)
    description = models.TextField(blank=True)
    youtube_category_ids = models.JSONField(default=list, blank=True)
    youtube_category_titles = models.JSONField(default=list, blank=True)
    search_keywords = models.JSONField(default=list, blank=True)
    negative_keywords = models.JSONField(default=list, blank=True)
    default_regions = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name 
