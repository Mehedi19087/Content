# AI-Powered YouTube Packaging Studio - MVP

## 1. Product Goal
An AI-powered YouTube packaging assistant for small and medium international creators making English content.

Core workflow:
```text
Category -> Trending idea -> SEO package -> Thumbnail text -> Thumbnail object -> 3 concepts -> Final thumbnail
```

The unique feature is **Thumbnail Object Intelligence**: the system recommends the best visual object/subject for the thumbnail based on video idea, search intent, viewer promise, and emotion.

Example:
```text
Idea: How to grow on YouTube fast
Object: YouTube analytics graph
Concept: Result / Proof
Thumbnail text: 0 to 100K?
```

### MVP Features
1. Category selection
2. Trending idea generator
3. Custom idea input
4. SEO package generator
5. Thumbnail text generator
6. Thumbnail object suggestion
7. 3 concept cards: Result, Curiosity, Conflict
8. Optional face/asset upload
9. Final thumbnail generation
10. Usage limit / credit system
11. Project history/dashboard

Do not build in v1: advanced editor, YouTube analytics, A/B testing, auto publishing, full video generation.

---

## 2. Technology Stack
- **Backend**: Django REST Framework
- **Database**: PostgreSQL
- **RAG / Vector Search**: pgvector
- **Cache**: Redis
- **LLM**: Groq API
- **Image Generation**: OpenAI image API / DALL-E 3
- **Asset Storage**: Cloudinary
- **Auth**: JWT

---

## 3. Database Schema
For MVP, keep only 4 main tables:

```text
users, categories, projects, assets
```

### 1. `users`
- `id` UUID PK
- `email` string unique
- `password_hash` string
- `subscription_tier` enum: `FREE`, `STARTER`, `CREATOR`
- `package_credits_remaining` int
- `thumbnail_credits_remaining` int
- `created_at`, `updated_at`

### 2. `categories`
- `id` UUID PK
- `name` string
- `slug` string unique
- `is_active` boolean
- `created_at`, `updated_at`

Initial categories: AI / Tech, Business, Finance, Fitness, Education, Productivity, Gaming, Travel, News / Commentary, Product Reviews.

### 3. `projects`
- `id` UUID PK
- `user_id` UUID FK -> `users.id`
- `category_id` UUID FK -> `categories.id`
- `video_idea` text
- `seo_data` JSONB
- `thumbnail_object_data` JSONB
- `concept_cards` JSONB
- `selected_concept_type` string nullable
- `final_thumbnail_url` string nullable
- `status` enum: `DRAFT`, `PACKAGE_GENERATED`, `CONCEPT_SELECTED`, `THUMBNAIL_PROCESSING`, `COMPLETED`, `FAILED`
- `created_at`, `updated_at`

`seo_data` stores: main keyword, search intent, title options, recommended title, description, tags, hashtags, hook, thumbnail text options.

`thumbnail_object_data` stores: primary object, secondary object, optional face suggestion, best angle, emotion, reason.

`concept_cards` stores the 3 concepts: Result / Proof, Curiosity / Hidden, Conflict / Comparison.

### 4. `assets`
- `id` UUID PK
- `user_id` UUID FK -> `users.id`
- `project_id` UUID FK -> `projects.id`
- `asset_type` enum: `USER_FACE`, `SCREENSHOT`, `PRODUCT_IMAGE`, `RESULT_PROOF`, `LOGO`, `REFERENCE_IMAGE`
- `file_url` string
- `mime_type` string
- `file_size` int
- `created_at`, `updated_at`

---

## 4. Redis + RAG

### Redis Cache
Use Redis for trending idea cache.

```text
Key: category:{slug}:trending_ideas
Value: JSON array of 10 ideas
TTL: 24 hours
```

Workflow: cron fetches trend data -> LLM converts it into 10 ideas -> save to Redis -> API reads Redis first.

### RAG Collections
Use pgvector collections:

- `seo_knowledge`: keywords, title formulas, hooks, descriptions, tags
- `thumbnail_knowledge`: object mapping, emotion, layout, click psychology
- `trend_snapshots`: recent category-level trend context

---

## 5. Use Cases

### Use Case 1: Trending Ideas
User selects category -> backend checks Redis -> returns 10 ideas. On cache miss, backend uses trend data + LLM and stores the result in Redis.

### Use Case 2: Generate Package
User selects idea/custom idea -> backend checks package credit -> retrieves RAG context -> LLM generates `seo_data`, `thumbnail_object_data`, `concept_cards` -> validates JSON -> creates project -> deducts 1 package credit.

### Use Case 3: Upload Assets
User uploads face/screenshot/product image -> backend validates file -> uploads to Cloudinary -> saves asset row.

### Use Case 4: Generate Thumbnail
User selects concept -> backend checks thumbnail credit -> builds prompt from selected concept + assets -> calls image generation API -> stores final image in Cloudinary -> updates `final_thumbnail_url` -> deducts 1 thumbnail credit.

---

## 6. API Endpoints
All protected endpoints require JWT.

### Auth & User
- `POST /api/auth/register` -> Create account
- `POST /api/auth/login` -> Return JWT
- `GET /api/users/me` -> User profile + credit balance

### Categories & Ideas
- `GET /api/categories` -> Active categories
- `GET /api/ideas/trending?category_id={id}` -> Cached trending ideas
- `POST /api/ideas/generate`-> Live custom ideas from user topic

### Projects
- `POST /api/projects/generate-package` -> Create project and generate SEO + thumbnail strategy
- `GET /api/projects` -> Project history
- `GET /api/projects/{id}` -> Project details
- `PATCH /api/projects/{id}` -> Update selected concept

Generate package payload:
```json
{
  "category_id": "uuid",
  "video_idea": "Best AI tools for creators in 2026"
}
```

Patch project payload:
```json
{
  "selected_concept_type": "Curiosity / Hidden"
}
```

### Assets
- `POST /api/projects/{id}/assets` -> Upload face/screenshot/product image
- `GET /api/projects/{id}/assets` -> List project assets
- `DELETE /api/projects/{id}/assets/{asset_id}` -> Delete asset

### Final Thumbnail
- `POST /api/projects/{id}/generate-thumbnail` -> Generate final image and update project

Payload:
```json
{
  "selected_concept_type": "Curiosity / Hidden",
  "include_face_asset_id": "uuid"
}
```

Response:
```json
{
  "final_thumbnail_url": "https://..."
}
```

---

## 7. Backend Rules

### JSONB Rule
Use JSONB for MVP because SEO data and concept cards belong to one project and are read/written together.

Create separate tables later only for version history, analytics, CTR tracking, A/B testing, or detailed audit logs.

### LLM Validation Rule
Never save raw LLM output directly. Validate required fields, allowed concept types, title/thumbnail text difference, non-empty thumbnail object, arrays for tags/hashtags, and copyright-risk prompts.

### Cost Control Rule
Generate cheap text strategy first. Generate final image only after the user selects one concept.

---

## 8. MVP Build Order
1. Auth/user/credits
2. Categories
3. Trending ideas with Redis
4. Project package generation
5. RAG with pgvector
6. Asset upload to Cloudinary
7. Final thumbnail generation
8. Project dashboard/history
