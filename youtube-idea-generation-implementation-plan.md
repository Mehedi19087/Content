# YouTube Trend Idea Generation Implementation Plan

## 1. Product Goal

Build a reliable video idea generation system for international English-speaking creators.

The user problem:

```text
I know my niche, but I do not know what video to make next.
Which topics are actually trending in my niche, and what idea can I make without fake clickbait?
```

The product should not expose raw YouTube categories directly to users. YouTube official categories are backend filters. Users should choose creator-friendly niches.

Core product promise:

```text
Choose your niche -> see real trend-backed video opportunities -> generate SEO and thumbnail strategy
```

## 2. Architecture Principle

Use 3 layers:

```text
User-facing niche
    -> YouTube official category + keyword rules
        -> trend-scored video idea candidates
```

Example:

```text
User sees: AI & Automation
Backend uses:
- YouTube category: Science & Technology
- YouTube category ID: 28
- Keywords: ai tools, chatgpt, ai agents, automation
- Negative keywords: iphone, samsung, laptop, unboxing, gadget review
```

This keeps the UI simple and keeps the backend compatible with the YouTube Data API.

## 3. Official YouTube API Sources

Use these official YouTube Data API endpoints:

- `videoCategories.list`: fetch official category IDs/titles by region.
- `videos.list`: fetch most popular videos or full video stats by video IDs.
- `search.list`: search niche keywords and return candidate video IDs.

Official docs:

- https://developers.google.com/youtube/v3/docs/videoCategories/list
- https://developers.google.com/youtube/v3/docs/videos/list
- https://developers.google.com/youtube/v3/docs/search/list
- https://developers.google.com/youtube/v3/determine_quota_cost

Important quota rule:

```text
Do not call YouTube search live for every user request.
Run background refresh jobs, save snapshots, and serve cached results to users.
```

## 4. User-Facing Niches

Use these 12 niches for MVP.

| # | User Niche | YouTube Category Mapping | Topic / Keywords |
|---|---|---|---|
| 1 | AI & Automation | Science & Technology | ai tools, chatgpt, ai agents, automation, ai workflow, ai coding, prompts |
| 2 | Tech & Gadgets | Science & Technology | smartphones, laptops, gadgets, app reviews, software reviews, camera gear, comparisons |
| 3 | Business & Startups | Education / News & Politics | business, startup, marketing, sales, freelancing, entrepreneurship |
| 4 | Money & Finance | Education / News & Politics | investing, budgeting, personal finance, side hustle, crypto, money management |
| 5 | Education & Tutorials | Education | tutorials, how to, beginner guide, online course, learning, explainers |
| 6 | Productivity & Self Improvement | Howto & Style / Education | habits, discipline, focus, productivity tools, routines, self improvement |
| 7 | Gaming | Gaming | gaming, game updates, walkthrough, esports, gameplay, game reviews |
| 8 | Fitness & Health | Sports / Howto & Style | fitness, workout, weight loss, nutrition, health habits, body transformation |
| 9 | Lifestyle & Vlogs | People & Blogs | vlog, daily routine, creator life, lifestyle, personal stories, behind the scenes |
| 10 | Travel & Food | Travel & Events / Howto & Style | travel guide, food review, tourism, city guide, restaurants, culture |
| 11 | News & Commentary | News & Politics / Entertainment | current events, explainers, commentary, reactions, pop culture, internet culture |
| 12 | Beauty & Fashion | Howto & Style | skincare, makeup, fashion, grooming, style tips, product routines |

Recommended default official category IDs:

| YouTube Category | Category ID |
|---|---|
| Science & Technology | 28 |
| Education | 27 |
| News & Politics | 25 |
| Howto & Style | 26 |
| Gaming | 20 |
| Sports | 17 |
| People & Blogs | 22 |
| Travel & Events | 19 |
| Entertainment | 24 |

Still sync categories with `videoCategories.list` at startup or daily, because category availability can depend on region.

## 5. Target Regions

For MVP, start with only the United States:

```text
US
```

Reason:

```text
The US is the strongest default signal for international English YouTube trends.
```

Later, expand the UI to support:

```text
Global English, United Kingdom, Canada, Australia, India
```

## 6. Data Collection Flow

Run this as a background job every 6-12 hours.

