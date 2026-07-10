from django.db import IntegrityError
from django.db.models import QuerySet
from rest_framework.exceptions import ValidationError, NotFound
from .models import Category 


def create_category(validated_data: dict) -> Category:
    """
    Creates a new category.
    Handles database integrity errors (like duplicate name or slug)
    and raises clean, descriptive validation errors for the API.
    """
    try:
        return Category.objects.create(**validated_data)
    except IntegrityError as e:
        error_message = str(e).lower()
        if 'name' in error_message:
            raise ValidationError({"name": "A category with this name already exists."})
        if 'slug' in error_message:
            raise ValidationError({"slug": "A category with this slug already exists."})
        raise ValidationError({"non_field_errors": ["Could not create category due to a database integrity issue."]})


def get_categories() -> QuerySet[Category]:
    """
    Returns active creator-facing categories.
    """
    return Category.objects.filter(is_active=True).order_by('name')


def get_category_by_id(category_id: int) -> Category:
    """
    Retrieves a category by ID or raises NotFound exception.
    """
    try:
        return Category.objects.get(id=category_id)
    except Category.DoesNotExist:
        raise NotFound("Category not found.")


def update_category(category: Category, validated_data: dict) -> Category:
    """
    Updates an existing category instance.
    Handles unique constraints violations during update.
    """
    try:
        for attr, value in validated_data.items():
            setattr(category, attr, value)
        category.save()
        return category
    except IntegrityError as e:
        error_message = str(e).lower()
        if 'name' in error_message:
            raise ValidationError({"name": "A category with this name already exists."})
        if 'slug' in error_message:
            raise ValidationError({"slug": "A category with this slug already exists."})
        raise ValidationError({"non_field_errors": ["Could not update category due to a database integrity issue."]})


def delete_category(category: Category) -> None:
    """
    Deletes a category instance.
    """
    category.delete()
