# YouTube Packaging Studio - API Documentation

## Overview

A Django REST Framework API backend for an AI-Powered YouTube Packaging Studio. It helps YouTube content creators generate SEO metadata, trending video ideas, and thumbnail concepts using Groq LLM and OpenAI DALL-E.

**Base URL:** `https://api.creatorintent.com/api/`

**Authentication:** 
* **JSON Web Token (JWT) Authentication** is required for all data endpoints (Categories and Ideas).
* Requests to data endpoints must include the following header: `Authorization: Bearer <access_token>`
* Public endpoints (authentication not required) are marked with `(Public)`.

---

## Endpoints

| # | Method | Endpoint | Description |
|---|--------|----------|-------------|
| 1 | `GET` | `auth/google/auth-url/` | Get Google login URL (Public) |
| 2 | `GET` | `auth/google/callback/` | Google login callback (Public) |
| 3 | `POST` | `auth/reviewer-login/` | App Store Reviewer Login (Public) |
| 4 | `GET/PATCH/DELETE` | `auth/profile/` | Manage User Profile (Authenticated) |
| 5 | `GET` | `categories/` | List all categories (Authenticated) |
| 6 | `POST` | `categories/` | Create a category (Authenticated) |
| 7 | `GET` | `categories/<id>/` | Get category by ID (Authenticated) |
| 8 | `PUT` | `categories/<id>/` | Update category (Authenticated) |
| 9 | `DELETE` | `categories/<id>/` | Delete category (Authenticated) |
| 10 | `GET` | `ideas/trending/` | Get trending ideas (Authenticated) |
| 11 | `POST` | `ideas/refresh/` | Refresh ideas for a category (Authenticated) |
| 12 | `POST` | `ideas/youtube-intent/` | Research YouTube intent (Authenticated) |
| 13 | `POST` | `ideas/thumbnail-preparation/` | Prepare thumbnail hooks (Authenticated) |
| 14 | `POST` | `ideas/generate-package/` | Generate final content package (Authenticated) |

---

## 1. GET `categories/`

List all active categories.

**Request:** No body.

**Response (200):**

```json
[
  {
    "id": 1,
    "name": "AI & Automation",
    "slug": "ai-automation",
    "description": "AI tools and automation workflows",
    "youtube_category_ids": ["28"],
    "youtube_category_titles": ["Science & Technology"],
    "search_keywords": ["ai", "chatgpt", "automation"],
    "negative_keywords": ["scam", "spam"],
    "default_regions": ["US", "GB"],
    "is_active": true
  }
]
```

---

## 2. POST `categories/`

Create a new category.

**Request:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Category name (max 100, unique) |
| `slug` | string | Yes | URL slug (max 120, unique) |
| `description` | string | No | Category description |
| `youtube_category_ids` | string[] | No | YouTube category IDs |
| `youtube_category_titles` | string[] | No | YouTube category names |
| `search_keywords` | string[] | No | Keywords to search for trending videos |
| `negative_keywords` | string[] | No | Keywords to exclude |
| `default_regions` | string[] | No | Supported region codes |
| `is_active` | boolean | No | Active status (default: true) |

```json
{
  "name": "AI & Automation",
  "slug": "ai-automation",
  "description": "AI tools and automation workflows",
  "youtube_category_ids": ["28"],
  "youtube_category_titles": ["Science & Technology"],
  "search_keywords": ["ai", "chatgpt", "automation"],
  "negative_keywords": ["scam", "spam"],
  "default_regions": ["US", "GB"],
  "is_active": true
}
```

**Response (201):**

```json
{
  "message": "category created successfully",
  "data": {
    "id": 1,
    "name": "AI & Automation",
    "slug": "ai-automation",
    "description": "AI tools and automation workflows",
    "youtube_category_ids": ["28"],
    "youtube_category_titles": ["Science & Technology"],
    "search_keywords": ["ai", "chatgpt", "automation"],
    "negative_keywords": ["scam", "spam"],
    "default_regions": ["US", "GB"],
    "is_active": true
  }
}
```

**Error (500):**

```json
{
  "message": "Failed to create category due to an internal server error.",
  "detail": "..."
}
```

---

## 3. GET `categories/<id>/`

Retrieve a single category by its ID.

**Response (200):**

```json
{
  "id": 1,
  "name": "AI & Automation",
  "slug": "ai-automation",
  "description": "AI tools and automation workflows",
  "youtube_category_ids": ["28"],
  "youtube_category_titles": ["Science & Technology"],
  "search_keywords": ["ai", "chatgpt", "automation"],
  "negative_keywords": ["scam", "spam"],
  "default_regions": ["US", "GB"],
  "is_active": true
}
```

