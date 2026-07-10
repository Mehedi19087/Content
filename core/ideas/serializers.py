from rest_framework import serializers


class TrendingIdeaQuerySerializer(serializers.Serializer):
    category_slug = serializers.SlugField(max_length=120)
    region_code = serializers.CharField(max_length=20, default="US", required=False)
    limit = serializers.IntegerField(default=10, min_value=1, max_value=20, required=False)


class RefreshIdeasSerializer(serializers.Serializer):
    category_slug = serializers.SlugField(max_length=120)
    region_code = serializers.CharField(max_length=20, default="US", required=False)
    limit = serializers.IntegerField(default=10, min_value=1, max_value=10, required=False)


class YouTubeIntentResearchSerializer(serializers.Serializer):
    idea = serializers.CharField(max_length=255)
    region_code = serializers.CharField(max_length=20, default="US", required=False)
    language_code = serializers.CharField(max_length=20, default="en", required=False)
    max_results = serializers.IntegerField(
        default=10,
        min_value=5,
        max_value=20,
        required=False,
    )

    def validate_idea(self, value):
        value = value.strip()
        if len(value) < 5:
            raise serializers.ValidationError("Idea must be at least 5 characters.")
        return value


class ThumbnailPreparationSerializer(serializers.Serializer):
    idea = serializers.CharField(max_length=255)
    youtube_intent = serializers.DictField()

    def validate_idea(self, value):
        value = value.strip()
        if len(value) < 5:
            raise serializers.ValidationError("Idea must be at least 5 characters.")
        return value

    def validate_youtube_intent(self, value):
        required_fields = (
            "viewer_intent",
            "content_type",
            "title_patterns",
            "emotional_angles",
            "thumbnail_subjects",
            "seo_keywords",
        )
        missing_fields = [field for field in required_fields if field not in value]
        if missing_fields:
            raise serializers.ValidationError(
                f"Missing fields: {', '.join(missing_fields)}."
            )
        return value


class GeneratePackageSerializer(serializers.Serializer):
    idea = serializers.CharField(max_length=255)
    youtube_intent = serializers.DictField()
    selected_hook = serializers.DictField()
    subject_plan = serializers.ListField(
        child=serializers.DictField(),
        allow_empty=False,
    )
    creator_image_choice = serializers.DictField(required=False, default=dict)

    def validate_idea(self, value):
        value = value.strip()
        if len(value) < 5:
            raise serializers.ValidationError("Idea must be at least 5 characters.")
        return value

    def validate_youtube_intent(self, value):
        required_fields = (
            "viewer_intent",
            "content_type",
            "title_patterns",
            "emotional_angles",
            "thumbnail_subjects",
            "seo_keywords",
        )
        missing_fields = [field for field in required_fields if field not in value]
        if missing_fields:
            raise serializers.ValidationError(
                f"Missing fields: {', '.join(missing_fields)}."
            )
        return value

    def validate_selected_hook(self, value):
        required_fields = ("id", "angle", "thumbnail_text")
        missing_fields = [field for field in required_fields if field not in value]
        if missing_fields:
            raise serializers.ValidationError(
                f"Missing fields: {', '.join(missing_fields)}."
            )
        return value


class ResponseIdeaCandidateSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    category_id = serializers.IntegerField(read_only=True)
    batch_id = serializers.UUIDField(read_only=True)
    region_code = serializers.CharField(read_only=True)
    title = serializers.CharField(read_only=True)
    why_now = serializers.CharField(read_only=True)
    audience_promise = serializers.CharField(read_only=True)
    suggested_format = serializers.CharField(read_only=True)
    difficulty = serializers.CharField(read_only=True)
    freshness = serializers.CharField(read_only=True)
    trend_score = serializers.IntegerField(read_only=True)
    source_signal = serializers.CharField(read_only=True)
    source_video_count = serializers.IntegerField(read_only=True)
    evidence_video_ids = serializers.ListField(
        child=serializers.CharField(),
        read_only=True,
    )
    risk_flags = serializers.ListField(
        child=serializers.CharField(),
        read_only=True,
    )
    generated_at = serializers.DateTimeField(read_only=True)
    expires_at = serializers.DateTimeField(read_only=True)


class ResponseYouTubeIntentResearchSerializer(serializers.Serializer):
    viewer_intent = serializers.CharField(read_only=True)
    content_type = serializers.CharField(read_only=True)
    title_patterns = serializers.ListField(
        child=serializers.CharField(),
        read_only=True,
    )
    emotional_angles = serializers.ListField(
        child=serializers.CharField(),
        read_only=True,
    )
    thumbnail_subjects = serializers.ListField(
        child=serializers.CharField(),
        read_only=True,
    )
    seo_keywords = serializers.ListField(
        child=serializers.CharField(),
        read_only=True,
    )


class ResponseThumbnailPreparationSerializer(serializers.Serializer):
    hook_cards = serializers.ListField(
        child=serializers.DictField(),
        read_only=True,
    )
    subject_plan = serializers.ListField(
        child=serializers.DictField(),
        read_only=True,
    )
    image_preparation = serializers.DictField(read_only=True)
    creator_image = serializers.DictField(read_only=True)


class ResponseGeneratePackageSerializer(serializers.Serializer):
    thumbnail = serializers.DictField(read_only=True)
    seo = serializers.DictField(read_only=True)
    edit_options = serializers.ListField(
        child=serializers.CharField(),
        read_only=True,
    )
