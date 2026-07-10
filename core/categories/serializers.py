from rest_framework import serializers
from rest_framework.validators import UniqueValidator

from .models import Category


class CreateCategorySerializer(serializers.Serializer):
    name = serializers.CharField(
        max_length=100,
        validators=[UniqueValidator(queryset=Category.objects.all())],
    )
    slug = serializers.CharField(
        max_length=120,
        validators=[UniqueValidator(queryset=Category.objects.all())],
    )
    description = serializers.CharField(required=False, allow_blank=True)
    youtube_category_ids = serializers.ListField(
        child=serializers.CharField(max_length=20),
        required=False,
    )
    youtube_category_titles = serializers.ListField(
        child=serializers.CharField(max_length=100),
        required=False,
    )
    search_keywords = serializers.ListField(
        child=serializers.CharField(max_length=100),
        required=False,
    )
    negative_keywords = serializers.ListField(
        child=serializers.CharField(max_length=100),
        required=False,
    )
    default_regions = serializers.ListField(
        child=serializers.CharField(max_length=20),
        required=False,
    )
    is_active = serializers.BooleanField(required=False)


class ResponseCategorySerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(read_only=True)
    slug = serializers.CharField(read_only=True)
    description = serializers.CharField(read_only=True)
    youtube_category_ids = serializers.ListField(
        child=serializers.CharField(),
        read_only=True,
    )
    youtube_category_titles = serializers.ListField(
        child=serializers.CharField(),
        read_only=True,
    )
    search_keywords = serializers.ListField(
        child=serializers.CharField(),
        read_only=True,
    )
    negative_keywords = serializers.ListField(
        child=serializers.CharField(),
        read_only=True,
    )
    default_regions = serializers.ListField(
        child=serializers.CharField(),
        read_only=True,
    )
    is_active = serializers.BooleanField(read_only=True)