**Error (404):**

```json
{
  "detail": "Category not found."
}
```

---

## 4. PUT `categories/<id>/`

Update an existing category. Partial updates are allowed.

**Request:**

```json
{
  "name": "Updated Name",
  "description": "Updated description"
}
```

**Response (200):**

```json
{
  "message": "category updated successfully",
  "data": {
    "id": 1,
    "name": "Updated Name",
    "slug": "ai-automation",
    "description": "Updated description",
    "youtube_category_ids": ["28"],
    "youtube_category_titles": ["Science & Technology"],
    "search_keywords": ["ai", "chatgpt", "automation"],
    "negative_keywords": ["scam", "spam"],
    "default_regions": ["US", "GB"],
    "is_active": true
  }
}
```

**Error (500):**

```json
{
  "message": "Failed to update category due to an internal server error.",
  "detail": "..."
}
```

---

## 5. DELETE `categories/<id>/`

Delete a category by its ID.

**Response (200):**

```json
{
  "message": "category deleted successfully"
}
```

**Error (500):**

```json
{
  "message": "Failed to delete category due to an internal server error.",
  "detail": "..."
}
```

---

## 6. GET `ideas/trending/`

Retrieve active trending ideas for a category.

**Query Parameters:**

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `category_slug` | string | Yes | — | Category slug |
| `region_code` | string | No | `"US"` | Region code |
| `limit` | integer | No | `10` | Max ideas to return (1-20) |

**Example:** `GET /api/ideas/trending/?category_slug=ai-automation&region_code=US&limit=5`

**Response (200):**

```json
{
  "message": "trending ideas retrieved successfully",
  "data": [
    {
      "id": 1,
      "category_id": 1,
      "batch_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "region_code": "US",
      "title": "I Tested 5 AI Agents That Can Automate Creator Workflows",
      "why_now": "Recent US YouTube videos show measurable traction: 15,000 views per day; 5.20% engagement rate.",
      "audience_promise": "Help viewers understand which ai automation ideas are practical enough to try now.",
      "suggested_format": "Test / workflow",
      "difficulty": "MEDIUM",
      "freshness": "HIGH",
      "trend_score": 78,
      "source_signal": "Based on 5 recent US YouTube trend signals",
      "source_video_count": 120,
      "evidence_video_ids": ["dQw4w9WgXcQ", "abc123def45"],
      "risk_flags": [],
      "generated_at": "2026-07-11T10:30:00Z",
      "expires_at": "2026-07-11T22:30:00Z"
    }
  ]
}
```

**Idea Candidate Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `id` | integer | Unique ID |
| `category_id` | integer | Parent category ID |
| `batch_id` | UUID | Batch grouping ID |
| `region_code` | string | Region code |
| `title` | string | Video idea title |
| `why_now` | string | Why this idea is trending now |
| `audience_promise` | string | Value proposition for viewers |
| `suggested_format` | string | Recommended video format |
| `difficulty` | string | `EASY`, `MEDIUM`, or `HARD` |
| `freshness` | string | `LOW`, `MEDIUM`, or `HIGH` |
| `trend_score` | integer | Trend score 0-100 |
| `source_signal` | string | Description of trend evidence |
| `source_video_count` | integer | Number of source videos analyzed |
| `evidence_video_ids` | string[] | YouTube video IDs used as evidence |
| `risk_flags` | string[] | Potential risks |
| `generated_at` | datetime | When the idea was generated |
| `expires_at` | datetime | When the idea expires |

---

## 7. POST `ideas/refresh/`

Refresh trending ideas for a category by fetching new YouTube data and generating new ideas via Groq LLM.

**Request:**

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `category_slug` | string | Yes | — | Category slug |
| `region_code` | string | No | `"US"` | Region code |
| `limit` | integer | No | `10` | Max ideas (1-10) |

```json
{
  "category_slug": "ai-automation",
  "region_code": "US",
  "limit": 10
}
```

**Response (201):** Same shape as the trending ideas response.

```json
{
  "message": "trending ideas refreshed successfully",
  "data": [...]
}
```

**Error (400):**

```json
{
  "videos": ["No usable YouTube videos found for this category and region."]
}
```

**Error (500):**

```json
{
  "message": "Failed to refresh ideas due to an internal server error.",
  "detail": "..."
}
```

---

