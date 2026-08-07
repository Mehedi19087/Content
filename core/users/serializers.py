from rest_framework import serializers
from django.contrib.auth import get_user_model

User = get_user_model()


class RefreshAccessTokenSerializer(serializers.Serializer):
    refresh = serializers.CharField(trim_whitespace=False)


class VerifyTokenSerializer(serializers.Serializer):
    token = serializers.CharField(trim_whitespace=False)


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'first_name', 'last_name', 'emergency_number', 'date_joined')
        read_only_fields = ('id', 'username', 'email', 'date_joined')
