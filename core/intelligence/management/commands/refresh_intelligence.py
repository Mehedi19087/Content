from django.core.management.base import BaseCommand

from intelligence.workflow_services import refresh_due_pools


class Command(BaseCommand):
    help = "Queue due shared niche refreshes, with at most monthly rediscovery."

    def handle(self, *args, **options):
        results = refresh_due_pools()
        self.stdout.write(f"Checked due niches: {len(results)}; results: {results}")
