from django.core.management.base import BaseCommand

from categories.models import Category


DEFAULT_REGIONS = ["US"]

CATEGORIES = [
    {
        "name": "AI & Automation",
        "slug": "ai-automation",
        "description": "AI tools, ChatGPT, agents, automation, prompts, workflows, and AI coding content.",
        "youtube_category_ids": ["28"],
        "youtube_category_titles": ["Science & Technology"],
        "search_keywords": [
            "ai tools",
            "chatgpt",
            "ai agents",
            "ai automation",
            "chatgpt automation",
            "ai workflow",
            "ai coding",
            "chatgpt prompts",
            "generative ai",
        ],
        "negative_keywords": [
            "iphone",
            "samsung",
            "laptop",
            "camera",
            "unboxing",
            "gadget review",
            "factory",
            "machine",
            "manufacturing",
            "molding",
            "3d printer",
        ],
    },
    {
        "name": "Tech & Gadgets",
        "slug": "tech-gadgets",
        "description": "Smartphones, laptops, gadgets, software reviews, apps, camera gear, and comparisons.",
        "youtube_category_ids": ["28"],
        "youtube_category_titles": ["Science & Technology"],
        "search_keywords": [
            "smartphone",
            "laptop",
            "gadgets",
            "app review",
            "software review",
            "camera gear",
            "comparison",
            "setup",
        ],
        "negative_keywords": [
            "chatgpt",
            "ai agent",
            "ai automation",
            "prompt engineering",
        ],
    },
    {
        "name": "Business & Startups",
        "slug": "business-startups",
        "description": "Business, startups, marketing, sales, freelancing, and entrepreneurship content.",
        "youtube_category_ids": ["27", "25"],
        "youtube_category_titles": ["Education", "News & Politics"],
        "search_keywords": [
            "business",
            "startup",
            "marketing",
            "sales",
            "freelancing",
            "entrepreneurship",
            "small business",
        ],
        "negative_keywords": [
            "get rich quick",
            "guaranteed income",
            "make money overnight",
        ],
    },
    {
        "name": "Money & Finance",
        "slug": "money-finance",
        "description": "Investing, budgeting, personal finance, side hustles, crypto, and money management.",
        "youtube_category_ids": ["27", "25"],
        "youtube_category_titles": ["Education", "News & Politics"],
        "search_keywords": [
            "investing",
            "budgeting",
            "personal finance",
            "side hustle",
            "crypto",
            "money management",
            "saving money",
        ],
        "negative_keywords": [
            "guaranteed profit",
            "risk free",
            "get rich quick",
            "financial advice",
        ],
    },
    {
        "name": "Education & Tutorials",
        "slug": "education-tutorials",
        "description": "Tutorials, how-to videos, beginner guides, online courses, learning, and explainers.",
        "youtube_category_ids": ["27"],
        "youtube_category_titles": ["Education"],
        "search_keywords": [
            "tutorial",
            "how to",
            "beginner guide",
            "online course",
            "learning",
            "explainer",
            "step by step",
        ],
        "negative_keywords": [
            "prank",
            "reaction",
            "drama",
        ],
    },
    {
        "name": "Productivity & Self Improvement",
        "slug": "productivity-self-improvement",
        "description": "Habits, discipline, focus, productivity tools, routines, and personal growth.",
        "youtube_category_ids": ["26", "27"],
        "youtube_category_titles": ["Howto & Style", "Education"],
        "search_keywords": [
            "habits",
            "discipline",
            "focus",
            "productivity tools",
            "routine",
            "self improvement",
            "time management",
        ],
        "negative_keywords": [
            "instant success",
            "life hack miracle",
            "guaranteed transformation",
        ],
    },
    {
        "name": "Gaming",
        "slug": "gaming",
        "description": "Gaming updates, gameplay, walkthroughs, esports, game reviews, and gaming commentary.",
        "youtube_category_ids": ["20"],
        "youtube_category_titles": ["Gaming"],
        "search_keywords": [
            "gaming",
            "game updates",
            "walkthrough",
            "esports",
            "gameplay",
            "game review",
            "new game",
        ],
        "negative_keywords": [
            "casino",
            "gambling",
            "betting",
        ],
    },
    {
        "name": "Fitness & Health",
        "slug": "fitness-health",
        "description": "Fitness, workouts, weight loss, nutrition, healthy habits, and body transformation content.",
        "youtube_category_ids": ["17", "26"],
        "youtube_category_titles": ["Sports", "Howto & Style"],
        "search_keywords": [
            "fitness",
            "workout",
            "weight loss",
            "nutrition",
            "health habits",
            "body transformation",
            "home workout",
        ],
        "negative_keywords": [
            "medical cure",
            "guaranteed weight loss",
            "miracle diet",
            "disease treatment",
        ],
    },
    {
        "name": "Lifestyle & Vlogs",
        "slug": "lifestyle-vlogs",
        "description": "Vlogs, daily routines, creator life, lifestyle, personal stories, and behind-the-scenes content.",
        "youtube_category_ids": ["22"],
        "youtube_category_titles": ["People & Blogs"],
        "search_keywords": [
            "vlog",
            "daily routine",
            "creator life",
            "lifestyle",
            "personal story",
            "behind the scenes",
            "day in the life",
        ],
        "negative_keywords": [
            "celebrity gossip",
            "drama",
            "scandal",
        ],
    },
    {
        "name": "Travel & Food",
        "slug": "travel-food",
        "description": "Travel guides, food reviews, tourism, city guides, restaurants, and culture content.",
        "youtube_category_ids": ["19", "26"],
        "youtube_category_titles": ["Travel & Events", "Howto & Style"],
        "search_keywords": [
            "travel guide",
            "food review",
            "tourism",
            "city guide",
            "restaurants",
            "culture",
            "street food",
        ],
        "negative_keywords": [
            "fake travel",
            "dangerous stunt",
            "illegal",
        ],
    },
    {
        "name": "News & Commentary",
        "slug": "news-commentary",
        "description": "Current events, explainers, commentary, reactions, pop culture, and internet culture.",
        "youtube_category_ids": ["25", "24"],
        "youtube_category_titles": ["News & Politics", "Entertainment"],
        "search_keywords": [
            "current events",
            "explainer",
            "commentary",
            "reaction",
            "pop culture",
            "internet culture",
            "news analysis",
        ],
        "negative_keywords": [
            "conspiracy",
            "fake news",
            "unverified rumor",
        ],
    },
    {
        "name": "Beauty & Fashion",
        "slug": "beauty-fashion",
        "description": "Skincare, makeup, fashion, grooming, style tips, product routines, and beauty reviews.",
        "youtube_category_ids": ["26"],
        "youtube_category_titles": ["Howto & Style"],
        "search_keywords": [
            "skincare",
            "makeup",
            "fashion",
            "grooming",
            "style tips",
            "product routine",
            "beauty review",
        ],
        "negative_keywords": [
            "miracle cure",
            "guaranteed skin fix",
            "unsafe product",
        ],
    },
]


class Command(BaseCommand):
    help = "Seed the 12 creator-facing categories with YouTube category mappings."

    def handle(self, *args, **options):
        created_count = 0
        updated_count = 0

        for category_data in CATEGORIES:
            defaults = {
                **category_data,
                "default_regions": DEFAULT_REGIONS,
                "is_active": True,
            }
            slug = defaults.pop("slug")
            category, created = Category.objects.update_or_create(
                slug=slug,
                defaults=defaults,
            )

            if created:
                created_count += 1
                self.stdout.write(self.style.SUCCESS(f"Created: {category.name}"))
            else:
                updated_count += 1
                self.stdout.write(self.style.WARNING(f"Updated: {category.name}"))

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded categories successfully. Created: {created_count}, updated: {updated_count}."
            )
        )
