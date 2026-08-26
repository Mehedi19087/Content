import json
from io import BytesIO
import urllib.error
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import override_settings
from django.urls import reverse
from rest_framework.exceptions import ValidationError
from rest_framework import status
from rest_framework.test import APITestCase

from categories.models import Category
from .deepseek_client import DeepSeekClient
from .groq_client import GroqClient
from .llm_client import TextGenerationClient
from .models import ContentPackageJob, IdeaCandidate
from .openai_image_client import OpenAIImageClient
from .services import (
    filter_relevant_phrases,
    generate_content_package,
    generate_contextual_intent_analysis,
    generate_script_guide,
    normalize_script_guide,
    refresh_all_ideas_for_cron,
    research_youtube_intent_for_idea,
    validate_generated_ideas,
)
from .youtube_suggest_client import YouTubeSuggestClient
from .youtube_client import YouTubeAPIError, YouTubeClient

User = get_user_model()


class DeepSeekClientTestCase(APITestCase):
    @override_settings(DEEPSEEK_TIMEOUT_SECONDS=60)
    @patch("ideas.deepseek_client.urllib.request.urlopen")
    def test_generate_json_uses_deepseek_api(self, mock_urlopen):
        response = MagicMock()
        response.read.return_value = (
            b'{"choices":[{"message":{"content":"{\\"ideas\\": []}"}}]}'
        )
        mock_urlopen.return_value.__enter__.return_value = response

        result = DeepSeekClient(
            api_key="deepseek-key",
            model="deepseek-v4-flash",
        ).generate_json(
            system_prompt="Return JSON.",
            user_payload={"topic": "AI tools"},
        )

        request = mock_urlopen.call_args.args[0]
        request_body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(request.full_url, "https://api.deepseek.com/chat/completions")
        self.assertEqual(request.get_header("Authorization"), "Bearer deepseek-key")
        self.assertEqual(request_body["model"], "deepseek-v4-flash")
        self.assertEqual(result, {"ideas": []})

    @override_settings(DEEPSEEK_API_KEY="", DEEPSEEK_MODEL="deepseek-v4-flash")
    def test_client_requires_deepseek_api_key(self):
        with self.assertRaises(ValidationError) as context:
            DeepSeekClient()

        self.assertIn("deepseek_api_key", context.exception.detail)


class GroqClientTestCase(APITestCase):
    @override_settings(
        GROQ_TIMEOUT_SECONDS=60,
        GROQ_REASONING_EFFORT="low",
        GROQ_MAX_COMPLETION_TOKENS=2048,
        GROQ_RATE_LIMIT_RETRIES=1,
        GROQ_MAX_RETRY_WAIT_SECONDS=30,
    )
    @patch("ideas.groq_client.urllib.request.urlopen")
    def test_generate_json_uses_current_groq_model(self, mock_urlopen):
        response = MagicMock()
        response.read.return_value = (
            b'{"choices":[{"message":{"content":"{\\"ideas\\": []}"}}]}'
        )
        mock_urlopen.return_value.__enter__.return_value = response

        result = GroqClient(
            api_key="groq-key",
            model="openai/gpt-oss-120b",
        ).generate_json(
            system_prompt="Return JSON.",
            user_payload={"topic": "AI tools"},
        )

        request = mock_urlopen.call_args.args[0]
        request_body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(
            request.full_url,
            "https://api.groq.com/openai/v1/chat/completions",
        )
        self.assertEqual(request_body["model"], "openai/gpt-oss-120b")
        self.assertEqual(request_body["reasoning_effort"], "low")
        self.assertEqual(request_body["max_completion_tokens"], 2048)
        self.assertEqual(result, {"ideas": []})

    @override_settings(
        GROQ_TIMEOUT_SECONDS=60,
        GROQ_REASONING_EFFORT="low",
        GROQ_MAX_COMPLETION_TOKENS=2048,
        GROQ_RATE_LIMIT_RETRIES=1,
        GROQ_MAX_RETRY_WAIT_SECONDS=30,
    )
    @patch("ideas.groq_client.time.sleep")
    @patch("ideas.groq_client.urllib.request.urlopen")
    def test_generate_json_retries_short_rate_limit(
        self,
        mock_urlopen,
        mock_sleep,
    ):
        rate_limit_error = urllib.error.HTTPError(
            url="https://api.groq.com/openai/v1/chat/completions",
            code=429,
            msg="Too Many Requests",
            hdrs={"Retry-After": "2.5"},
            fp=BytesIO(b'{"error":{"message":"Rate limited"}}'),
        )
        response = MagicMock()
        response.read.return_value = (
            b'{"choices":[{"message":{"content":"{\\"ideas\\": []}"}}]}'
        )
        mock_urlopen.side_effect = [rate_limit_error, response]
        response.__enter__.return_value = response

        result = GroqClient(
            api_key="groq-key",
            model="openai/gpt-oss-120b",
        ).generate_json(
            system_prompt="Return JSON.",
            user_payload={"topic": "AI tools"},
        )

        self.assertEqual(result, {"ideas": []})
        mock_sleep.assert_called_once_with(2.5)
        self.assertEqual(mock_urlopen.call_count, 2)


