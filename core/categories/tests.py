from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from .models import Category


User = get_user_model()


class CategoryAPITestCase(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="category-admin",
            email="category-admin@example.com",
            password="secret123",
        )
        self.client.force_authenticate(user=self.admin)
        self.category = Category.objects.create(name="CAT", slug="cat-slug")

    def test_create_category(self):
        response = self.client.post(
            reverse("category-create-list"),
            {"name": "DOG", "slug": "dog-slug"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["data"]["name"], "DOG")
        self.assertEqual(response.data["data"]["slug"], "dog-slug")

    def test_authenticated_user_can_list_categories_without_model_permission(self):
        user = User.objects.create_user(
            username="category-viewer",
            email="category-viewer@example.com",
            password="secret123",
        )
        access_token = RefreshToken.for_user(user).access_token
        self.client.force_authenticate(user=None)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")

        response = self.client.get(reverse("category-create-list"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data), 1)

    def test_list_categories_requires_authentication(self):
        self.client.force_authenticate(user=None)

        response = self.client.get(reverse("category-create-list"))

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data["error"]["code"], "not_authenticated")

    def test_retrieve_category(self):
        response = self.client.get(
            reverse("category-detail", kwargs={"pk": self.category.id}),
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["name"], "CAT")
        self.assertEqual(response.data["slug"], "cat-slug")

    def test_retrieve_category_not_found(self):
        response = self.client.get(
            reverse("category-detail", kwargs={"pk": 9999}),
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_update_category(self):
        response = self.client.put(
            reverse("category-detail", kwargs={"pk": self.category.id}),
            {"name": "PET", "slug": "pet-slug"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["name"], "PET")
        self.assertEqual(response.data["data"]["slug"], "pet-slug")

        self.category.refresh_from_db()
        self.assertEqual(self.category.name, "PET")
        self.assertEqual(self.category.slug, "pet-slug")

    def test_delete_category(self):
        response = self.client.delete(
            reverse("category-detail", kwargs={"pk": self.category.id}),
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["message"], "category deleted successfully")
        self.assertFalse(Category.objects.filter(id=self.category.id).exists())
