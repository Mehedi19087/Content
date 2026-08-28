# YouTube Packaging Studio - API Documentation

## Overview

A Django REST Framework API backend for an AI-Powered YouTube Packaging Studio. It helps YouTube content creators generate SEO metadata, trending video ideas, and thumbnail concepts using DeepSeek and OpenAI image generation.

**Base URL:** `https://api.creatorintent.com/api/`

**Authentication:** 
* **JSON Web Token (JWT) Authentication** is required for all data endpoints (Categories and Ideas).
* Requests to data endpoints must include the following header: `Authorization: Bearer <access_token>`
* Public endpoints (authentication not required) are marked with `(Public)`.
* The internal idea cron endpoint does not accept user JWTs; it requires `X-Cron-Secret`.

---

## Endpoints

| # | Method | Endpoint | Description |
|---|--------|----------|-------------|
| 1 | `GET` | `auth/google/auth-url/` | Get Google login URL (Public) |
| 2 | `GET` | `auth/google/callback/` | Google login callback (Public) |
| 3 | `POST` | `auth/reviewer-login/` | App Store Reviewer Login (Public) |
| 4 | `POST` | `auth/token/refresh/` | Exchange a refresh token for a new access token (Public) |
| 5 | `POST` | `auth/token/verify/` | Check whether a JWT is valid (Public) |
| 6 | `GET/PATCH/DELETE` | `auth/profile/` | Manage User Profile (Authenticated) |
| 7 | `GET` | `categories/` | List all categories (Authenticated) |
| 8 | `POST` | `categories/` | Create a category (Authenticated) |
| 9 | `GET` | `categories/<id>/` | Get category by ID (Authenticated) |
| 10 | `PUT` | `categories/<id>/` | Update category (Authenticated) |
| 11 | `DELETE` | `categories/<id>/` | Delete category (Authenticated) |
| 12 | `GET` | `ideas/` | Get global or category-filtered trending ideas (Authenticated) |
| 13 | `GET` | `ideas/trending/` | Backward-compatible trending ideas URL (Authenticated) |
| 14 | `POST` | `internal/ideas/refresh/` | Enqueue a background refresh of every active category (Cron secret) |
| 15 | `POST` | `ideas/youtube-intent/` | Research YouTube intent (Authenticated) |
| 16 | `POST` | `ideas/thumbnail-preparation/` | Prepare thumbnail hooks (Authenticated) |
| 17 | `POST` | `ideas/generate-package/` | Start content-package generation (Authenticated) |
| 18 | `GET` | `ideas/generation-jobs/<id>/` | Get package-generation status (Authenticated) |
| 19 | `GET` | `billing/plans/` | List purchasable plans (Authenticated) |
| 20 | `POST` | `billing/checkout/` | Get Lemon Squeezy hosted checkout URL (Authenticated) |
| 21 | `GET` | `billing/status/` | Get current user's subscription status (Authenticated) |
| 22 | `POST` | `billing/portal/` | Get Lemon Squeezy customer portal URL (Authenticated) |
| 23 | `POST` | `billing/cancel/` | Cancel subscription at period end (Authenticated) |
| 24 | `POST` | `billing/webhook/` | Lemon Squeezy webhook receiver (Public) |

---

## Token lifecycle

Google login returns both `access` and `refresh`. Send the access token in the
`Authorization: Bearer <access_token>` header for authenticated requests. When
an API request returns `401`, exchange the stored refresh token for a new access
token and retry the original request once.

### POST `auth/token/refresh/`

```json
{
  "refresh": "<refresh_token>"
}
```

Successful response (`200`):

```json
{
  "access": "<new_access_token>"
}
```

### POST `auth/token/verify/`

```json
{
  "token": "<access_or_refresh_token>"
}
```

Successful response (`200`):

```json
{
  "valid": true
}
```

DRF-generated errors retain their original fields and also include a stable
`error` object with `status`, `code`, `message`, and `details` fields.

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

## 6. GET `ideas/`

Retrieve active trending ideas across all active categories or filter by a
category. `ideas/trending/` remains available as an alias.

**Query Parameters:**

| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `category_slug` | string | No | — | Optional category slug |
| `region_code` | string | No | `"US"` | Region code |
| `region` | string | No | `"US"` | Alias for `region_code` used by the web client |
| `limit` | integer | No | `10` | Max ideas to return (1-20) |

**Web-client example:** `GET /api/ideas/?region=US&limit=10`

**Category-filtered example:**
`GET /api/ideas/trending/?category_slug=ai-automation&region_code=US&limit=5`

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

## 7. POST `internal/ideas/refresh/`

Internal scheduled endpoint. It validates the cron secret and enqueues a Celery
background job that refreshes every active category enabled for the requested
region. The HTTP request returns immediately so short-lived external cron
services never time out; the worker runs the refresh outside the request cycle.
DeepSeek is attempted first and Groq is the fallback. Transient failures receive
bounded retries; permanent failures do not block later categories. Existing ideas
remain active for any failed category.

**Authentication header:**

```text
X-Cron-Secret: <IDEA_CRON_SECRET>
```

**Request:**

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `region_code` | string | No | `"US"` | Region code |
| `limit` | integer | No | `10` | Ideas per category (1-10) |

```json
{
  "region_code": "US",
  "limit": 10
}
```

An empty JSON object (`{}`) uses the defaults.

**Response (202):**

```json
{
  "message": "scheduled idea refresh started",
  "data": {
    "region_code": "US",
    "limit": 10,
    "task_id": "5e05eb9f-0e6a-4a2b-8f0d-1f1c1c1c1c1c"
  }
}
```

The endpoint returns `503` when the message broker is unreachable and the
background job could not be scheduled.

The Celery task `ideas.refresh_all_ideas` executes the refresh. It requires a
running worker with the same `CELERY_BROKER_URL` as the web service.

Required environment variables and retry defaults:

```env
IDEA_CRON_SECRET=<long-random-secret>
IDEA_CRON_MAX_ATTEMPTS=3
IDEA_CRON_RETRY_BASE_SECONDS=5
IDEA_CRON_RETRY_MAX_SECONDS=30
IDEA_EXPIRY_HOURS=80
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
    "viewer_intent": "Creators want proof of which AI agents can complete real workflow steps before choosing one.",
    "content_type": "hands-on creator workflow comparison",
    "title_patterns": ["I Tested [number] [topic] for [workflow]", "[topic]: Which One Actually [result]?", "[number] [topic] Ranked by [constraint]"],
    "emotional_angles": ["skepticism about exaggerated automation claims", "relief from repetitive creator work", "confidence in choosing one practical agent"],
    "thumbnail_subjects": ["creator comparing five agent workflow results", "research task transforming into a finished video brief", "five distinct automation result cards"],
    "seo_keywords": ["ai agents", "chatgpt", "automation", "creator tools", "productivity"]
  }
}
```

