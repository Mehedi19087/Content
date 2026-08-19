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


# ----------------------------------------------------------------------
# Tier permissions (group-based, hierarchical)
# ----------------------------------------------------------------------
# The pricing matrix is cumulative: an upper tier unlocks every lower tier's
# features. So we model each permission class as "user is in any of these
# groups". Groups are populated by billing.services.recompute_user_entitlement
# based on the user's active Stripe/Lemon Squeezy subscription.

class HasTierPermission(permissions.BasePermission):
    """Base class — subclasses declare which tiers count via ALLOWED_GROUPS."""
    ALLOWED_GROUPS: tuple[str, ...] = ()

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return request.user.groups.filter(name__in=self.ALLOWED_GROUPS).exists()


class HasStarterPermission(HasTierPermission):
    """Starter + Pro + Ultra/Creator all unlock Starter-tier features."""
    ALLOWED_GROUPS = ("Starter Users", "Pro Users", "Ultra Users", "Creator Users")


class HasProPermission(HasTierPermission):
    """Pro + Ultra/Creator unlock Pro-tier features."""
    ALLOWED_GROUPS = ("Pro Users", "Ultra Users", "Creator Users")


class HasCreatorPermission(HasTierPermission):
    """Only the Ultra/Creator tier unlocks top-tier features (e.g. AI image gen)."""
    ALLOWED_GROUPS = ("Ultra Users", "Creator Users")


# Alias for Ultra tier
HasUltraPermission = HasCreatorPermission
