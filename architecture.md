# AI-Powered YouTube Packaging Studio

## 1. Project Overview & Product Goal
An AI-powered YouTube video packaging assistant for small and medium international creators making English content. The platform helps creators streamline the pre-publishing phase by generating SEO metadata and providing "Thumbnail Object Intelligence" to suggest exactly what visual elements should be in the thumbnail.

### Key Value Proposition
- **Fast Workflow**: Creators get professional SEO, title ideas, and thumbnail concepts quickly without hiring experts.
- **Thumbnail Object Intelligence**: The system tells the creator what visual objects should be inside the thumbnail based on the video idea, search intent, and psychological concepts (Result, Curiosity, Conflict).
- **Cost-Controlled Architecture**: Image generation (the most expensive step) is deferred until the very end, after text-based concepts are selected.

### MVP Features
1. Category selection
2. Trending idea generator (Background cached)
3. Custom idea input
4. SEO package generator (LLM + RAG)
5. Thumbnail text generator
6. Thumbnail object suggestion
7. 3 thumbnail concept cards
8. Face/Asset upload (Optional)
9. Final thumbnail generation
10. Usage limit / credit system

---

## 2. Technology Stack (MVP)
- **Backend Framework**: drf .
- **Primary Database**: PostgreSQL (Users, Subscriptions, Projects, Assets).
- **Caching Layer**: Redis (Used with RDB snapshots to cache daily trending ideas to avoid rate limits and reduce latency).
- **Vector Database (RAG)**: pgvector 
- **LLM Provider**: DeepSeek API with Groq fallback
- **Image Generation API**:OpenAI (DALL-E 3).
- **Asset Storage**: cloudinary.

---

## 3. Database Schema (PostgreSQL & Redis)

### Relational Database (PostgreSQL)

**1. `users` Table**
*   `id` (UUID, Primary Key)
*   `email` (String, Unique)
*   `password_hash` (String)
*   `subscription_tier` (Enum: 'FREE', 'STARTER', 'CREATOR') - *Default: 'FREE'*
*   `package_credits_remaining` (Integer) - *Default: 3*
*   `thumbnail_credits_remaining` (Integer) - *Default: 1*
*   `created_at` (Timestamp)
*   `updated_at` (Timestamp)

**2. `categories` Table**
*   `id` (UUID, Primary Key)
*   `name` (String) - *e.g., "AI / Tech", "Finance"*
*   `slug` (String, Unique)
*   `is_active` (Boolean) - *Default: true*
*   `created_at` (Timestamp)

**3. `projects` Table**
*   `id` (UUID, Primary Key)
*   `user_id` (UUID, Foreign Key -> `users.id`)
*   `category_id` (UUID, Foreign Key -> `categories.id`)
*   `video_idea` (String) - *The raw idea selected or typed by the user*
*   `seo_data` (JSONB) - *Stores: { main_keyword, search_intent, titles: [], recommended_title, description, tags, hashtags, hook }*
*   `concept_cards` (JSONB) - *Stores an array of the 3 concepts (Result, Curiosity, Conflict) with their text and object suggestions.*
*   `selected_concept_type` (String, Nullable) - *e.g., "Conflict"*
*   `final_thumbnail_url` (String, Nullable) - *S3 URL of the final generated image*
*   `status` (Enum: 'DRAFT', 'COMPLETED') - *Default: 'DRAFT'*
*   `created_at` (Timestamp)
*   `updated_at` (Timestamp)

**4. `assets` Table**
*   `id` (UUID, Primary Key)
*   `project_id` (UUID, Foreign Key -> `projects.id`)
*   `user_id` (UUID, Foreign Key -> `users.id`)
*   `asset_type` (Enum: 'USER_FACE', 'SCREENSHOT', 'BRAND_LOGO')
*   `file_url` (String) - *Secure S3 URL of the uploaded image*
*   `created_at` (Timestamp)

### Caching Strategy (Redis)
**Cache-Aside Pattern for Trending Ideas**
- **Persistence**: RDB (Snapshots) enabled.
- **Key Structure**: `category:{slug}:trending_ideas`
- **Value Structure**: JSON array of synthesized video ideas.
- **Workflow**: 
  1. A background Cron Job fetches YouTube API data every 24 hours.
  2. The Cron Job uses the LLM to synthesize the raw data into 10 clean video ideas.
  3. Saves the JSON string into Redis.
  4. When a user queries a category, the backend checks Redis first. If a Cache Miss occurs, it falls back to the live API/LLM chain, saves to Redis, and returns the data.

---

## 4. API Endpoints

*(Note: All protected endpoints require a Bearer JWT Token)*

### Auth & User Management
- **`POST /api/auth/register`** -> Create user account.
- **`POST /api/auth/login`** -> Authenticate and return token.
- **`GET /api/users/me`** -> Returns user profile and current credit balances.

### Categories & Trending Ideas
- **`GET /api/categories`**
  - **Action**: Returns all categories where `is_active = true`.
- **`GET /api/ideas/trending?category_id={id}`**
  - **Action**: Checks Redis cache for trending ideas for the specified category. Returns the 10 synthesized video topics instantly.
- **`POST /api/ideas/generate`**
  - **Payload**: `{ "custom_topic": "string" }`
  - **Action**: For users who want ideas outside the standard trending list. Calls the LLM live to generate custom video ideas based on their specific input. This is a synchronous call and bypasses the Redis cache.

### Core Workflow (The Project Pipeline)
- **`POST /api/projects/generate-package`**
  - **Payload**: `{ "category_id": "uuid", "video_idea": "custom or selected string" }`
  - **Action**: Deducts 1 package credit. Calls LLM + RAG to generate the SEO package and the 3 Thumbnail Concept Cards. Creates a new row in the `projects` table.
  - **Returns**: The newly created `Project` JSON object.
- **`GET /api/projects/:id`**
  - **Action**: Retrieves the full project details.
- **`PATCH /api/projects/:id`**
  - **Payload**: `{ "selected_concept_type": "Curiosity" }`
  - **Action**: Updates user choices on the project before final image generation.

### Asset Uploads
- **`POST /api/projects/:id/assets`**
  - **Payload**: Multipart/form-data (Image file), `{ "asset_type": "USER_FACE" }`
  - **Action**: Uploads image to AWS S3, saves secure URL to `assets` table linked to the project.
  - **Returns**: The uploaded asset record.

### Final Image Generation
- **`POST /api/projects/:id/generate-thumbnail`**
  - **Payload**: `{ "selected_concept_type": "Curiosity", "include_face_asset_id": "uuid" (optional) }`
  - **Action**: Deducts 1 thumbnail credit. Constructs an image generation prompt based on the chosen concept and object intelligence. Calls Image Generation API. Uploads result to S3. Updates `projects` table with the `final_thumbnail_url`.
  - **Returns**: `{ "final_thumbnail_url": "https://s3..." }`

### Dashboard & History
- **`GET /api/projects`**
  - **Action**: Returns a paginated list of the user's past projects, sorted by `created_at` descending.