-text
For each niche:
    For each target region:
        1. Fetch popular videos by official category
        2. Fetch search results by niche keywords
        3. Fetch full video stats with videos.list
        4. Normalize and deduplicate videos
        5. Score trend strength
        6. Cluster similar topics
        7. Generate creator-friendly video ideas
        8. Save trend snapshot
```

### Step 1: Fetch Popular Videos By Official Category

Use `videos.list` with `chart=mostPopular`.

Example for `AI & Automation` in the US:

```http
GET /youtube/v3/videos
  ?part=snippet,statistics,contentDetails
  &chart=mostPopular
  &regionCode=US
  &videoCategoryId=28
  &maxResults=50
```

This returns broad popular videos in `Science & Technology`.

Example data returned:

```json
{
  "id": "abc123",
  "snippet": {
    "title": "I Tested the New AI Coding Tool",
    "description": "Video description...",
    "publishedAt": "2026-07-04T10:00:00Z",
    "channelTitle": "Tech Channel",
    "categoryId": "28"
  },
  "statistics": {
    "viewCount": "245000",
    "likeCount": "12000",
    "commentCount": "900"
  },
  "contentDetails": {
    "duration": "PT12M40S"
  }
}
```

Purpose:

```text
Find broad category-level trend signals.
```

Problem:

```text
This is too broad by itself. Science & Technology can include AI, phones, laptops, space, and gadgets.
```

So Step 2 is needed.

### Step 2: Fetch Search Results By Niche Keywords

Use `search.list` for niche-specific keywords.

Example keyword list for `AI & Automation`:

```text
ai tools
chatgpt
ai agents
ai automation
ai workflow
ai coding
```

Example request:

```http
GET /youtube/v3/search
  ?part=snippet
  &q=ai tools
  &type=video
  &order=viewCount
  &publishedAfter=2026-06-28T00:00:00Z
  &regionCode=US
  &relevanceLanguage=en
  &videoCategoryId=28
  &maxResults=25
```

This returns candidate videos matching the keyword.

Example data returned:

```json
{
  "id": {
    "kind": "youtube#video",
    "videoId": "xyz789"
  },
  "snippet": {
    "title": "7 AI Tools I Actually Use Every Day",
    "description": "Video description...",
    "publishedAt": "2026-07-02T08:00:00Z",
    "channelTitle": "Creator Tools"
  }
}
```

Purpose:

```text
Find niche-specific videos that broad category search may miss.
```

Important:

```text
search.list usually gives candidate IDs and snippet data. It does not give all stats needed for trend scoring.
```

So Step 3 is needed.

### Step 3: Fetch Full Video Stats

Collect video IDs from Step 1 and Step 2.

Example:

```text
abc123, xyz789, def456
```

Then call `videos.list` by IDs:

```http
GET /youtube/v3/videos
  ?part=snippet,statistics,contentDetails
  &id=abc123,xyz789,def456
```

This returns complete video details:

```text
title
description
published date
channel
category
views
likes
comments
duration
thumbnail URLs
tags when available
```

Purpose:

```text
Make every candidate video scoreable using the same complete data shape.
```

### Step 4: Normalize And Deduplicate Videos

Normalize every video into your own internal shape.

Example internal object:

```json
{
  "video_id": "xyz789",
  "category_slug": "ai-automation",
  "region_code": "US",
  "title": "7 AI Tools I Actually Use Every Day",
  "description": "Video description...",
  "channel_title": "Creator Tools",
  "published_at": "2026-07-02T08:00:00Z",
  "view_count": 245000,
  "like_count": 12000,
  "comment_count": 900,
  "duration_seconds": 760,
  "youtube_category_id": "28",
  "matched_keywords": ["ai tools", "chatgpt"],
  "source_types": ["search", "most_popular"]
}
```

Deduplicate by `video_id`.

If a video appears from multiple sources, keep one record and merge the source data:

```text
source_types: ["search", "most_popular"]
matched_keywords: ["ai tools", "chatgpt"]
```

Purpose:

```text
Avoid counting the same video multiple times.
```

### Step 5: Score Trend Strength

Use code to calculate trend score before using the LLM.

Recommended scoring inputs:

```text
views per day
engagement rate
freshness
keyword match
source strength
multi-region presence
saturation penalty
negative keyword penalty
```

Example:

```text
views_per_day = view_count / max(days_since_published, 1)
engagement_rate = (like_count + comment_count) / max(view_count, 1)
```

Recommended score:

```text
trend_score =
    views_velocity_score
  + engagement_score
  + freshness_score
  + keyword_match_score
  + source_strength_score
  + multi_region_score
  - saturation_penalty
  - negative_keyword_penalty
