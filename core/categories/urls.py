from django.urls import path
from .views import CreateListCategoryAPIView, CategoryDetailAPIView

urlpatterns = [
    path('categories/', CreateListCategoryAPIView.as_view(), name='category-create-list'),
    path('categories/<int:pk>/', CategoryDetailAPIView.as_view(), name='category-detail'),
]
