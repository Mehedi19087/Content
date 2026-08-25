import json
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from .deepseek_client import DeepSeekClient
from .groq_client import GroqClient
from .openai_image_client import OpenAIImageClient
from .views import GeneratePackageAPIView


class ProviderTimingLogTestCase(SimpleTestCase):
    @override_settings(DEEPSEEK_TIMEOUT_SECONDS=60)
    @patch("ideas.deepseek_client.time.perf_counter", side_effect=[10.0, 12.5])
    @patch("ideas.deepseek_client.urllib.request.urlopen")
    def test_deepseek_logs_provider_duration(self, mock_urlopen, mock_perf_counter):
        response = MagicMock()
        response.read.return_value = (
            b'{"choices":[{"message":{"content":"{\\"ideas\\": []}"}}]}'
        )
        mock_urlopen.return_value.__enter__.return_value = response

        with self.assertLogs("ideas.performance", level="INFO") as logs:
            DeepSeekClient(api_key="key", model="model").generate_json(
                system_prompt="Return JSON.",
                user_payload={"topic": "AI tools"},
            )

        self.assertIn("provider=deepseek", logs.output[0])
        self.assertIn("outcome=succeeded", logs.output[0])
        self.assertIn("duration_seconds=2.500", logs.output[0])

    @override_settings(
        GROQ_TIMEOUT_SECONDS=60,
        GROQ_REASONING_EFFORT="low",
        GROQ_MAX_COMPLETION_TOKENS=2048,
        GROQ_RATE_LIMIT_RETRIES=1,
        GROQ_MAX_RETRY_WAIT_SECONDS=30,
    )
    @patch("ideas.groq_client.time.perf_counter", side_effect=[20.0, 21.25])
    @patch("ideas.groq_client.urllib.request.urlopen")
    def test_groq_logs_provider_duration(self, mock_urlopen, mock_perf_counter):
        response = MagicMock()
        response.read.return_value = (
            b'{"choices":[{"message":{"content":"{\\"ideas\\": []}"}}]}'
        )
        mock_urlopen.return_value.__enter__.return_value = response

        with self.assertLogs("ideas.performance", level="INFO") as logs:
            GroqClient(api_key="key", model="model").generate_json(
                system_prompt="Return JSON.",
                user_payload={"topic": "AI tools"},
            )

        self.assertIn("provider=groq", logs.output[0])
        self.assertIn("outcome=succeeded", logs.output[0])
        self.assertIn("duration_seconds=1.250", logs.output[0])

    @override_settings(
        OPENAI_TIMEOUT_SECONDS=120,
        OPENAI_IMAGE_MODEL="gpt-image-2",
        OPENAI_IMAGE_SIZE="1536x1024",
        OPENAI_IMAGE_QUALITY="low",
        OPENAI_IMAGE_OUTPUT_FORMAT="png",
        CLOUDINARY_CLOUD_NAME="cloud",
        CLOUDINARY_API_KEY="key",
        CLOUDINARY_API_SECRET="secret",
    )
    @patch(
        "ideas.openai_image_client.time.perf_counter",
        side_effect=[30.0, 32.0, 40.0, 40.75],
    )
    @patch("ideas.openai_image_client.cloudinary.uploader.upload")
    @patch("ideas.openai_image_client.urllib.request.urlopen")
    def test_openai_and_cloudinary_log_separate_durations(
        self,
        mock_urlopen,
        mock_upload,
        mock_perf_counter,
    ):
        response = MagicMock()
        response.read.return_value = json.dumps(
            {"data": [{"b64_json": "aW1hZ2UtYnl0ZXM="}]}
        ).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = response
        mock_upload.return_value = {
            "secure_url": "https://example.com/image.png",
            "public_id": "creatorintent/generated_thumbnails/test",
        }

        with self.assertLogs("ideas.performance", level="INFO") as logs:
            OpenAIImageClient(api_key="key").generate_thumbnail(prompt="A prompt")

        output = "\n".join(logs.output)
        self.assertIn("provider=openai", output)
        self.assertIn("duration_seconds=2.000", output)
        self.assertIn("provider=cloudinary", output)
        self.assertIn("duration_seconds=0.750", output)


class RequestTimingLogTestCase(SimpleTestCase):
    @patch("ideas.views.time.perf_counter", side_effect=[50.0, 53.5])
    @patch("ideas.views.ResponseContentPackageJobSerializer")
    @patch("ideas.views.mark_content_package_job_dispatched")
    @patch("ideas.views.generate_content_package_task.apply_async")
    @patch("ideas.views.create_content_package_job")
    @patch("ideas.views.GeneratePackageSerializer")
    def test_generate_package_view_logs_total_duration(
        self,
        mock_request_serializer,
        mock_create_job,
        mock_delay,
        mock_mark_dispatched,
        mock_response_serializer,
        mock_perf_counter,
    ):
        request_serializer = mock_request_serializer.return_value
        request_serializer.validated_data = {"idea": "An example idea"}
        job = mock_create_job.return_value
        job.id = "job-id"
        mock_delay.return_value.id = "task-id"
        mock_response_serializer.return_value.data = {"status": "pending"}
        request = MagicMock()
        request.data = {"idea": "An example idea"}
        request.user = MagicMock()

        with self.assertLogs("ideas.performance", level="INFO") as logs:
            response = GeneratePackageAPIView().post(request)

        self.assertEqual(response.status_code, 202)
        self.assertIn("endpoint=generate_package", logs.output[0])
        self.assertIn("outcome=succeeded", logs.output[0])
        self.assertIn("duration_seconds=3.500", logs.output[0])
