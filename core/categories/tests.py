from django.urls import reverse
from rest_framework.test import APITestCase
from rest_framework import status
from .models import Category

class CategoryAPITestCase(APITestCase):
    def setUp(self):
        # Create a sample category for testing retrieve, update, and delete
        self.category = Category.objects.create(name='CAT', slug='cat-slug')

    def test_create_category(self):
        url = reverse('category-create-list')
        data = {
            'name': 'DOG',
            'slug': 'dog-slug'
        }
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['data']['name'], 'DOG')
        self.assertEqual(response.data['data']['slug'], 'dog-slug')

    def test_list_categories(self):
        url = reverse('category-create-list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should return list containing at least our setup category
        self.assertGreaterEqual(len(response.data), 1)

    def test_retrieve_category(self):
        url = reverse('category-detail', kwargs={'pk': self.category.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['name'], 'CAT')
        self.assertEqual(response.data['slug'], 'cat-slug')

    def test_retrieve_category_not_found(self):
        url = reverse('category-detail', kwargs={'pk': 9999})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_update_category(self):
        url = reverse('category-detail', kwargs={'pk': self.category.id})
        data = {
            'name': 'PET',
            'slug': 'pet-slug'
        }
        response = self.client.put(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['data']['name'], 'PET')
        self.assertEqual(response.data['data']['slug'], 'pet-slug')

        # Verify it updated in the database
        self.category.refresh_from_db()
        self.assertEqual(self.category.name, 'PET')
        self.assertEqual(self.category.slug, 'pet-slug')

    def test_delete_category(self):
        url = reverse('category-detail', kwargs={'pk': self.category.id})
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['message'], 'category deleted successfully')

        # Verify it is deleted from the database
        self.assertFalse(Category.objects.filter(id=self.category.id).exists())


