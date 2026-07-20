from rest_framework import serializers


class YouTubeCallbackSerializer(serializers.Serializer):
    code = serializers.CharField()
    state = serializers.CharField()


class AnalyzeYouTubeChannelSerializer(serializers.Serializer):
    pass


class ResponseYouTubeChannelSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    youtube_channel_id = serializers.CharField(read_only=True)
    title = serializers.CharField(read_only=True)
    thumbnail_url = serializers.URLField(read_only=True, allow_blank=True)
    status = serializers.CharField(read_only=True)
    subscriber_count = serializers.IntegerField(read_only=True)
    video_count = serializers.IntegerField(read_only=True)
    view_count = serializers.IntegerField(read_only=True)
    last_analyzed_at = serializers.DateTimeField(read_only=True, allow_null=True)
    created_at = serializers.DateTimeField(read_only=True)


class ResponseYouTubeAnalysisSerializer(serializers.Serializer):
    period_start = serializers.DateField(read_only=True)
    period_end = serializers.DateField(read_only=True)
    videos_analyzed = serializers.IntegerField(read_only=True)
    summary = serializers.DictField(read_only=True)
    top_videos = serializers.ListField(
        child=serializers.DictField(),
        read_only=True,
    )
    weak_videos = serializers.ListField(
        child=serializers.DictField(),
        read_only=True,
    )
    content_gaps = serializers.ListField(
        child=serializers.DictField(),
        read_only=True,
    )
    recommendations = serializers.ListField(
        child=serializers.CharField(),
        read_only=True,
    )
    generated_at = serializers.DateTimeField(read_only=True)