class TextGenerationClientTestCase(APITestCase):
    @patch("ideas.llm_client.GroqClient")
    @patch("ideas.llm_client.DeepSeekClient")
    def test_uses_deepseek_without_calling_groq(
        self,
        mock_deepseek_client,
        mock_groq_client,
    ):
        mock_deepseek_client.return_value.generate_json.return_value = {"source": "deepseek"}

        result = TextGenerationClient().generate_json(
            system_prompt="Return JSON.",
            user_payload={"topic": "AI tools"},
        )

        self.assertEqual(result, {"source": "deepseek"})
        mock_groq_client.assert_not_called()

    @patch("ideas.llm_client.GroqClient")
    @patch("ideas.llm_client.DeepSeekClient")
    def test_uses_groq_when_deepseek_fails(
        self,
        mock_deepseek_client,
        mock_groq_client,
    ):
        mock_deepseek_client.return_value.generate_json.side_effect = ValidationError(
            {"deepseek_api": "Unavailable"}
        )
        mock_groq_client.return_value.generate_json.return_value = {"source": "groq"}

        result = TextGenerationClient().generate_json(
            system_prompt="Return JSON.",
            user_payload={"topic": "AI tools"},
        )

        self.assertEqual(result, {"source": "groq"})
        mock_groq_client.return_value.generate_json.assert_called_once()


class ContextualIntentAnalysisTestCase(APITestCase):
    @patch("ideas.services.TextGenerationClient")
    def test_uses_title_specific_analysis_from_llm(self, mock_text_client_class):
        mock_text_client_class.return_value.generate_json.return_value = {
            "viewer_intent": (
                "Creators want proof of which AI tools remove real workflow steps."
            ),
            "content_type": "hands-on creator workflow tool comparison",
            "title_patterns": [
                "I Tested [number] [topic] for [workflow]",
                "[topic]: Which One Actually [result]?",
                "[number] [topic] Ranked by [constraint]",
            ],
            "emotional_angles": [
                "relief from repetitive production work",
                "skepticism about exaggerated automation claims",
                "confidence in choosing one practical tool",
            ],
            "thumbnail_subjects": [
                "creator comparing five completed automation results",
                "content calendar filling itself with finished posts",
                "stack of repetitive tasks reduced to one workflow",
            ],
            "seo_keywords": [
                "ai tools for creator workflows",
                "creator automation tool comparison",
                "automate content creation workflow",
            ],
        }

        result = generate_contextual_intent_analysis(
            idea="I Tested 5 AI Tools That Automate a Creator Workflow",
            query="tested ai tools automate creator workflow",
            videos=[
                {
                    "title": "Testing Current Creator Automation Tools",
                    "description": "A workflow comparison.",
                    "tags": ["creator automation"],
                    "view_count": 1000,
                    "like_count": 100,
                }
            ],
            search_suggestions=["ai tools for creator workflows"],
        )

        self.assertEqual(
            result["thumbnail_subjects"],
            [
                "creator comparing five completed automation results",
                "content calendar filling itself with finished posts",
                "stack of repetitive tasks reduced to one workflow",
            ],
        )
        self.assertEqual(
            result["content_type"],
            "hands-on creator workflow tool comparison",
        )
        self.assertEqual(
            result["emotional_angles"][0],
            "relief from repetitive production work",
        )
        payload = mock_text_client_class.return_value.generate_json.call_args.kwargs[
            "user_payload"
        ]
        self.assertEqual(
            payload["video_title"],
            "I Tested 5 AI Tools That Automate a Creator Workflow",
        )

    @patch("ideas.services.TextGenerationClient")
    def test_falls_back_to_title_and_evidence_when_both_llms_fail(
        self,
        mock_text_client_class,
    ):
        mock_text_client_class.return_value.generate_json.side_effect = ValidationError(
            {"llm_api": "Unavailable"}
        )

        result = generate_contextual_intent_analysis(
            idea="A Solar Generator Powered My Studio for 24 Hours",
            query="solar generator powered studio 24 hours",
            videos=[
                {
                    "title": "Testing a Solar Generator for 24 Hours",
                    "description": "Studio power test.",
                    "tags": ["solar generator", "studio power"],
                }
            ],
            search_suggestions=["solar generator for studio"],
        )

        self.assertEqual(
            result["thumbnail_subjects"],
            ["A Solar Generator Powered My Studio for 24 Hours"],
        )
        self.assertIn("solar generator", result["seo_keywords"])
        self.assertEqual(result["emotional_angles"], [])

    def test_filters_unrelated_search_suggestions(self):
        result = filter_relevant_phrases(
            idea="Fallout Beginner Survival Tutorial",
            phrases=[
                "fallout beginner guide",
                "fallout survival tutorial",
                "outfit idea",
            ],
        )

        self.assertEqual(
            result,
            ["fallout beginner guide", "fallout survival tutorial"],
        )


