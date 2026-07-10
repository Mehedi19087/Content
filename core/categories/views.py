from django.shortcuts import render

from rest_framework.views import APIView 
from rest_framework.response import Response
from rest_framework import status
from rest_framework.exceptions import ValidationError
from .serializers import CreateCategorySerializer, ResponseCategorySerializer
from .services import (
    create_category,
    get_categories,
    get_category_by_id,
    update_category,
    delete_category
)

class CreateListCategoryAPIView(APIView):
    def get(self, request):
        # Retrieve all categories and serialize them
        categories = get_categories()
        serializer = ResponseCategorySerializer(categories, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        serializer = CreateCategorySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            # Call the service layer with the validated data dictionary
            category = create_category(serializer.validated_data)
            
            # Serialize the newly created category instance for the response
            response_serializer = ResponseCategorySerializer(category)
            
            return Response(
                {
                    "message": "category created successfully",
                    "data": response_serializer.data,
                },
                status=status.HTTP_201_CREATED,
            )
        except ValidationError as e:
            # Let DRF handle ValidationError automatically to return HTTP 400
            raise e
        except Exception as e:
            # Catch unexpected server/database failures and describe them cleanly
            return Response(
                {
                    "message": "Failed to create category due to an internal server error.",
                    "detail": str(e)
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class CategoryDetailAPIView(APIView):
    def get(self, request, pk):
        # Retrieve a single category by ID
        category = get_category_by_id(pk)
        serializer = ResponseCategorySerializer(category)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def put(self, request, pk):
        # Retrieve the existing category
        category = get_category_by_id(pk)
        
        # Validate data against the serializer (partial=True allows partial updates)
        serializer = CreateCategorySerializer(category, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        
        try:
            # Call the service to save changes
            updated_category = update_category(category, serializer.validated_data)
            response_serializer = ResponseCategorySerializer(updated_category)
            return Response(
                {
                    "message": "category updated successfully",
                    "data": response_serializer.data,
                },
                status=status.HTTP_200_OK,
            )
        except ValidationError as e:
            raise e
        except Exception as e:
            return Response(
                {
                    "message": "Failed to update category due to an internal server error.",
                    "detail": str(e)
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def delete(self, request, pk):
        # Retrieve and delete the category
        category = get_category_by_id(pk)
        try:
            delete_category(category)
            return Response(
                {"message": "category deleted successfully"},
                status=status.HTTP_200_OK,
            )
        except Exception as e:
            return Response(
                {
                    "message": "Failed to delete category due to an internal server error.",
                    "detail": str(e)
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


