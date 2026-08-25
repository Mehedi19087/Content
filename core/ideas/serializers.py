from rest_framework import serializers


class TrendingIdeaQuerySerializer(serializers.Serializer):
    category_slug = serializers.SlugField(max_length=120, required=False)
    region_code = serializers.CharField(max_length=20, required=False)
    region = serializers.CharField(max_length=20, required=False, write_only=True)
    limit = serializers.IntegerField(default=10, min_value=1, max_value=20, required=False)

    def validate(self, attrs):
        region_code = attrs.pop("region_code", None)
        region_alias = attrs.pop("region", None)

        if (
            region_code
            and region_alias
            and region_code.upper() != region_alias.upper()
        ):
            raise serializers.ValidationError(
                {"region": "Use either region or region_code, not conflicting values."}
            )

        attrs["region_code"] = (region_code or region_alias or "US").upper()
        return attrs


class CronRefreshIdeasSerializer(serializers.Serializer):
    region_code = serializers.CharField(max_length=20, default="US", required=False)
    limit = serializers.IntegerField(default=10, min_value=1, max_value=10, required=False)

    def validate_region_code(self, value):
        return value.strip().upper()


class CronCategoryResultSerializer(serializers.Serializer):
    category_slug = serializers.CharField(read_only=True)
    status = serializers.ChoiceField(
        choices=("succeeded", "failed"),
        read_only=True,
    )
    attempts = serializers.IntegerField(read_only=True)
    ideas_created = serializers.IntegerField(read_only=True)
    error = serializers.CharField(read_only=True, allow_blank=True)


class CronRefreshSummarySerializer(serializers.Serializer):
    region_code = serializers.CharField(read_only=True)
    total_categories = serializers.IntegerField(read_only=True)
    succeeded = serializers.IntegerField(read_only=True)
    failed = serializers.IntegerField(read_only=True)
    results = CronCategoryResultSerializer(many=True, read_only=True)


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
    search_suggestions = serializers.ListField(
        child=serializers.CharField(),
        read_only=True,
    )
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
    script = serializers.DictField(read_only=True)
    edit_options = serializers.ListField(
        child=serializers.CharField(),
        read_only=True,
    )


class ResponseContentPackageJobSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    status = serializers.CharField(read_only=True)
    stage = serializers.CharField(read_only=True)
    result = ResponseGeneratePackageSerializer(read_only=True, allow_null=True)
    error_code = serializers.CharField(read_only=True, allow_blank=True)
    error_message = serializers.CharField(read_only=True, allow_blank=True)
    created_at = serializers.DateTimeField(read_only=True)
    started_at = serializers.DateTimeField(read_only=True, allow_null=True)
    finished_at = serializers.DateTimeField(read_only=True, allow_null=True)
