from rest_framework import serializers


class AnalyzeCreatorSerializer(serializers.Serializer):
    channel_confirmed = serializers.BooleanField()

    def validate_channel_confirmed(self, value):
        if not value:
            raise serializers.ValidationError("Confirm the connected channel first.")
        return value


class UpdateDNASerializer(serializers.Serializer):
    profile = serializers.DictField()
    confirmed = serializers.BooleanField(default=True)


class GenerateIdeasSerializer(serializers.Serializer):
    count = serializers.IntegerField(min_value=1, max_value=10, default=5)


class DNAResponseSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    profile = serializers.JSONField(read_only=True)
    performance_summary = serializers.JSONField(read_only=True)
    confirmed = serializers.BooleanField(read_only=True)
    niche_pool_id = serializers.IntegerField(read_only=True, allow_null=True)
    status = serializers.CharField(read_only=True)
    error_message = serializers.CharField(read_only=True)
    source = serializers.CharField(read_only=True)
    fetched_at = serializers.DateTimeField(read_only=True, allow_null=True)
    expires_at = serializers.DateTimeField(read_only=True, allow_null=True)


class PoolResponseSerializer(serializers.Serializer):
    collection_summary = serializers.JSONField(read_only=True)
    next_discovery_at = serializers.DateTimeField(read_only=True, allow_null=True)
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    error_message = serializers.CharField(read_only=True)
    evidence_mode = serializers.CharField(read_only=True)
    confidence = serializers.FloatField(read_only=True)
    fetched_at = serializers.DateTimeField(read_only=True, allow_null=True)
    expires_at = serializers.DateTimeField(read_only=True, allow_null=True)


class IdeasResponseSerializer(serializers.Serializer):
    next_refresh_at = serializers.CharField(read_only=True, allow_null=True)
    generation_summary = serializers.JSONField(read_only=True)
    status = serializers.CharField(read_only=True)
    message = serializers.CharField(read_only=True)
    ideas = serializers.ListField(child=serializers.DictField(), read_only=True)
    evidence_mode = serializers.CharField(read_only=True)
    data_timestamp = serializers.CharField(read_only=True, allow_null=True)
    refresh_status = serializers.CharField(read_only=True)
    creator_refresh_status = serializers.CharField(read_only=True)
