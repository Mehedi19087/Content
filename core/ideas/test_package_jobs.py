from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from .models import ContentPackageJob
from .tasks import generate_content_package_task


User = get_user_model()


def package_request_payload():
    return {
        "idea": "5 AI tools that can replace your assistant",
        "youtube_intent": {
            "viewer_intent": "People want AI tools that save time.",
            "content_type": "Tool comparison",
            "title_patterns": ["Best [topic]"],
            "emotional_angles": ["Save time"],
            "thumbnail_subjects": ["Creator comparing AI tools"],
            "seo_keywords": ["ai tools"],
        },
        "selected_hook": {
            "id": "time-saving",
            "angle": "Save time",
            "thumbnail_text": "SAVE HOURS",
        },
        "subject_plan": [
            {
                "type": "human",
                "description": "Creator comparing AI tools",
                "source": "ai_generate",
            }
        ],
        "creator_image_choice": {"skip_creator_image": True},
    }


class ContentPackageJobAPITestCase(APITestCase):
    def setUp(self):
        creator_group = Group.objects.create(name="Creator Users")
        self.user = User.objects.create_user(username="creator", password="password")
        self.user.groups.add(creator_group)
        self.other_user = User.objects.create_user(
            username="other-creator",
            password="password",
        )
        self.other_user.groups.add(creator_group)
        self.client.force_authenticate(user=self.user)

    @patch("ideas.views.generate_content_package_task.apply_async")
    def test_start_generation_returns_durable_pending_job(self, mock_delay):
        mock_delay.return_value.id = "celery-task-id"

        response = self.client.post(
            reverse("ideas-generate-package"),
            package_request_payload(),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        job = ContentPackageJob.objects.get(id=response.data["data"]["id"])
        self.assertEqual(job.user, self.user)
        self.assertEqual(job.status, ContentPackageJob.Status.PENDING)
        self.assertEqual(job.celery_task_id, "celery-task-id")
        mock_delay.assert_called_once_with(args=[str(job.id)], retry=False)

    @patch("ideas.views.generate_content_package_task.apply_async")
    def test_queue_failure_is_saved_and_returns_service_unavailable(self, mock_delay):
        mock_delay.side_effect = ConnectionError("Redis unavailable")

        response = self.client.post(
            reverse("ideas-generate-package"),
            package_request_payload(),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        job = ContentPackageJob.objects.get(user=self.user)
        self.assertEqual(job.status, ContentPackageJob.Status.FAILED)
        self.assertEqual(job.error_code, "queue_unavailable")
        self.assertNotIn("Redis unavailable", response.data["message"])

    def test_user_can_fetch_own_job(self):
        job = ContentPackageJob.objects.create(
            user=self.user,
            request_payload=package_request_payload(),
        )

        response = self.client.get(
            reverse("ideas-generation-job-detail", kwargs={"job_id": job.id})
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["status"], "pending")
        self.assertIsNone(response.data["data"]["result"])

    def test_user_cannot_fetch_another_users_job(self):
        job = ContentPackageJob.objects.create(
            user=self.other_user,
            request_payload=package_request_payload(),
        )

        response = self.client.get(
            reverse("ideas-generation-job-detail", kwargs={"job_id": job.id})
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @override_settings(CONTENT_PACKAGE_JOB_STALE_SECONDS=600)
    def test_stale_pending_job_becomes_failed(self):
        job = ContentPackageJob.objects.create(
            user=self.user,
            request_payload=package_request_payload(),
        )
        ContentPackageJob.objects.filter(id=job.id).update(
            created_at=timezone.now() - timedelta(minutes=11)
        )

        response = self.client.get(
            reverse("ideas-generation-job-detail", kwargs={"job_id": job.id})
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["status"], "failed")
        self.assertEqual(
            response.data["data"]["error_code"],
            "generation_timed_out",
        )


class ContentPackageTaskTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="worker-user", password="password")
        self.job = ContentPackageJob.objects.create(
            user=self.user,
            request_payload=package_request_payload(),
        )

    @patch("ideas.tasks.generate_content_package")
    def test_task_saves_successful_result(self, mock_generate_content_package):
        mock_generate_content_package.return_value = {
            "thumbnail": {"url": "https://example.com/image.png"},
            "seo": {"title": "AI tools"},
            "script": {"format": "creator_talking_guide"},
            "edit_options": ["Change thumbnail text"],
        }

        generate_content_package_task.run(str(self.job.id))

        self.job.refresh_from_db()
        self.assertEqual(self.job.status, ContentPackageJob.Status.SUCCEEDED)
        self.assertEqual(self.job.stage, "completed")
        self.assertEqual(self.job.result["seo"]["title"], "AI tools")
        self.assertIsNotNone(self.job.started_at)
        self.assertIsNotNone(self.job.finished_at)

    @patch("ideas.tasks.generate_content_package")
    def test_task_saves_safe_failure(self, mock_generate_content_package):
        mock_generate_content_package.side_effect = RuntimeError("secret provider error")

        with self.assertRaises(RuntimeError):
            generate_content_package_task.run(str(self.job.id))

        self.job.refresh_from_db()
        self.assertEqual(self.job.status, ContentPackageJob.Status.FAILED)
        self.assertEqual(self.job.error_code, "generation_failed")
        self.assertNotIn("secret provider error", self.job.error_message)

    @patch("ideas.tasks.generate_content_package")
    def test_terminal_job_is_not_generated_again(self, mock_generate_content_package):
        self.job.status = ContentPackageJob.Status.SUCCEEDED
        self.job.stage = "completed"
        self.job.save(update_fields=["status", "stage", "updated_at"])

        generate_content_package_task.run(str(self.job.id))

        mock_generate_content_package.assert_not_called()