## 8. POST `ideas/youtube-intent/`

Research YouTube search intent for a specific video idea. Analyzes YouTube search results and extracts viewer intent, content type, title patterns, emotional angles, thumbnail subjects, and SEO keywords.

**Request:**

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `idea` | string | Yes | — | Video idea (min 5 chars) |
| `region_code` | string | No | `"US"` | Region code |
| `language_code` | string | No | `"en"` | Language code |
| `max_results` | integer | No | `10` | Max YouTube results (5-20) |

```json
{
  "idea": "I Tested 5 AI Agents That Can Automate Creator Workflows",
  "region_code": "US",
  "language_code": "en",
  "max_results": 10
}
```

**Response (200):**

```json
{
  "message": "youtube intent research generated successfully",
  "data": {
    "viewer_intent": "people want the best ai agent options and practical reasons to use them",
    "content_type": "listicle / tool recommendation",
    "title_patterns": ["Best [topic]", "Top [number] [topic]", "I tested [topic]"],
    "emotional_angles": ["shock", "curiosity gap", "productivity gain"],
    "thumbnail_subjects": ["shocked person at laptop", "AI robot assistant", "software dashboard on laptop"],
    "seo_keywords": ["ai agents", "chatgpt", "automation", "creator tools", "productivity"]
  }
}
```

**Intent Response Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `viewer_intent` | string | What viewers are looking for |
| `content_type` | string | Detected content type (e.g., tutorial, listicle, comparison) |
| `title_patterns` | string[] | Effective title patterns for this idea |
| `emotional_angles` | string[] | Emotional angles for thumbnails |
| `thumbnail_subjects` | string[] | Suggested thumbnail visual subjects |
| `seo_keywords` | string[] | Extracted SEO keywords |

**Error (400):**

```json
{
  "youtube_results": ["No YouTube videos found for this idea."]
}
```

---

## 9. POST `ideas/thumbnail-preparation/`

Prepare thumbnail hook cards, subject plans, and image preparation instructions based on YouTube intent research.

**Request:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `idea` | string | Yes | Video idea (min 5 chars) |
| `youtube_intent` | object | Yes | Intent research output (see required fields below) |

The `youtube_intent` object must contain these fields:

- `viewer_intent` (string)
- `content_type` (string)
- `title_patterns` (string[])
- `emotional_angles` (string[])
- `thumbnail_subjects` (string[])
- `seo_keywords` (string[])

```json
{
  "idea": "I Tested 5 AI Agents That Can Automate Creator Workflows",
  "youtube_intent": {
    "viewer_intent": "people want the best ai agent options",
    "content_type": "listicle / tool recommendation",
    "title_patterns": ["Best [topic]"],
    "emotional_angles": ["shock", "curiosity gap"],
    "thumbnail_subjects": ["shocked person at laptop", "AI robot assistant"],
    "seo_keywords": ["ai agents", "chatgpt", "automation"]
  }
}
```

**Response (200):**

```json
{
  "message": "thumbnail preparation generated successfully",
  "data": {
    "hook_cards": [
      {
        "id": "curiosity",
        "angle": "curiosity",
        "label": "Curiosity",
        "thumbnail_text": "Nobody Explains This",
        "reason": "Opens a curiosity gap around the viewer need: people want the best ai agent options"
      },
      {
        "id": "shock",
        "angle": "shock",
        "label": "Shock",
        "thumbnail_text": "This Changed Everything",
        "reason": "Creates a strong surprise promise around the viewer need: people want the best ai agent options"
      },
      {
        "id": "fear",
        "angle": "fear",
        "label": "Fear",
        "thumbnail_text": "Don't Miss This",
        "reason": "Uses risk or mistake tension around the viewer need: people want the best ai agent options"
      }
    ],
    "subject_plan": [
      {
        "type": "human",
        "role": "supporting_subject",
        "description": "shocked person at laptop",
        "count": 1,
        "source": "ai_generate",
        "ai_prompt": "Generate a photorealistic shocked person at laptop for a YouTube thumbnail about I Tested 5 AI Agents... Clear facial expression, dramatic high contrast lighting, real camera look, clean composition, no text."
      },
      {
        "type": "object",
        "role": "supporting_subject",
        "description": "AI robot assistant",
        "count": 1,
        "source": "ai_generate",
        "ai_prompt": "Generate a photorealistic object/scene of AI robot assistant for a YouTube thumbnail about... High contrast, clear shape, realistic detail, clean composition, no text."
      }
    ],
    "image_preparation": {
      "uses_google_search": false,
      "all_non_creator_subjects_generated_by_ai": true,
      "ask_user_for_own_image": true,
      "ai_subject_prompts": ["...", "..."]
    },
    "creator_image": {
      "ask_user_for_own_image": true,
      "source": "profile_or_upload",
      "question": "Do you want to use your own image in the thumbnail?"
    }
  }
}
```

