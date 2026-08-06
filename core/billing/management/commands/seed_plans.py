"""
Seed billing Plan rows and create the auth Groups they map to.

This is the single source of plan definition for the billing app, mirroring
the existing `seed_categories` and `setup_roles` commands. Run it once after
you create the Lemon Squeezy product and variants in the LS dashboard and
copy their variant ids into the environment.

Env vars expected (one per tier):
    STARTER_VARIANT_ID
    PRO_VARIANT_ID
    CREATOR_VARIANT_ID
    (optional) STARTER_PRODUCT_ID / PRO_PRODUCT_ID / CREATOR_PRODUCT_ID

Group <-> Plan mapping (matches the tier hierarchy in users/permissions.py):

    Plan slug | Group name     | Unlocks API endpoints (cumulative)
    ---------+----------------+---------------------------------------
    starter  | Starter Users  | ideas/refresh, ideas/youtube-intent
    pro      | Pro Users       | + ideas/thumbnail-preparation, youtube/* (channel ops)
    creator  | Creator Users  | + ideas/generate-package

Free Users is the default group; no Plan row is needed for it.
"""

import os

from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand

from billing.models import Plan


TIER_DEFS = [
    {
        "slug": "starter",
        "name": "Starter",
        "description": "Generate fresh trending ideas and YouTube intent research.",
        "group": "Starter Users",
        "variant_env": "STARTER_VARIANT_ID",
        "product_env": "STARTER_PRODUCT_ID",
        "price_cents": 1900,
        "interval": Plan.Interval.MONTH,
        "sort_order": 1,
    },
    {
        "slug": "pro",
        "name": "Pro",
        "description": "Thumbnail preparation + YouTube channel connection and analysis.",
        "group": "Pro Users",
        "variant_env": "PRO_VARIANT_ID",
        "product_env": "PRO_PRODUCT_ID",
        "price_cents": 4900,
        "interval": Plan.Interval.MONTH,
        "sort_order": 2,
    },
    {
        "slug": "creator",
        "name": "Creator",
        "description": "Full packaging pipeline + final thumbnail image generation.",
        "group": "Creator Users",
        "variant_env": "CREATOR_VARIANT_ID",
        "product_env": "CREATOR_PRODUCT_ID",
        "price_cents": 9900,
        "interval": Plan.Interval.MONTH,
        "sort_order": 3,
    },
]


class Command(BaseCommand):
    help = "Seed billing plans and create the auth groups they map to."

    def handle(self, *args, **kwargs):
        missing = []
        for tier in TIER_DEFS:
            if not os.getenv(tier["variant_env"]):
                missing.append(tier["variant_env"])

        if missing:
            self.stdout.write(
                self.style.ERROR(
                    "Missing env vars: " + ", ".join(missing) + ". "
                    "Create the product and variants in Lemon Squeezy first, "
                    "then set the variant ids in your environment and rerun."
                )
            )
            return

        # Free group is the fallback used by recompute_user_entitlement.
        Group.objects.get_or_create(name="Free Users")

        for tier in TIER_DEFS:
            Group.objects.get_or_create(name=tier["group"])
            variant_id = os.getenv(tier["variant_env"])
            product_id = os.getenv(tier["product_env"], "")
            plan, created = Plan.objects.update_or_create(
                slug=tier["slug"],
                defaults={
                    "name": tier["name"],
                    "description": tier["description"],
                    "group": tier["group"],
                    "lemon_product_id": product_id,
                    "lemon_variant_id": variant_id,
                    "price_usd_cents": tier["price_cents"],
                    "interval": tier["interval"],
                    "is_active": True,
                    "sort_order": tier["sort_order"],
                },
            )
            action = "created" if created else "updated"
            self.stdout.write(
                self.style.SUCCESS(
                    f"Plan '{plan.name}' {action} (group='{plan.group}', variant={plan.lemon_variant_id})"
                )
            )

        self.stdout.write(self.style.SUCCESS("Seeding billing plans complete."))