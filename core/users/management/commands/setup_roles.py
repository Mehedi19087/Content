from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from categories.models import Category
from ideas.models import IdeaCandidate

class Command(BaseCommand):
    help = "Sets up default user groups and assigns default permissions."

    def handle(self, *args, **kwargs):
        # 1. Create/Get Groups
        free_group, _ = Group.objects.get_or_create(name="Free Users")
        premium_group, _ = Group.objects.get_or_create(name="Premium Users")

        # 2. Get content types
        category_type = ContentType.objects.get_for_model(Category)
        idea_type = ContentType.objects.get_for_model(IdeaCandidate)

        # 3. Get permissions from database
        category_perms = Permission.objects.filter(content_type=category_type)
        idea_perms = Permission.objects.filter(content_type=idea_type)

        # 4. Set permissions for Free Users: ONLY view_category
        view_category_perm = category_perms.get(codename="view_category")
        free_group.permissions.set([view_category_perm])
        self.stdout.write(self.style.SUCCESS('Assigned ONLY "view_category" to "Free Users".'))

        # 5. Set permissions for Premium Users: All category and idea permissions
        all_perms = list(category_perms) + list(idea_perms)
        premium_group.permissions.set(all_perms)
        self.stdout.write(self.style.SUCCESS('Assigned all category and idea permissions to "Premium Users".'))
