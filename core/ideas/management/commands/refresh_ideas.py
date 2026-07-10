from django.core.management.base import BaseCommand, CommandError

from categories.models import Category
from ideas.services import refresh_ideas_for_category


class Command(BaseCommand):
    help = "Refresh YouTube trend-backed idea candidates for one category or all active categories."

    def add_arguments(self, parser):
        parser.add_argument(
            "--category-slug",
            help="Refresh only one category by slug, for example ai-automation.",
        )
        parser.add_argument(
            "--region-code",
            default="US",
            help="YouTube API region code. Defaults to US.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=10,
            help="Number of final ideas to store per category. Defaults to 10.",
        )

    def handle(self, *args, **options):
        category_slug = options.get("category_slug")
        region_code = options["region_code"]
        limit = options["limit"]

        if category_slug:
            category_slugs = [category_slug]
        else:
            category_slugs = list(
                Category.objects.filter(
                    is_active=True,
                    default_regions__contains=[region_code],
                ).values_list("slug", flat=True)
            )

        if not category_slugs:
            raise CommandError(f"No active categories found for region {region_code}.")

        for slug in category_slugs:
            self.stdout.write(f"Refreshing ideas for {slug} ({region_code})...")
            ideas = refresh_ideas_for_category(
                category_slug=slug,
                region_code=region_code,
                limit=limit,
            )
            self.stdout.write(
                self.style.SUCCESS(f"Stored {len(ideas)} ideas for {slug}.")
            )
