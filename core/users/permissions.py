from rest_framework import permissions

class HasCategoryWritePermission(permissions.BasePermission):
    """
    Checks if the user has appropriate Django default model permissions for Category.
    - Safe methods (GET, HEAD, OPTIONS) require: 'categories.view_category'
    - POST (create) requires: 'categories.add_category'
    - PUT/PATCH (update) requires: 'categories.change_category'
    - DELETE requires: 'categories.delete_category'
    """
    def has_permission(self, request, view):
        # 1. User must be authenticated
        if not request.user or not request.user.is_authenticated:
            return False

        # 2. Check permission based on HTTP method
        if request.method in permissions.SAFE_METHODS:
            return request.user.has_perm("categories.view_category")
        
        if request.method == "POST":
            return request.user.has_perm("categories.add_category")
            
        if request.method in ["PUT", "PATCH"]:
            return request.user.has_perm("categories.change_category")
            
        if request.method == "DELETE":
            return request.user.has_perm("categories.delete_category")
            
        return False


class HasIdeaWritePermission(permissions.BasePermission):
    """
    Checks if the user has appropriate Django default model permissions for IdeaCandidate.
    - Safe methods (GET) require: 'ideas.view_ideacandidate'
    - Write/Execute methods (POST) require: 'ideas.add_ideacandidate'
    """
    def has_permission(self, request, view):
        # 1. User must be authenticated
        if not request.user or not request.user.is_authenticated:
            return False

        # 2. Check permission based on HTTP method
        if request.method in permissions.SAFE_METHODS:
            return request.user.has_perm("ideas.view_ideacandidate")
            
        if request.method == "POST":
            return request.user.has_perm("ideas.add_ideacandidate")
            
        return False
