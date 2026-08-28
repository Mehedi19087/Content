from rest_framework import serializers


MAX_CREATOR_IMAGE_BYTES = 5 * 1024 * 1024
CREATOR_IMAGE_SIGNATURES = {
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/webp": (b"RIFF",),
}


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


class YouTubeIntentResearchSerializer(serializers.Serializer):
    idea = serializers.CharField(max_length=255)
    region_code = serializers.CharField(max_length=20, default="US", required=False)
    language_code = serializers.CharField(max_length=20, default="en", required=False)
    max_results = serializers.IntegerField(
        default=5,
        min_value=5,
        max_value=10,
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


class CreatorImageUploadSerializer(serializers.Serializer):
    image = serializers.FileField(allow_empty_file=False)

    def validate_image(self, value):
        if value.size > MAX_CREATOR_IMAGE_BYTES:
            raise serializers.ValidationError("Image must be 5 MB or smaller.")

        content_type = str(getattr(value, "content_type", "")).lower()
        signatures = CREATOR_IMAGE_SIGNATURES.get(content_type)
        if not signatures:
            raise serializers.ValidationError("Use a JPG, PNG, or WebP image.")

        header = value.read(12)
        value.seek(0)
        valid_signature = any(header.startswith(signature) for signature in signatures)
        if content_type == "image/webp":
            valid_signature = valid_signature and header[8:12] == b"WEBP"
        if not valid_signature:
            raise serializers.ValidationError("The uploaded file is not a valid image.")
        return value


class ChannelLogoUploadSerializer(CreatorImageUploadSerializer):
    pass


class GeneratePackageSerializer(serializers.Serializer):
    idea = serializers.CharField(max_length=255)
    youtube_intent = serializers.DictField()
    selected_hook = serializers.DictField()
    subject_plan = serializers.ListField(
        child=serializers.DictField(),
        allow_empty=False,
    )
    creator_image_choice = serializers.DictField(required=False, default=dict)
    channel_logo_choice = serializers.DictField(required=False, default=dict)

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


class GenerateScriptSerializer(serializers.Serializer):
    idea = serializers.CharField(max_length=255)
    youtube_intent = serializers.DictField()
    seo = serializers.DictField(required=False, default=dict)

    def validate_idea(self, value):
        value = value.strip()
        if len(value) < 5:
            raise serializers.ValidationError("Idea must be at least 5 characters.")
        return value

    def validate_youtube_intent(self, value):
        required_fields = ("viewer_intent", "content_type")
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
    thumbnail_hooks = serializers.ListField(
        child=serializers.DictField(),
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


class ResponseCreatorImageUploadSerializer(serializers.Serializer):
    url = serializers.URLField(read_only=True)
    asset_token = serializers.CharField(read_only=True)


class ResponseChannelLogoUploadSerializer(serializers.Serializer):
    url = serializers.URLField(read_only=True)
    asset_token = serializers.CharField(read_only=True)


class ResponseGeneratePackageSerializer(serializers.Serializer):
    thumbnail = serializers.DictField(read_only=True)
    seo = serializers.DictField(read_only=True)
    edit_options = serializers.ListField(
        child=serializers.CharField(),
        read_only=True,
    )


class ResponseContentPackageJobSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    job_type = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    stage = serializers.CharField(read_only=True)
    result = serializers.JSONField(read_only=True, allow_null=True)
    error_code = serializers.CharField(read_only=True, allow_blank=True)
    error_message = serializers.CharField(read_only=True, allow_blank=True)
    created_at = serializers.DateTimeField(read_only=True)
    started_at = serializers.DateTimeField(read_only=True, allow_null=True)
    finished_at = serializers.DateTimeField(read_only=True, allow_null=True)


class ResponseSavedPackageSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    idea_title = serializers.CharField(source="request_payload.idea", read_only=True)
    saved_at = serializers.SerializerMethodField()
    package = serializers.JSONField(source="result", read_only=True)

    def get_saved_at(self, obj):
        return obj.finished_at or obj.created_at