class YouTubeClientTestCase(APITestCase):
    def test_popular_videos_skip_unavailable_category_chart(self):
        client = YouTubeClient(api_key="youtube-key")
        client._get = MagicMock(
            side_effect=[
                YouTubeAPIError("Chart unavailable", upstream_status_code=404),
                {"items": [{"id": "video-1"}]},
            ]
        )

        videos = client.fetch_most_popular_videos(
            category_ids=["27", "25"],
            region_code="US",
        )

        self.assertEqual([video["id"] for video in videos], ["video-1"])
        self.assertEqual(client._get.call_count, 2)

    def test_popular_videos_do_not_hide_other_youtube_errors(self):
        client = YouTubeClient(api_key="youtube-key")
        client._get = MagicMock(
            side_effect=YouTubeAPIError(
                "Quota exceeded",
                upstream_status_code=403,
            )
        )

        with self.assertRaises(YouTubeAPIError):
            client.fetch_most_popular_videos(
                category_ids=["27"],
                region_code="US",
            )


class IdeaCronServiceTestCase(APITestCase):
    def setUp(self):
        self.first_category = Category.objects.create(
            name="First Category",
            slug="first-category",
            default_regions=["US"],
            is_active=True,
        )
        self.second_category = Category.objects.create(
            name="Second Category",
            slug="second-category",
            default_regions=["US"],
            is_active=True,
        )
        Category.objects.create(
            name="Inactive Category",
            slug="inactive-category",
            default_regions=["US"],
            is_active=False,
        )

    @override_settings(
        IDEA_CRON_MAX_ATTEMPTS=3,
        IDEA_CRON_RETRY_BASE_SECONDS=2,
        IDEA_CRON_RETRY_MAX_SECONDS=10,
    )
    @patch("ideas.services.time.sleep")
    @patch("ideas.services.refresh_ideas_for_category")
    def test_refreshes_categories_sequentially_and_retries_transient_errors(
        self,
        mock_refresh,
        mock_sleep,
    ):
        calls = []

        def refresh_side_effect(*, category_slug, region_code, limit):
            calls.append(category_slug)
            if category_slug == "first-category" and calls.count(category_slug) == 1:
                raise ValidationError({"llm_api": "HTTP 503 unavailable"})
            return [object()] * (1 if category_slug == "first-category" else 2)

        mock_refresh.side_effect = refresh_side_effect

        summary = refresh_all_ideas_for_cron(region_code="US", limit=5)

        self.assertEqual(
            calls,
            ["first-category", "first-category", "second-category"],
        )
        mock_sleep.assert_called_once_with(2)
        self.assertEqual(summary["total_categories"], 2)
        self.assertEqual(summary["succeeded"], 2)
        self.assertEqual(summary["failed"], 0)
        self.assertEqual(summary["results"][0]["attempts"], 2)
        self.assertEqual(summary["results"][1]["ideas_created"], 2)

    @override_settings(
        IDEA_CRON_MAX_ATTEMPTS=3,
        IDEA_CRON_RETRY_BASE_SECONDS=2,
        IDEA_CRON_RETRY_MAX_SECONDS=10,
    )
    @patch("ideas.services.time.sleep")
    @patch("ideas.services.refresh_ideas_for_category")
    def test_permanent_failure_is_not_retried_and_preserves_active_ideas(
        self,
        mock_refresh,
        mock_sleep,
    ):
        existing_idea = IdeaCandidate.objects.create(
            category=self.first_category,
            region_code="US",
            title="Existing idea",
            why_now="Existing evidence",
            audience_promise="Existing promise",
            suggested_format="Tutorial",
            is_active=True,
        )
        mock_refresh.side_effect = ValidationError(
            {"videos": "No usable YouTube videos found."}
        )

        summary = refresh_all_ideas_for_cron(region_code="US", limit=5)

        self.assertEqual(summary["failed"], 2)
        self.assertEqual(mock_refresh.call_count, 2)
        mock_sleep.assert_not_called()
        existing_idea.refresh_from_db()
        self.assertTrue(existing_idea.is_active)

    @override_settings(
        IDEA_CRON_MAX_ATTEMPTS=3,
        IDEA_CRON_RETRY_BASE_SECONDS=2,
        IDEA_CRON_RETRY_MAX_SECONDS=3,
    )
    @patch("ideas.services.time.sleep")
    @patch("ideas.services.refresh_ideas_for_category")
    def test_transient_failure_uses_bounded_backoff_then_continues(
        self,
        mock_refresh,
        mock_sleep,
    ):
        def refresh_side_effect(*, category_slug, region_code, limit):
            if category_slug == "first-category":
                raise ValidationError({"llm_api": "HTTP 503 unavailable"})
            return [object()]

        mock_refresh.side_effect = refresh_side_effect

        summary = refresh_all_ideas_for_cron(region_code="US", limit=5)

        self.assertEqual(summary["failed"], 1)
        self.assertEqual(summary["succeeded"], 1)
        self.assertEqual(summary["results"][0]["attempts"], 3)
        self.assertEqual(
            [sleep_call.args[0] for sleep_call in mock_sleep.call_args_list],
            [2, 3],
        )