**Intent Response Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `viewer_intent` | string | Title-specific outcome, question, or tension supported by relevant evidence |
| `content_type` | string | Precise format inferred for this exact title and evidence |
| `title_patterns` | string[] | Evidence-grounded reusable structures for this idea |
| `emotional_angles` | string[] | Title-specific viewer motivations or tensions |
| `thumbnail_subjects` | string[] | Title-specific visual subjects generated from the idea and research |
| `seo_keywords` | string[] | Relevant search phrases grounded in the title, suggestions, titles, and tags |

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
    "thumbnail_subjects": ["creator comparing five agent workflow results", "research task transforming into a finished video brief"],
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
        "description": "creator comparing five agent workflow results",
        "count": 1,
        "source": "ai_generate",
        "ai_prompt": "Generate a photorealistic creator comparing five agent workflow results for a YouTube thumbnail about I Tested 5 AI Agents... Clear facial expression, dramatic high contrast lighting, real camera look, clean composition, no text."
      },
      {
        "type": "object",
        "role": "supporting_subject",
        "description": "research task transforming into a finished video brief",
        "count": 1,
        "source": "ai_generate",
        "ai_prompt": "Generate a photorealistic object/scene of a research task transforming into a finished video brief for a YouTube thumbnail about... High contrast, clear shape, realistic detail, clean composition, no text."
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

Start background generation of the final content package, including an OpenAI
thumbnail, SEO metadata, and edit options.

Available to every paid tier. One monthly package slot is reserved when the
job is accepted. A successful job consumes the slot; a failed, timed-out, or
undispatched job refunds it. Monthly limits are Starter 10, Pro 25, and Ultra
45, and reset on the first day of each UTC calendar month.

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
    "thumbnail_subjects": ["creator comparing five agent workflow results", "research task transforming into a finished video brief"],
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
      "description": "creator comparing five agent workflow results",
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

**Response (202):**

```json
{
  "message": "content package generation started",
  "data": {
    "id": "2ec63e12-8e34-4f65-b9b7-c6d7e7017780",
    "status": "pending",
    "stage": "queued",
    "quota_status": "reserved",
    "result": null,
    "error_code": "",
    "error_message": "",
    "created_at": "2026-08-25T10:00:00Z",
    "started_at": null,
    "finished_at": null
  }
}
```

The frontend should poll `GET ideas/generation-jobs/{id}/` until the status is
`succeeded` or `failed`.

**Response (429):** The caller has no package generations remaining in the
current monthly period. The response includes `limit`, `used`, `remaining`,
and `period_end`.

## 10.1 GET `ideas/generation-jobs/{id}/`

Return the current state of a content-package generation job. Users can only
retrieve their own jobs.

**Completed response (200):**

```json
{
  "message": "content package generation status retrieved successfully",
  "data": {
    "id": "2ec63e12-8e34-4f65-b9b7-c6d7e7017780",
    "status": "succeeded",
    "stage": "completed",
    "result": {
    "thumbnail": {
      "url": "https://res.cloudinary.com/example/image/upload/v1/creatorintent/generated_thumbnails/example.png",
      "public_id": "creatorintent/generated_thumbnails/example",
      "model": "gpt-image-2",
      "size": "1536x1024",
      "quality": "low",
      "selected_hook": {
        "id": "curiosity",
        "angle": "curiosity",
        "thumbnail_text": "Nobody Explains This"
      },
      "prompt": "Create a photorealistic 16:9 YouTube thumbnail. Video idea: I Tested 5 AI Agents... Viewer intent: people want the best ai agent options... Main visual subjects: creator comparing five agent workflow results, research task transforming into a finished video brief... Render this exact thumbnail text inside the image: Nobody Explains This. Dramatic high contrast lighting...",
      "used_subjects": [
        {
          "type": "human",
          "role": "supporting_subject",
          "description": "creator comparing five agent workflow results",
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
    "script": {
      "format": "creator_talking_guide",
      "audience_goal": "Help creators understand which AI agents are practical.",
      "core_message": "Choose agents based on a real workflow problem.",
      "opening": {},
      "sections": [],
      "closing": {},
      "delivery_notes": [],
      "facts_to_verify": [],
      "estimated_duration_minutes": 8
    },
    "edit_options": [
      "Change thumbnail text",
      "Use my face",
      "Regenerate with stronger emotion",
      "Replace background"
    ]
    },
    "error_code": "",
    "error_message": "",
    "created_at": "2026-08-25T10:00:00Z",
    "started_at": "2026-08-25T10:00:01Z",
    "finished_at": "2026-08-25T10:01:20Z"
  }
}
```

---

## External Integrations

| Service | Purpose | Client Module |
|---------|---------|---------------|
| YouTube Data API v3 | Fetch trending videos, search results | `youtube_client.py` |
| DeepSeek | Primary text generation provider | `deepseek_client.py` |
| Groq | Backup text generation provider | `groq_client.py` |
| OpenAI Image API | Generate thumbnail images | `openai_image_client.py` |
| Cloudinary | Persist generated thumbnails and serve HTTPS URLs | `openai_image_client.py` |
| Redis | Celery message broker | Celery configuration |
| Celery | Execute package generation outside HTTP requests | `ideas/tasks.py` |
| Lemon Squeezy | Subscription billing, customer portal, webhooks | `billing/client.py` |

DeepSeek text generation requires `DEEPSEEK_API_KEY`. `DEEPSEEK_MODEL` defaults
to `deepseek-v4-flash`, and `DEEPSEEK_TIMEOUT_SECONDS` defaults to `60`.
If DeepSeek fails, the application retries once through Groq. The fallback requires
`GROQ_API_KEY`; `GROQ_MODEL` defaults to `openai/gpt-oss-120b`, and
`GROQ_TIMEOUT_SECONDS` defaults to `60`. GPT-OSS fallback requests use low
reasoning effort and a 2,048-token completion limit by default; override these
with `GROQ_REASONING_EFFORT` and `GROQ_MAX_COMPLETION_TOKENS` if needed. Short
HTTP 429 rate limits are retried once using Groq's requested wait time.

Interactive YouTube research is latency-optimized without changing other text
generation workflows: it tries Groq first, immediately falls back to DeepSeek on
failure or rate limiting, and then uses the existing evidence-derived result if both
providers fail. Research calls use `YOUTUBE_RESEARCH_HTTP_TIMEOUT_SECONDS`
(default `10`) for YouTube and suggestions, and
`YOUTUBE_RESEARCH_LLM_TIMEOUT_SECONDS` (default `25`) for each LLM provider.

Cloudinary thumbnail storage requires `CLOUDINARY_CLOUD_NAME`,
`CLOUDINARY_API_KEY`, and `CLOUDINARY_API_SECRET` in the backend environment.
`CLOUDINARY_TIMEOUT_SECONDS` defaults to `60`.

Background generation requires `CELERY_BROKER_URL`, normally a managed Redis
URL. The web and worker processes must use the same value. Optional worker limits
are `CELERY_TASK_SOFT_TIME_LIMIT` (default `420`) and
`CELERY_TASK_TIME_LIMIT` (default `450`). PostgreSQL stores job status and final
results; Redis is not used as permanent result storage. Jobs still pending or
processing after `CONTENT_PACKAGE_JOB_STALE_SECONDS` (default `600`) are marked
failed when their status is retrieved.

---

## Workflow

The typical API usage follows this sequence:

1. **Create Category** - `POST categories/`
2. **Scheduled Refresh** - cron calls `POST internal/ideas/refresh/` every 2-3 days
3. **Get Trending Ideas** - users call `GET ideas/trending/` (read-only)
4. **Research Intent** - `POST ideas/youtube-intent/` (analyze a specific idea)
5. **Prepare Thumbnail** - `POST ideas/thumbnail-preparation/` (generate hook cards and subject plans)
6. **Start Package Generation** - `POST ideas/generate-package/` (returns `202` and a job id)
7. **Poll Package Status** - `GET ideas/generation-jobs/{id}/` until `succeeded` or `failed`

---

## 11. Billing (Lemon Squeezy)

Entitlement is group-based: each Plan maps to a Django auth Group, and the user is added/removed from that Group by `billing.services.recompute_user_entitlement()` based on the state of their `Subscription` rows. Tiers are cumulative — a Creator-tier user unlocks all lower-tier features too.

| Tier (Group) | Unlocks |
|---|---|
| Free Users | `GET ideas/trending/` |
| Starter Users | + `POST ideas/youtube-intent/`, `POST ideas/generate-package/` (10/month) |
| Pro Users | + `POST ideas/thumbnail-preparation/`, all `youtube/*` endpoints (25 packages/month) |
| Ultra / Creator Users | Highest package allowance (45/month) |

Pro users receive 25 package generations per month. Package limits are also
returned by the plans API rather than being hard-coded by clients.

### 11.1 GET `billing/plans/`

List all active purchasable plans, ordered by `sort_order`.

**Response (200):**

```json
{
  "message": "plans retrieved successfully",
  "data": [
    {
      "id": 1,
      "slug": "starter",
      "name": "Starter",
      "description": "Generate fresh trending ideas and YouTube intent research.",
      "group": "Starter Users",
      "price_usd_cents": 999,
      "monthly_package_limit": 10,
      "interval": "month",
      "is_active": true,
      "sort_order": 1
    }
  ]
}
```

### 11.2 POST `billing/checkout/`

Returns a Lemon Squeezy hosted checkout URL. The user is redirected to LS to pay; LS redirects back to your success URL after payment, then sends a webhook so the backend grants the entitlement.

**Request:**

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `plan_slug` | string | Yes | — | Plan slug |
| `platform` | string | No | `"web"` | `web` or `mobile` (selects success redirect target) |

```json
{
  "plan_slug": "pro",
  "platform": "web"
}
```

**Response (200):**

```json
{
  "message": "checkout url generated successfully",
  "data": {
    "checkout_url": "https://checkout.lemonsqueezy.com/..."
  }
}
```

**Error (404):** Plan slug not found.
**Error (503):** `LEMON_SQUEEZY_API_KEY` missing.
**Error (502):** LS call failed.

### 11.3 GET `billing/status/`

Returns the caller's current subscription state. Always calls `recompute_user_entitlement()` first, so this endpoint self-heals any drift between LS and your database.

**Response (200):**

```json
{
  "message": "billing status retrieved successfully",
  "data": {
    "plan": "pro",
    "plan_name": "Pro",
    "group": "Pro Users",
    "status": "active",
    "current_period_end": "2026-08-31T10:00:00Z",
    "cancelled_at": null,
    "lemon_subscription_id": "sub_abc",
    "package_usage": {
      "limit": 25,
      "used": 7,
      "remaining": 18,
      "period_start": "2026-08-01",
      "period_end": "2026-09-01"
    }
  }
}
```

If the user has no paid subscription, `plan`, `plan_name`, `status`, `current_period_end`, `cancelled_at`, `lemon_subscription_id` are all `null`, and `group` is `"Free Users"`.

### 11.4 POST `billing/portal/`

Returns a one-time Lemon Squeezy customer portal URL the user can use to update their card or see invoices. No request body required.

**Response (200):**

```json
{
  "message": "portal url generated successfully",
  "data": {
    "portal_url": "https://app.lemonsqueezy.com/portal/..."
  }
}
```

**Error (404):** No subscription exists for this user.
**Error (503):** `LEMON_SQUEEZY_API_KEY` missing.

### 11.5 POST `billing/cancel/`

Cancels the user's subscription at period end. The user keeps their paid-tier access until `current_period_end` because `recompute_user_entitlement()` still treats a `CANCELLED` subscription with a future `current_period_end` as entitled. When LS later fires `subscription_expired` (after the period actually lapses), the backend flips the user back to `Free Users`.

**Response (200):**

```json
{
  "message": "subscription will cancel at period end",
  "cancelled_at": "2026-08-05T12:00:00Z",
  "current_period_end": "2026-08-31T10:00:00Z"
}
```

**Error (404):** No subscription exists for this user.

### 11.6 POST `billing/webhook/` (Public)

Receives Lemon Squeezy webhook events. This endpoint is **public** (no JWT) — security is provided by HMAC signature verification against `LEMON_SQUEEZY_WEBHOOK_SECRET`. The `X-Signature` header must match `HMAC-SHA256(body, secret)`. The same `event_id` is never applied twice (idempotency via the `WebhookEvent` table); replays return `200` with `status: "skipped"`.

Webhook URL to register in LS: `https://api.creatorintent.com/api/billing/webhook/`

**Handled event names:**

| Event name | Action |
|---|---|
| `subscription_created` | Upsert Subscription; recompute entitlement (add user to plan's group). |
| `subscription_updated` | Same; handles upgrade/downgrade via new `variant_id`. |
| `subscription_cancelled` | Mark `cancelled_at`; keep group until `current_period_end`. |
| `subscription_expired` | Mark status=expired; recompute → drop to `Free Users`. |
| `subscription_paused` / `subscription_resumed` | Set status accordingly and recompute. |
| `subscription_payment_success` | Refresh `current_period_end`; recompute. |
| `subscription_payment_failed` | Set status=`past_due`; recompute (user keeps access until period end). |
| `order_created` | Stored but treated as a no-op (subscriptions-only MVP). |

**Response (200):**

```json
{
  "message": "webhook received",
  "event_id": "evt_1",
  "status": "processed"
}
```

`status` is one of: `processed` (first delivery of a known event), `skipped` (replay of an already-seen `event_id`), `unknown` (event_name we don't handle — still stored to `WebhookEvent`), or `failed` (handler raised; the row's `error` field is populated and can be inspected in the admin).

**Error (400):** Signature invalid OR JSON malformed OR `event_id` missing.