```

Example output:

```json
{
  "video_id": "xyz789",
  "trend_score": 86,
  "trend_reasons": [
    "High views per day",
    "Strong comment activity",
    "Published within the last 7 days",
    "Matched ai tools and chatgpt keywords"
  ]
}
```

Purpose:

```text
Avoid fake trends. A 3-year-old viral video should not beat a fresh video gaining traction now.
```

### Step 6: Cluster Similar Topics

Now group videos that are about the same topic.

Example raw titles:

```text
7 AI Tools I Actually Use Every Day
Best AI Tools for Creators in 2026
I Tried 10 AI Productivity Apps
These AI Tools Saved Me 20 Hours
```

Cluster:

```text
AI productivity tools for creators
```

MVP clustering approach:

1. Clean title text.
2. Remove stop words.
3. Extract important phrases.
4. Group videos with overlapping phrases and keywords.
5. Use LLM only to name the cluster and summarize the pattern.

Later improvement:

```text
Use embeddings + pgvector for better semantic clustering.
```

Cluster output:

```json
{
  "cluster_key": "ai-productivity-tools",
  "cluster_title": "AI productivity tools for creators",
  "category_slug": "ai-automation",
  "region_code": "US",
  "trend_score": 86,
  "evidence_video_ids": ["xyz789", "abc123", "def456"],
  "evidence_titles": [
    "7 AI Tools I Actually Use Every Day",
    "Best AI Tools for Creators in 2026",
    "These AI Tools Saved Me 20 Hours"
  ]
}
```

Purpose:

```text
Turn many raw videos into a smaller number of real topic opportunities.
```

### Step 7: Generate Creator-Friendly Video Ideas

Use the LLM after scoring and clustering.

The LLM should not decide what is trending from zero. It should transform proven trend clusters into useful creator ideas.

LLM input:

```json
{
  "niche": "AI & Automation",
  "region": "US",
  "cluster_title": "AI productivity tools for creators",
  "trend_score": 86,
  "evidence_titles": [
    "7 AI Tools I Actually Use Every Day",
    "Best AI Tools for Creators in 2026",
    "These AI Tools Saved Me 20 Hours"
  ],
  "quality_rules": [
    "Do not copy existing video titles",
    "Do not create fake guarantees",
    "Do not use misleading clickbait",
    "Create practical video ideas a small creator can actually make"
  ]
}
```

LLM output:

```json
{
  "idea": "I Tested 7 AI Tools That Save Creators Time",
  "why_now": "Recent AI productivity tool videos are gaining strong views and engagement.",
  "audience_promise": "Help creators find practical tools they can use immediately.",
  "suggested_format": "Test / comparison",
  "difficulty": "Medium",
  "freshness": "High",
  "not_clickbait_rule": "Do not claim guaranteed income or impossible results.",
  "evidence_video_ids": ["xyz789", "abc123", "def456"]
}
```

Purpose:

```text
Return useful video opportunities, not copied titles.
```

### Step 8: Save Trend Snapshot

Save the final idea list for fast user access.

Example snapshot:

```json
{
  "niche": "AI & Automation",
  "region": "US",
  "updated_at": "2026-07-05T09:00:00Z",
  "source_video_count": 143,
  "ideas": [
    {
      "idea": "I Tested 7 AI Tools That Save Creators Time",
      "trend_score": 86,
      "freshness": "High",
      "difficulty": "Medium",
      "why_now": "AI productivity tool videos are gaining strong recent engagement.",
      "suggested_format": "Test / comparison",
      "audience_promise": "Help creators save time with practical AI tools.",
      "evidence_video_ids": ["xyz789", "abc123", "def456"]
    }
  ]
}
```

Also save this in Redis Later:

```text
Key: niche:{slug}:region:{region_code}:trend_snapshot
TTL: 6-12 hours
```

Purpose:

```text
Users get instant results without live YouTube API calls.
```

## 7. User-Facing API Response

When a user selects a niche, return clean idea cards.

Endpoint:

```http
GET /api/ideas/trending/?category_slug=ai-automation&region_code=US
```

Response:

```json
{
  "niche": {
    "name": "AI & Automation",
    "slug": "ai-automation"
  },
  "region": {
    "code": "US",
    "label": "United States"
  },
  "updated_at": "2026-07-05T09:00:00Z",
  "ideas": [
    {
      "id": "idea_uuid",
      "title": "I Tested 7 AI Tools That Save Creators Time",
      "trend_score": 86,
      "freshness": "High",
      "difficulty": "Medium",
      "why_now": "AI productivity tool videos are gaining strong recent engagement.",
      "audience_promise": "Help creators save time with practical AI tools.",
      "suggested_format": "Test / comparison",
      "source_signal": "Based on 3 high-performing recent videos",
      "risk_flags": []
    }
  ]
}
```

Do not show raw YouTube video links in MVP unless needed. Show enough evidence to build trust without encouraging copying.

## 8. Database Design

### `creator_niches`

User-facing categories.

```text
id UUID PK
name string
slug string unique
description text
youtube_category_ids JSONB
search_keywords JSONB
negative_keywords JSONB
default_regions JSONB
is_active boolean
created_at timestamp
updated_at timestamp
```

Example:

```json
{
  "name": "AI & Automation",
  "slug": "ai-automation",
  "youtube_category_ids": ["28"],
  "search_keywords": [
    "ai tools",
    "chatgpt",
    "ai agents",
    "automation",
    "ai workflow",
    "ai coding"
  ],
  "negative_keywords": [
    "iphone",
    "samsung",
    "laptop",
    "camera",
    "unboxing",
    "gadget review"
  ]
}
```

### `youtube_categories`

Official YouTube category cache.

```text
id UUID PK
youtube_category_id string
title string
region_code string
assignable boolean
raw_data JSONB
created_at timestamp
updated_at timestamp
```

### `source_videos`

Normalized videos collected from YouTube.

```text
id UUID PK
youtube_video_id string unique
niche_id UUID FK
region_code string
title text
description text
channel_title string
published_at timestamp
youtube_category_id string
view_count bigint
like_count bigint nullable
comment_count bigint nullable
duration_seconds int nullable
thumbnail_url text nullable
matched_keywords JSONB
source_types JSONB
trend_score int
trend_reasons JSONB
raw_data JSONB
collected_at timestamp
created_at timestamp
updated_at timestamp
```

### `trend_snapshots`

One saved result per niche and region refresh.

```text
id UUID PK
niche_id UUID FK
region_code string
status enum: PROCESSING, COMPLETED, FAILED
source_video_count int
cluster_count int
started_at timestamp
completed_at timestamp nullable
error_message text nullable
created_at timestamp
updated_at timestamp
```

### `idea_candidates`

Final trend-backed ideas users see.

```text
id UUID PK
trend_snapshot_id UUID FK
niche_id UUID FK
region_code string
title text
why_now text
audience_promise text
suggested_format string
difficulty enum: EASY, MEDIUM, HARD
freshness enum: LOW, MEDIUM, HIGH
trend_score int
source_signal text
evidence_video_ids JSONB
risk_flags JSONB
is_active boolean
created_at timestamp
updated_at timestamp
```

## 9. Backend Services

Recommended service modules:

```text
youtube_client.py
    sync_youtube_categories()
    fetch_most_popular_videos()
    search_videos_by_keyword()
    fetch_videos_by_ids()