class IdeaCronRefreshAPITestCase(APITestCase):
    @override_settings(IDEA_CRON_SECRET="cron-secret")
    def test_cron_endpoint_rejects_missing_secret(self):
        response = self.client.post(reverse("ideas-cron-refresh"), {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @override_settings(IDEA_CRON_SECRET="cron-secret")
    def test_cron_endpoint_rejects_incorrect_secret(self):
        response = self.client.post(
            reverse("ideas-cron-refresh"),
            {},
            format="json",
            HTTP_X_CRON_SECRET="wrong-secret",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @override_settings(IDEA_CRON_SECRET="")
    def test_cron_endpoint_reports_missing_server_configuration(self):
        response = self.client.post(
            reverse("ideas-cron-refresh"),
            {},
            format="json",
            HTTP_X_CRON_SECRET="cron-secret",
        )

        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)

    @override_settings(IDEA_CRON_SECRET="cron-secret")
    @patch("ideas.views.refresh_all_ideas_for_cron")
    def test_cron_endpoint_refreshes_all_categories(self, mock_refresh_all):
        mock_refresh_all.return_value = {
            "region_code": "US",
            "total_categories": 2,
            "succeeded": 2,
            "failed": 0,
            "results": [
                {
                    "category_slug": "first-category",
                    "status": "succeeded",
                    "attempts": 1,
                    "ideas_created": 10,
                    "error": "",
                },
                {
                    "category_slug": "second-category",
                    "status": "succeeded",
                    "attempts": 2,
                    "ideas_created": 10,
                    "error": "",
                },
            ],
        }

        response = self.client.post(
            reverse("ideas-cron-refresh"),
            {"region_code": "us", "limit": 10},
            format="json",
            HTTP_X_CRON_SECRET="cron-secret",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["succeeded"], 2)
        mock_refresh_all.assert_called_once_with(region_code="US", limit=10)

    @override_settings(IDEA_CRON_SECRET="cron-secret")
    @patch("ideas.views.refresh_all_ideas_for_cron")
    def test_cron_endpoint_returns_failure_status_for_partial_result(
        self,
        mock_refresh_all,
    ):
        mock_refresh_all.return_value = {
            "region_code": "US",
            "total_categories": 1,
            "succeeded": 0,
            "failed": 1,
            "results": [
                {
                    "category_slug": "failed-category",
                    "status": "failed",
                    "attempts": 3,
                    "ideas_created": 0,
                    "error": "Provider unavailable",
                }
            ],
        }

        response = self.client.post(
            reverse("ideas-cron-refresh"),
            {},
            format="json",
            HTTP_X_CRON_SECRET="cron-secret",
        )

        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(response.data["data"]["failed"], 1)


class IdeasAPITestCase(APITestCase):
    def setUp(self):
        # A Creator-tier user is at the top of the cumulative hierarchy
        # (Creator > Pro > Starter), so they can exercise every endpoint.
        self.user = User.objects.create_user(
            username="creator",
            email="creator@example.com",
            password="secret123",
        )
        creator_group, _ = Group.objects.get_or_create(name="Creator Users")
        self.user.groups.add(creator_group)
        self.client.force_authenticate(user=self.user)

        self.category = Category.objects.create(
            name="AI & Automation",
            slug="ai-automation",
            youtube_category_ids=["28"],
            youtube_category_titles=["Science & Technology"],
            search_keywords=["ai tools", "chatgpt"],
            negative_keywords=["iphone"],
            default_regions=["US"],
        )
        self.idea = IdeaCandidate.objects.create(
            category=self.category,
            region_code="US",
            title="I Tested 7 AI Tools That Save Creators Time",
            why_now="AI workflow videos are gaining strong recent engagement.",
            audience_promise="Help creators find practical tools they can use immediately.",
            suggested_format="Test / comparison",
            difficulty=IdeaCandidate.Difficulty.MEDIUM,
            freshness=IdeaCandidate.Freshness.HIGH,
            trend_score=86,
            source_signal="Based on recent YouTube trend signals",
            source_video_count=12,
            evidence_video_ids=["abc123", "xyz789"],
            risk_flags=[],
        )

    def test_list_trending_ideas(self):
        url = reverse("ideas-trending")
        response = self.client.get(
            url,
            {"category_slug": "ai-automation", "region_code": "US"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["message"], "trending ideas retrieved successfully")
        self.assertEqual(len(response.data["data"]), 1)
        self.assertEqual(response.data["data"][0]["title"], self.idea.title)

    def test_retrieve_idea_returns_real_selected_title(self):
        response = self.client.get(
            reverse("ideas-detail", kwargs={"idea_id": self.idea.id})
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["id"], self.idea.id)
        self.assertEqual(response.data["data"]["title"], self.idea.title)

    def test_retrieve_idea_rejects_missing_or_inactive_idea(self):
        self.idea.is_active = False
        self.idea.save(update_fields=["is_active", "updated_at"])

        response = self.client.get(
            reverse("ideas-detail", kwargs={"idea_id": self.idea.id})
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_idea_post_preflight_allows_frontend_preview_origins(self):
        url = reverse("ideas-youtube-intent")
        origins = (
            "http://localhost:5173",
            "https://id-preview-123.lovable.app",
            "https://creator-intent-git-main.vercel.app",
        )

        for origin in origins:
            with self.subTest(origin=origin):
                response = self.client.options(
                    url,
                    HTTP_ORIGIN=origin,
                    HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
                    HTTP_ACCESS_CONTROL_REQUEST_HEADERS="authorization,content-type",
                )

                self.assertEqual(response.status_code, status.HTTP_200_OK)
                self.assertEqual(response["Access-Control-Allow-Origin"], origin)

    def test_list_trending_ideas_invalid_category(self):
        url = reverse("ideas-trending")
        response = self.client.get(
            url,
            {"category_slug": "missing-category", "region_code": "US"},
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_list_ideas_compatibility_endpoint_accepts_region_alias(self):
        second_category = Category.objects.create(
            name="Creator Economy",
            slug="creator-economy",
            default_regions=["US"],
        )
        top_idea = IdeaCandidate.objects.create(
            category=second_category,
            region_code="US",
            title="The Creator Business Model Growing Fastest This Year",
            why_now="Creator business breakdowns are drawing recent interest.",
            audience_promise="Show creators which business model is gaining traction.",
            suggested_format="Analysis",
            difficulty=IdeaCandidate.Difficulty.MEDIUM,
            freshness=IdeaCandidate.Freshness.HIGH,
            trend_score=95,
            source_signal="Based on recent creator economy signals",
            source_video_count=8,
        )

        response = self.client.get(
            reverse("ideas-list"),
            {"region": "US", "limit": 1},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["data"]), 1)
        self.assertEqual(response.data["data"][0]["title"], top_idea.title)

    def test_list_ideas_rejects_conflicting_region_parameters(self):
        response = self.client.get(
            reverse("ideas-list"),
            {"region": "US", "region_code": "GB"},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"]["code"], "validation_error")

    @patch("ideas.views.generate_youtube_intent_task.apply_async")
    def test_research_youtube_intent_starts_background_job(self, mock_research_task):
        mock_research_task.return_value = MagicMock(id="research-task-1")
        url = reverse("ideas-youtube-intent")

        response = self.client.post(
            url,
            {
                "idea": "5 AI tools that can replace your assistant",
                "region_code": "US",
                "language_code": "en",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(
            response.data["message"],
            "youtube intent research started",
        )
        job = ContentPackageJob.objects.get(id=response.data["data"]["id"])
        self.assertEqual(job.job_type, ContentPackageJob.JobType.RESEARCH)
        self.assertEqual(job.celery_task_id, "research-task-1")
        self.assertEqual(
            job.request_payload["idea"],
            "5 AI tools that can replace your assistant",
        )
        self.assertEqual(job.request_payload["max_results"], 5)
        mock_research_task.assert_called_once_with(args=[str(job.id)], retry=False)

    def test_research_youtube_intent_requires_valid_idea(self):
        url = reverse("ideas-youtube-intent")

        response = self.client.post(
            url,
            {"idea": "ai"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("ideas.services.TextGenerationClient")
    @patch("ideas.services.YouTubeClient")
    @patch("ideas.services.YouTubeSuggestClient")
    def test_youtube_intent_uses_search_suggestions(
        self,
        mock_suggest_client_class,
        mock_youtube_client_class,
        mock_text_client_class,
    ):
        mock_text_client_class.return_value.generate_json.return_value = {
            "viewer_intent": (
                "Creators want to understand how AI agents move a real content task "
                "from research to a finished draft."
            ),
            "content_type": "beginner creator-workflow demonstration",
            "title_patterns": [
                "How [topic] Moves from [input] to [result]",
                "[topic] Explained Through One Real [workflow]",
                "Build Your First [topic] for [audience]",
            ],
            "emotional_angles": [
                "confidence to build a first working agent",
                "clarity about what happens between workflow steps",
                "relief from manually moving research into drafts",
            ],
            "thumbnail_subjects": [
                "creator arranging connected AI agent task cards",
                "automated research task passing into a draft",
                "finished video package produced by an agent workflow",
            ],
            "seo_keywords": [
                "ai agents for creators",
                "ai agent workflow tutorial",
                "creator automation agents",
            ],
        }
        mock_suggest_client_class.return_value.fetch_suggestions.return_value = [
            "ai agents for beginners",
            "ai agents tutorial",
            "ai agents explained",
        ]
        youtube_client = mock_youtube_client_class.return_value
        youtube_client.search_videos_by_query.return_value = [
            {"video_id": "video-1"},
        ]
        youtube_client.fetch_videos_by_ids.return_value = [
            {
                "id": "video-1",
                "snippet": {
                    "title": "How AI Agents Work",
                    "description": "A practical AI agent guide.",
                    "tags": ["ai agents"],
                },
                "statistics": {"viewCount": "1000", "likeCount": "100"},
            }
        ]

        result = research_youtube_intent_for_idea(
            idea="AI agents explained for creators",
            region_code="US",
            language_code="en",
        )

        mock_suggest_client_class.return_value.fetch_suggestions.assert_called_once_with(
            query="ai agents explained creators",
            region_code="US",
            language_code="en",
        )
        self.assertEqual(
            result["search_suggestions"],
            [
                "ai agents for beginners",
                "ai agents tutorial",
                "ai agents explained",
            ],
        )
        self.assertEqual(result["seo_keywords"][0], "ai agents for creators")
        self.assertIn("research to a finished draft", result["viewer_intent"])
        self.assertEqual(
            result["content_type"],
            "beginner creator-workflow demonstration",
        )
        self.assertEqual(
            result["thumbnail_subjects"],
            [
                "creator arranging connected AI agent task cards",
                "automated research task passing into a draft",
                "finished video package produced by an agent workflow",
            ],
        )

    @patch("ideas.youtube_suggest_client.urllib.request.urlopen")
    def test_youtube_suggest_client_parses_firefox_response(self, mock_urlopen):
        response = MagicMock()
        response.read.return_value = (
            b'["ai agents", ["ai agents tutorial", "ai agents explained", '
            b'"ai agents for beginners"], [], {}]'
        )
        mock_urlopen.return_value.__enter__.return_value = response

        suggestions = YouTubeSuggestClient().fetch_suggestions(
            query="ai agents",
            region_code="US",
            language_code="en",
        )

        self.assertEqual(
            suggestions,
            [
                "ai agents tutorial",
                "ai agents explained",
                "ai agents for beginners",
            ],
        )

    @patch("ideas.youtube_suggest_client.urllib.request.urlopen")
    def test_youtube_suggest_failure_does_not_break_intent(self, mock_urlopen):
        mock_urlopen.side_effect = TimeoutError("suggest service timed out")

        suggestions = YouTubeSuggestClient().fetch_suggestions(query="ai agents")

        self.assertEqual(suggestions, [])

    @override_settings(
        CLOUDINARY_CLOUD_NAME="demo-cloud",
        CLOUDINARY_API_KEY="cloudinary-key",
        CLOUDINARY_API_SECRET="cloudinary-secret",
    )
    @patch("ideas.openai_image_client.cloudinary.uploader.upload")
    def test_generated_thumbnail_uploads_to_cloudinary(self, mock_upload):
        mock_upload.return_value = {
            "secure_url": (
                "https://res.cloudinary.com/demo-cloud/image/upload/"
                "creatorintent/generated_thumbnails/test.png"
            ),
            "public_id": "creatorintent/generated_thumbnails/test",
        }
        client = OpenAIImageClient(api_key="openai-key")

        result = client._upload_image(
            image_base64="aW1hZ2UtYnl0ZXM=",
            filename_prefix="AI agents thumbnail",
            output_format="png",
        )

        self.assertEqual(
            result["url"],
            (
                "https://res.cloudinary.com/demo-cloud/image/upload/"
                "creatorintent/generated_thumbnails/test.png"
            ),
        )
        self.assertEqual(
            result["public_id"],
            "creatorintent/generated_thumbnails/test",
        )
        uploaded_file = mock_upload.call_args.args[0]
        self.assertEqual(uploaded_file.getvalue(), b"image-bytes")
        self.assertTrue(
            mock_upload.call_args.kwargs["public_id"].startswith(
                "creatorintent/generated_thumbnails/AI-agents-thumbnail-"
            )
        )

    @override_settings(
        CLOUDINARY_CLOUD_NAME="",
        CLOUDINARY_API_KEY="",
        CLOUDINARY_API_SECRET="",
    )
    def test_thumbnail_generation_requires_cloudinary_credentials(self):
        with self.assertRaises(ValidationError) as context:
            OpenAIImageClient(api_key="openai-key")

        self.assertIn("cloudinary", context.exception.detail)

    def test_prepare_thumbnail_from_youtube_intent(self):
        url = reverse("ideas-thumbnail-preparation")

        response = self.client.post(
            url,
            {
                "idea": "5 AI tools that can replace your assistant",
                "youtube_intent": {
                    "viewer_intent": "people want AI tools that save time and automate work",
                    "content_type": "listicle / tool recommendation",
                    "title_patterns": [
                        "Best [topic]",
                        "[topic] that save time",
                        "[topic] that replace work",
                    ],
                    "emotional_angles": [
                        "shock",
                        "fear of falling behind",
                        "productivity gain",
                    ],
                    "thumbnail_subjects": [
                        "creator comparing five automation results",
                        "five tool outputs arranged as result cards",
                        "repetitive task stack reduced to one workflow",
                    ],
                    "seo_keywords": [
                        "ai tools",
                        "ai productivity tools",
                        "best ai tools",
                    ],
                },
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["message"],
            "thumbnail preparation generated successfully",
        )
        self.assertEqual(len(response.data["data"]["hook_cards"]), 3)
        self.assertIn(
            "shock",
            [card["angle"] for card in response.data["data"]["hook_cards"]],
        )
        self.assertEqual(
            response.data["data"]["image_preparation"]["uses_google_search"],
            False,
        )
        self.assertEqual(
            response.data["data"]["image_preparation"]["all_non_creator_subjects_generated_by_ai"],
            True,
        )
        self.assertEqual(
            response.data["data"]["image_preparation"]["ask_user_for_own_image"],
            True,
        )
        self.assertEqual(
            response.data["data"]["subject_plan"][0]["source"],
            "ai_generate",
        )
        self.assertEqual(
            response.data["data"]["subject_plan"][1]["source"],
            "ai_generate",
        )
        self.assertEqual(
            response.data["data"]["creator_image"]["source"],
            "profile_or_upload",
        )

    @patch("ideas.views.generate_content_package_task.apply_async")
    def test_generate_content_package(self, mock_generate_content_package):
        mock_generate_content_package.return_value = {
            "thumbnail": {
                "url": "https://res.cloudinary.com/demo/image/upload/test.png",
                "public_id": "creatorintent/generated_thumbnails/test",
                "model": "gpt-image-2",
                "size": "1536x1024",
                "quality": "low",
                "selected_hook": {
                    "id": "shock",
                    "angle": "shock",
                    "thumbnail_text": "This Changed Everything",
                },
                "used_subjects": [],
            },
            "seo": {
                "title": "5 AI Tools That Can Replace Your Assistant",
                "description": "AI tools that save time.",
                "tags": ["ai tools"],
                "hashtags": ["#AITools"],
                "keywords": ["ai tools"],
            },
            "script": {
                "format": "creator_talking_guide",
                "audience_goal": "Choose AI tools that save meaningful time.",
                "core_message": "Choose tools based on workflow needs.",
                "opening": {
                    "viewer_need": "Know which AI tools are worth trying.",
                    "hook_guidance": "Start with the cost of repetitive work.",
                    "promise": "Show where each tool is genuinely useful.",
                },
                "sections": [
                    {
                        "heading": "Start with the workflow",
                        "viewer_question": "Which work should I automate?",
                        "talking_points": ["Identify repetitive creator tasks."],
                        "proof_or_example": "Walk through one supported workflow.",
                        "retention_bridge": "Move to the first tool category.",
                    }
                ],
                "closing": {
                    "key_takeaway": "Choose tools that solve a measured problem.",
                    "call_to_action": "Ask viewers which task wastes their time.",
                },
                "delivery_notes": ["Use concrete examples."],
                "facts_to_verify": [],
                "estimated_duration_minutes": 8,
            },
            "edit_options": [
                "Change thumbnail text",
                "Use my face",
                "Regenerate with stronger emotion",
                "Replace background",
            ],
        }
        mock_generate_content_package.return_value = MagicMock(id="task-1")
        youtube_intent = {
            "viewer_intent": "people want AI tools that save time and automate work",
            "content_type": "listicle / tool recommendation",
            "title_patterns": ["Best [topic]"],
            "emotional_angles": ["shock"],
            "thumbnail_subjects": ["creator comparing five automation results"],
            "seo_keywords": ["ai tools"],
        }
        selected_hook = {
            "id": "shock",
            "angle": "shock",
            "thumbnail_text": "This Changed Everything",
        }
        subject_plan = [
            {
                "type": "human",
                "role": "supporting_subject",
                "description": "creator comparing five automation results",
                "source": "ai_generate",
                "ai_prompt": "Generate a creator comparing five automation results.",
            }
        ]
        url = reverse("ideas-generate-package")

        response = self.client.post(
            url,
            {
                "idea": "5 AI tools that can replace your assistant",
                "youtube_intent": youtube_intent,
                "selected_hook": selected_hook,
                "subject_plan": subject_plan,
                "creator_image_choice": {
                    "use_profile_image": False,
                    "uploaded_image_id": None,
                    "skip_creator_image": True,
                },
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(
            response.data["message"],
            "content package generation started",
        )
        self.assertEqual(response.data["data"]["status"], "pending")
        job = ContentPackageJob.objects.get(id=response.data["data"]["id"])
        self.assertEqual(job.user, self.user)
        self.assertEqual(job.celery_task_id, "task-1")
        mock_generate_content_package.assert_called_once_with(
            args=[str(job.id)],
            retry=False,
        )

    def test_prepare_thumbnail_requires_youtube_intent_shape(self):
        url = reverse("ideas-thumbnail-preparation")

        response = self.client.post(
            url,
            {
                "idea": "5 AI tools that can replace your assistant",
                "youtube_intent": {
                    "viewer_intent": "people want AI tools",
                },
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_script_guide_falls_back_when_ai_output_is_missing(self):
        script = normalize_script_guide(
            script=None,
            idea="5 AI tools that can replace your assistant",
            youtube_intent={
                "viewer_intent": "find AI tools that save time without wasting money",
            },
        )

        self.assertEqual(script["format"], "creator_talking_guide")
        self.assertEqual(
            script["audience_goal"],
            "find AI tools that save time without wasting money",
        )
        self.assertGreaterEqual(len(script["sections"]), 3)
        self.assertEqual(script["estimated_duration_minutes"], 8)

    @patch("ideas.services.OpenAIImageClient")
    @patch("ideas.services.TextGenerationClient")
    def test_package_generation_does_not_request_or_return_script(
        self,
        mock_text_client_class,
        mock_image_client_class,
    ):
        mock_text_client_class.return_value.generate_json.return_value = {
            "thumbnail_prompt": "A creator dashboard with exact text SAVE HOURS",
            "seo": {
                "title": "5 AI Tools That Save Creators Time",
                "description": "Find practical AI tools.",
                "tags": ["ai tools"],
                "hashtags": ["#AITools"],
                "keywords": ["ai tools for creators"],
            },
            "edit_options": [
                "Change thumbnail text",
                "Use my face",
                "Regenerate with stronger emotion",
                "Replace background",
            ],
        }
        mock_image_client_class.return_value.generate_thumbnail.return_value = {
            "url": "https://example.com/thumbnail.png",
            "public_id": "thumbnail-id",
            "model": "gpt-image-2",
            "size": "1536x1024",
            "quality": "low",
        }

        result = generate_content_package(
            idea="5 AI tools that can replace your assistant",
            youtube_intent={
                "viewer_intent": "Creators want tools that save time.",
                "content_type": "Tool comparison",
                "seo_keywords": ["ai tools for creators"],
            },
            selected_hook={
                "id": "result",
                "angle": "result",
                "thumbnail_text": "SAVE HOURS",
            },
            subject_plan=[{"description": "Creator reviewing an automation dashboard"}],
        )

        self.assertNotIn("script", result)
        system_prompt = mock_text_client_class.return_value.generate_json.call_args.kwargs[
            "system_prompt"
        ]
        self.assertNotIn("script rules", system_prompt)

    @patch("ideas.services.TextGenerationClient")
    def test_script_generation_is_a_separate_llm_call(self, mock_text_client_class):
        mock_text_client_class.return_value.generate_json.return_value = {
            "format": "creator_talking_guide",
            "audience_goal": "Choose useful AI tools.",
            "core_message": "Automate measured workflow problems.",
            "opening": {},
            "sections": [],
            "closing": {},
            "delivery_notes": [],
            "facts_to_verify": [],
            "estimated_duration_minutes": 8,
        }

        result = generate_script_guide(
            idea="5 AI tools that can replace your assistant",
            youtube_intent={
                "viewer_intent": "Creators want tools that save time.",
                "content_type": "Tool comparison",
            },
            seo={"title": "5 AI Tools That Save Creators Time"},
        )

        self.assertEqual(result["format"], "creator_talking_guide")
        self.assertEqual(result["core_message"], "Automate measured workflow problems.")

    def test_validate_generated_ideas_rejects_vague_titles(self):
        clusters = [
            {
                "cluster_key": "chatgpt",
                "cluster_title": "Chatgpt",
                "trend_score": 85,
                "evidence_video_ids": ["abc123", "xyz789"],
                "evidence_titles": [
                    "7 ChatGPT Tools I Actually Use",
                    "ChatGPT Workflows for Creators",
                ],
                "trend_reasons": [
                    "120,000 views per day",
                    "Matched keywords: chatgpt",
                ],
            }
        ]
        ideas = [
            {
                "title": "Exploring ChatGPT's Impact on Daily Life",
                "why_now": "ChatGPT has been gaining popularity.",
                "audience_promise": "Learn about ChatGPT.",
                "suggested_format": "Vlog",
                "difficulty": "MEDIUM",
                "freshness": "HIGH",
                "risk_flags": [],
                "evidence_video_ids": ["abc123"],
            }
        ]

        validated = validate_generated_ideas(
            ideas=ideas,
            clusters=clusters,
            region_code="US",
            limit=1,
        )

        self.assertEqual(len(validated), 0)
