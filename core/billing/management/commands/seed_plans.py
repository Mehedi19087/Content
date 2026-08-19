"""
Seed billing Plan rows and create the auth Groups they map to.

This is the single source of plan definition for the billing app, mirroring
the existing `seed_categories` and `setup_roles` commands. Run it once after
you create the Lemon Squeezy product and variants in the LS dashboard and
copy their variant ids into the environment.

Env vars expected (one per tier):
    STARTER_VARIANT_ID
    PRO_VARIANT_ID
    ULTRA_VARIANT_ID (CREATOR_VARIANT_ID is accepted during migration)
    Yearly variants use the corresponding *_YEARLY_VARIANT_ID names.

Group <-> Plan mapping (matches the tier hierarchy in users/permissions.py):

    Plan slug | Group name     | Unlocks API endpoints (cumulative)
    ---------+----------------+---------------------------------------
    starter  | Starter Users  | ideas/refresh, ideas/youtube-intent
    pro      | Pro Users       | + ideas/thumbnail-preparation, youtube/* (channel ops)
    ultra    | Ultra Users    | + ideas/generate-package

Free Users is the default group; no Plan row is needed for it.
"""

import os

from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError

from billing.models import Plan


TIER_DEFS = [
    {
        "slug": "starter",
        "name": "Starter",
        "description": "Generate fresh trending ideas and YouTube intent research.",
        "group": "Starter Users",
        "variant_envs": ["STARTER_VARIANT_ID"],
        "product_envs": ["STARTER_PRODUCT_ID"],
        "price_cents": 999,
        "interval": Plan.Interval.MONTH,
        "sort_order": 1,
    },
    {
        "slug": "pro",
        "name": "Pro",
        "description": "Thumbnail preparation + YouTube channel connection and analysis.",
        "group": "Pro Users",
        "variant_envs": ["PRO_VARIANT_ID"],
        "product_envs": ["PRO_PRODUCT_ID"],
        "price_cents": 1999,
        "interval": Plan.Interval.MONTH,
        "sort_order": 2,
    },
    {
        "slug": "ultra",
        "name": "Ultra",
        "description": "Full packaging pipeline + final thumbnail image generation.",
        "group": "Ultra Users",
        "variant_envs": ["ULTRA_VARIANT_ID", "CREATOR_VARIANT_ID"],
        "product_envs": ["ULTRA_PRODUCT_ID", "CREATOR_PRODUCT_ID"],
        "price_cents": 3499,
        "interval": Plan.Interval.MONTH,
        "sort_order": 3,
    },
]

YEARLY_TIER_DEFS = [
    {
        "slug": "starter-yearly",
        "name": "Starter (Yearly)",
        "description": "Generate fresh trending ideas and YouTube intent research (billed annually).",
        "group": "Starter Users",
        "variant_envs": ["STARTER_YEARLY_VARIANT_ID"],
        "product_envs": ["STARTER_PRODUCT_ID"],
        "price_cents": 7999,
        "interval": Plan.Interval.YEAR,
        "sort_order": 4,
    },
    {
        "slug": "pro-yearly",
        "name": "Pro (Yearly)",
        "description": "Thumbnail preparation + YouTube channel connection and analysis (billed annually).",
        "group": "Pro Users",
        "variant_envs": ["PRO_YEARLY_VARIANT_ID"],
        "product_envs": ["PRO_PRODUCT_ID"],
        "price_cents": 19199,
        "interval": Plan.Interval.YEAR,
        "sort_order": 5,
    },
    {
        "slug": "ultra-yearly",
        "name": "Ultra (Yearly)",
        "description": "Full packaging pipeline + final thumbnail image generation (billed annually).",
        "group": "Ultra Users",
        "variant_envs": ["ULTRA_YEARLY_VARIANT_ID", "CREATOR_YEARLY_VARIANT_ID"],
        "product_envs": ["ULTRA_PRODUCT_ID", "CREATOR_PRODUCT_ID"],
        "price_cents": 33599,
        "interval": Plan.Interval.YEAR,
        "sort_order": 6,
    },
]


def _get_first_env(names: list[str]) -> str:
    for name in names:
        val = os.getenv(name)
        if val and val.strip():
            return val.strip()
    return ""


def _upsert_plan(definition: dict) -> tuple[Plan, bool]:
    variant_id = _get_first_env(definition["variant_envs"])
    product_id = _get_first_env(definition["product_envs"])
    plan = (
        Plan.objects.filter(lemon_variant_id=variant_id).first()
        or Plan.objects.filter(slug=definition["slug"]).first()
    )
    created = plan is None
    if plan is None:
        plan = Plan()

    plan.slug = definition["slug"]
    plan.name = definition["name"]
    plan.description = definition["description"]
    plan.group = definition["group"]
    plan.lemon_product_id = product_id
    plan.lemon_variant_id = variant_id
    plan.price_usd_cents = definition["price_cents"]
    plan.interval = definition["interval"]
    plan.is_active = True
    plan.sort_order = definition["sort_order"]
    plan.save()
    return plan, created


class Command(BaseCommand):
    help = "Seed billing plans and create the auth groups they map to."

    def handle(self, *args, **kwargs):
        definitions = TIER_DEFS + YEARLY_TIER_DEFS
        missing = [
            "/".join(tier["variant_envs"])
            for tier in definitions
            if not _get_first_env(tier["variant_envs"])
        ]

        if missing:
            raise CommandError(
                "Cannot seed billing plans. Missing env vars: " + ", ".join(missing)
            )

        group_names = {"Free Users", "Creator Users"}
        group_names.update(tier["group"] for tier in definitions)
        for group_name in group_names:
            Group.objects.get_or_create(name=group_name)

        for tier in definitions:
            plan, created = _upsert_plan(tier)
            action = "created" if created else "updated"
            self.stdout.write(
                self.style.SUCCESS(
                    f"Plan '{plan.name}' {action} (group='{plan.group}', variant={plan.lemon_variant_id})"
                )
            )

        self.stdout.write(self.style.SUCCESS("Seeding billing plans complete."))
