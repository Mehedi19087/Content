from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import override_settings
from django.urls import reverse
from rest_framework.exceptions import ValidationError
from rest_framework import status
from rest_framework.test import APITestCase

from categories.models import Category
from .models import IdeaCandidate
from .openai_image_client import OpenAIImageClient
from .services import (
    normalize_script_guide,
    research_youtube_intent_for_idea,
    validate_generated_ideas,
)
from .youtube_suggest_client import YouTubeSuggestClient

User = get_user_model()


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

    @patch("ideas.views.refresh_ideas_for_category")
    def test_refresh_ideas(self, mock_refresh_ideas_for_category):
        mock_refresh_ideas_for_category.return_value = [self.idea]
        url = reverse("ideas-refresh")

        response = self.client.post(
            url,
            {"category_slug": "ai-automation", "region_code": "US"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["message"], "trending ideas refreshed successfully")
        self.assertEqual(response.data["data"][0]["title"], self.idea.title)
        mock_refresh_ideas_for_category.assert_called_once_with(
            category_slug="ai-automation",
            region_code="US",
            limit=10,
        )

    @patch("ideas.views.research_youtube_intent_for_idea")
    def test_research_youtube_intent(self, mock_research_youtube_intent_for_idea):
        mock_research_youtube_intent_for_idea.return_value = {
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
                "shocked person at laptop",
                "AI robot assistant",
                "busy workspace",
            ],
            "seo_keywords": [
                "ai tools",
                "ai productivity tools",
                "best ai tools",
                "ai assistant",
                "automation tools",
            ],
            "search_suggestions": [
                "ai tools for content creators",
                "best ai tools for productivity",
            ],
        }
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

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["message"],
            "youtube intent research generated successfully",
        )
        self.assertEqual(
            response.data["data"]["viewer_intent"],
            "people want AI tools that save time and automate work",
        )
        self.assertEqual(
            response.data["data"]["thumbnail_subjects"],
            [
                "shocked person at laptop",
                "AI robot assistant",
                "busy workspace",
            ],
        )
        self.assertEqual(
            response.data["data"]["search_suggestions"],
            [
                "ai tools for content creators",
                "best ai tools for productivity",
            ],
        )
        mock_research_youtube_intent_for_idea.assert_called_once_with(
            idea="5 AI tools that can replace your assistant",
            region_code="US",
            language_code="en",
            max_results=10,
        )

    def test_research_youtube_intent_requires_valid_idea(self):
        url = reverse("ideas-youtube-intent")

        response = self.client.post(
            url,
            {"idea": "ai"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("ideas.services.YouTubeClient")
    @patch("ideas.services.YouTubeSuggestClient")
    def test_youtube_intent_uses_search_suggestions(
        self,
        mock_suggest_client_class,
        mock_youtube_client_class,
    ):
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
        self.assertEqual(result["seo_keywords"][0], "ai agents beginners")
        self.assertIn("ai agents tutorial", result["viewer_intent"])

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
                        "shocked person at laptop",
                        "AI robot assistant",
                        "busy workspace",
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

    @patch("ideas.views.generate_content_package")
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
        youtube_intent = {
            "viewer_intent": "people want AI tools that save time and automate work",
            "content_type": "listicle / tool recommendation",
            "title_patterns": ["Best [topic]"],
            "emotional_angles": ["shock"],
            "thumbnail_subjects": ["shocked person at laptop"],
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
                "description": "shocked person at laptop",
                "source": "ai_generate",
                "ai_prompt": "Generate a photorealistic shocked person at laptop.",
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

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            response.data["message"],
            "content package generated successfully",
        )
        self.assertEqual(
            response.data["data"]["thumbnail"]["url"],
            "https://res.cloudinary.com/demo/image/upload/test.png",
        )
        self.assertEqual(
            response.data["data"]["thumbnail"]["public_id"],
            "creatorintent/generated_thumbnails/test",
        )
        self.assertEqual(
            response.data["data"]["seo"]["title"],
            "5 AI Tools That Can Replace Your Assistant",
        )
        self.assertEqual(
            response.data["data"]["script"]["format"],
            "creator_talking_guide",
        )
        mock_generate_content_package.assert_called_once()

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