---

## 10. POST `ideas/generate-package/`

Generate the final content package including a DALL-E thumbnail, SEO metadata, and edit options.

**Request:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `idea` | string | Yes | Video idea (min 5 chars) |
| `youtube_intent` | object | Yes | Intent research output |
| `selected_hook` | object | Yes | Selected hook card with `id`, `angle`, `thumbnail_text` |
| `subject_plan` | object[] | Yes | Subject plan array (non-empty) |
| `creator_image_choice` | object | No | User's own image preference |

```json
{
  "idea": "I Tested 5 AI Agents That Can Automate Creator Workflows",
  "youtube_intent": {
    "viewer_intent": "people want the best ai agent options",
    "content_type": "listicle / tool recommendation",
    "title_patterns": ["Best [topic]"],
    "emotional_angles": ["shock", "curiosity gap"],
    "thumbnail_subjects": ["shocked person at laptop", "AI robot assistant"],
    "seo_keywords": ["ai agents", "chatgpt", "automation"]
  },
  "selected_hook": {
    "id": "curiosity",
    "angle": "curiosity",
    "thumbnail_text": "Nobody Explains This"
  },
  "subject_plan": [
    {
      "type": "human",
      "role": "supporting_subject",
      "description": "shocked person at laptop",
      "count": 1,
      "source": "ai_generate",
      "ai_prompt": "..."
    }
  ],
  "creator_image_choice": {
    "use_own_image": true,
    "image_url": "https://example.com/my-photo.jpg"
  }
}
```

**Response (201):**

```json
{
  "message": "content package generated successfully",
  "data": {
    "thumbnail": {
      "url": "https://oaidalleapiprodscus.blob.core.windows.net/...",
      "model": "dall-e-3",
      "size": "1792x1024",
      "quality": "hd",
      "selected_hook": {
        "id": "curiosity",
        "angle": "curiosity",
        "thumbnail_text": "Nobody Explains This"
      },
      "prompt": "Create a photorealistic 16:9 YouTube thumbnail. Video idea: I Tested 5 AI Agents... Viewer intent: people want the best ai agent options... Main visual subjects: shocked person at laptop, AI robot assistant... Render this exact thumbnail text inside the image: Nobody Explains This. Dramatic high contrast lighting...",
      "used_subjects": [
        {
          "type": "human",
          "role": "supporting_subject",
          "description": "shocked person at laptop",
          "count": 1,
          "source": "ai_generate",
          "ai_prompt": "..."
        }
      ]
    },
    "seo": {
      "title": "I Tested 5 AI Agents That Can Automate Creator Workflows",
      "description": "I Tested 5 AI Agents That Can Automate Creator Workflows\n\npeople want the best ai agent options and practical reasons to use them",
      "tags": ["ai agents", "chatgpt", "automation", "creator tools", "productivity"],
      "hashtags": ["#aiagents", "#chatgpt", "#automation"],
      "keywords": ["ai agents", "chatgpt", "automation", "creator tools", "productivity"]
    },
    "edit_options": [
      "Change thumbnail text",
      "Use my face",
      "Regenerate with stronger emotion",
      "Replace background"
    ]
  }
}
```

---

## External Integrations

| Service | Purpose | Client Module |
|---------|---------|---------------|
| YouTube Data API v3 | Fetch trending videos, search results | `youtube_client.py` |
| Groq LLM | Generate video ideas, intent analysis, package plans | `groq_client.py` |
| OpenAI DALL-E 3 | Generate thumbnail images | `openai_image_client.py` |

---

## Workflow

The typical API usage follows this sequence:

1. **Create Category** - `POST categories/`
2. **Refresh Ideas** - `POST ideas/refresh/` (fetches YouTube data, generates ideas via Groq)
3. **Get Trending Ideas** - `GET ideas/trending/` (list generated ideas)
4. **Research Intent** - `POST ideas/youtube-intent/` (analyze a specific idea)
5. **Prepare Thumbnail** - `POST ideas/thumbnail-preparation/` (generate hook cards and subject plans)
6. **Generate Package** - `POST ideas/generate-package/` (create final thumbnail + SEO + edit options)
