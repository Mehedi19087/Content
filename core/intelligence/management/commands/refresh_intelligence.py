from django.core.management.base import BaseCommand

from intelligence.workflow_services import refresh_due_pools


class Command(BaseCommand):
    help = "Queue due shared YouTube evidence refreshes and discovery retries."

    def handle(self, *args, **options):
        results = refresh_due_pools()
        self.stdout.write(f"Checked due niches: {len(results)}; results: {results}")
