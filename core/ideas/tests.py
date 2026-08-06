from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from categories.models import Category
from .models import IdeaCandidate
from .services import validate_generated_ideas

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
                "url": "/media/generated_thumbnails/test.png",
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
            "/media/generated_thumbnails/test.png",
        )
        self.assertEqual(
            response.data["data"]["seo"]["title"],
            "5 AI Tools That Can Replace Your Assistant",
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