trend_collection_service.py
    collect_niche_region_videos()
    normalize_youtube_video()
    deduplicate_videos()

trend_scoring_service.py
    calculate_video_trend_score()
    calculate_cluster_trend_score()

topic_clustering_service.py
    cluster_source_videos()
    summarize_cluster()

idea_generation_service.py
    generate_ideas_from_clusters()
    validate_idea_json()

trend_snapshot_service.py
    refresh_trend_snapshot()
    get_latest_snapshot()
```

## 10. Public API Endpoints

### Niches

```http
GET /api/niches
```

Returns active user-facing niches.

### Trending Ideas

```http
GET /api/ideas/trending/?category_slug=ai-automation&region_code=US
```

Returns latest cached idea candidates.

Rules:

- For the current two-table MVP, read active `IdeaCandidate` rows from PostgreSQL.
- Do not call YouTube live from this endpoint.
- If no ideas exist yet, return an empty list and let the refresh command/API create ideas.

### Admin Refresh

```http
POST /api/ideas/refresh/
```

Triggers a background refresh for selected niche and region.

Payload:

```json
{
  "category_slug": "ai-automation",
  "region_code": "US"
}
```

### Generate Package

Existing project endpoint:

```http
POST /api/projects/generate-package
```

Payload should support selected idea:

```json
{
  "niche_id": "uuid",
  "idea_candidate_id": "uuid",
  "video_idea": "I Tested 7 AI Tools That Save Creators Time"
}
```

## 11. Background Job Strategy

MVP:

```text
Django management command + cron
```

Command:

```bash
python manage.py refresh_ideas --region-code US
```

Later:

```text
Celery + Celery Beat + Redis
```

Refresh schedule:

```text
High-demand niches: every 6 hours
Normal niches: every 12 hours
Fallback full refresh: every 24 hours
```

Recommended first refresh order:

1. AI & Automation
2. Tech & Gadgets
3. Business & Startups
4. Money & Finance
5. Education & Tutorials
6. Productivity & Self Improvement
7. Gaming
8. News & Commentary
9. Fitness & Health
10. Travel & Food
11. Lifestyle & Vlogs
12. Beauty & Fashion

## 12. Quality And Anti-Clickbait Rules

Every generated idea must pass these rules:

```text
No fake income guarantee.
No fake health guarantee.
No "YouTube is hiding this" unless evidence exists.
No copying source video titles.
No exaggeration beyond the source signal.
No celebrity or brand claim without source evidence.
No "must watch before deleted" style manipulation.
```

Better idea style:

```text
I Tested 7 AI Tools That Save Creators Time
```

Bad idea style:

```text
This AI Tool Will Make You Rich Overnight
```

## 13. LLM Validation Rules

Never save raw LLM output directly.

Required fields:

```text
title
why_now
audience_promise
suggested_format
difficulty
freshness
not_clickbait_rule
evidence_video_ids
```

Validation:

- `title` must not be empty.
- `title` must not exactly match any source video title.
- `evidence_video_ids` must reference collected videos.
- `difficulty` must be one of `EASY`, `MEDIUM`, `HARD`.
- `freshness` must be one of `LOW`, `MEDIUM`, `HIGH`.
- `trend_score` must come from code, not the LLM.
- `risk_flags` must be present even if empty.

## 14. Build Order

### Phase 1: Niche Foundation

1. Create `creator_niches` model.
2. Seed the 12 user-facing niches.
3. Add YouTube category IDs, keywords, and negative keywords.
4. Create `GET /api/niches`.

### Phase 2: YouTube Client

1. Implement API client with timeout and retry handling.
2. Implement `videoCategories.list` sync.
3. Implement `videos.list` for most popular videos.
4. Implement `search.list` for niche keywords.
5. Implement `videos.list` by IDs for full stats.

### Phase 3: Data Collection

1. Create `source_videos`.
2. Normalize all YouTube responses.
3. Deduplicate by `youtube_video_id`.
4. Store matched keywords and source types.

### Phase 4: Trend Scoring

1. Calculate views per day.
2. Calculate engagement rate.
3. Add freshness score.
4. Add keyword match score.
5. Add negative keyword penalty.
6. Save final `trend_score`.

### Phase 5: Topic Clustering

1. Group similar videos by title phrases and matched keywords.
2. Calculate cluster-level score.
3. Keep top clusters per niche and region.

### Phase 6: Idea Generation

1. Send top clusters to LLM.
2. Generate idea candidates.
3. Validate LLM JSON.
4. Save `idea_candidates`.

### Phase 7: Snapshot API

1. Create `trend_snapshots`.
2. Save completed refresh result.
3. Cache latest response in Redis.
4. Create `GET /api/ideas/trending`.

### Phase 8: Project Pipeline Integration

1. Let user select an idea candidate.
2. Pass selected idea into `generate-package`.
3. Generate SEO data and thumbnail object intelligence.
4. Continue existing project workflow.

## 15. MVP Success Criteria

The system is working when:

```text
User selects a niche.
User sees 10 useful video ideas within 1 second.
Each idea has a real trend reason.
Each idea has source evidence internally.
The idea is not copied from a YouTube title.
The idea is practical for a small or medium creator.
The backend does not call YouTube live during normal user browsing.
```

## 16. Final Recommended User Experience

Screen 1:

```text
Choose your niche
```

Screen 2:

```text
Choose target audience
- United States
```

Screen 3:

```text
Trending video opportunities
Updated 4 hours ago
```

Each idea card:

```text
Title
Trend score
Freshness
Difficulty
Why now
Audience promise
Suggested format
Generate package button
```

This gives the creator clarity without exposing confusing YouTube API details.
