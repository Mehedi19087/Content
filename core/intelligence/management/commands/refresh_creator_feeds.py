from django.core.management.base import BaseCommand

from intelligence.workflow_services import refresh_due_creator_feeds


class Command(BaseCommand):
    help = "Queue due creator video idea feed refreshes for channels with confirmed DNA."

    def handle(self, *args, **options):
        results = refresh_due_creator_feeds()
        self.stdout.write(
            f"Checked due creator feeds: {len(results)}; results: {results}"
        )
