from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from rest_framework import serializers

from apps.accounts.managers import normalize_email_address
from apps.accounts.models import User

DUPLICATE_EMAIL_MESSAGE = "A user with this email already exists."


class UserSerializer(serializers.ModelSerializer):
    """Read-only public representation of a user. Never includes the password hash."""

    class Meta:
        model = User
        fields = ["id", "email", "first_name", "last_name", "role", "date_joined"]
        read_only_fields = fields


class RegisterSerializer(serializers.ModelSerializer):
    # Declared explicitly so ModelSerializer does not attach its own UniqueValidator,
    # which would compare the *un-normalized* email and miss "AVI@x.com" vs "avi@x.com".
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, style={"input_type": "password"})

    class Meta:
        model = User
        # `role` is deliberately absent: self-registration always creates a plain user.
        fields = ["email", "password", "first_name", "last_name"]

    def validate_email(self, value):
        email = normalize_email_address(value)
        if User.objects.filter(email=email).exists():
            raise serializers.ValidationError(DUPLICATE_EMAIL_MESSAGE)
        return email

    def validate(self, attrs):
        # Runs Django's AUTH_PASSWORD_VALIDATORS (length, common passwords, similarity to
        # email/name). The unsaved user is passed so the similarity check can see those fields.
        candidate = User(**{k: v for k, v in attrs.items() if k != "password"})
        try:
            validate_password(attrs["password"], user=candidate)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": list(exc.messages)}) from exc
        return attrs

    def create(self, validated_data):
        # validate_email's exists() check has a race: two signups with the same email can
        # both pass it before either inserts. The DB unique index is the real guarantee;
        # we turn its IntegrityError into a normal 400 instead of a 500.
        # atomic() creates a savepoint so the failed INSERT doesn't poison an outer transaction.
        try:
            with transaction.atomic():
                return User.objects.create_user(**validated_data)
        except IntegrityError as exc:
            raise serializers.ValidationError({"email": [DUPLICATE_EMAIL_MESSAGE]}) from exc

    def to_representation(self, instance):
        return UserSerializer(instance).data


class RoleUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "email", "role"]
        read_only_fields = ["id", "email"]

    def validate(self, attrs):
        # An admin demoting themselves could leave the platform with no admin at all.
        if self.instance.pk == self.context["request"].user.pk:
            raise serializers.ValidationError("You cannot change your own role.")
        return attrs
