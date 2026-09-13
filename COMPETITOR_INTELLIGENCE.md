# Creator intelligence MVP

The new authenticated `/api/intelligence/` flow builds an owner-only Channel DNA
profile, shares public competitor evidence across matching niches, and generates
ideas from saved evidence. Existing category ideas, intent research and content
package endpoints retain their existing contracts. Clients must use the new
endpoint below for the zero-live-YouTube generation workflow.

## Client workflow

1. Connect through the existing `/api/youtube/connect/` OAuth flow. Display
   `/api/youtube/channel/` and ask the creator to confirm the channel identity.
2. `POST /api/intelligence/analyze/` with `{"channel_confirmed": true}`.
   This returns `202` with `data.id` and `data.status: "pending"`.
3. Poll `GET /api/intelligence/dna/` every 2–3 seconds until `status` is
   `succeeded` or `failed`. Stop polling when leaving the screen.
4. Review and correct the profile, then confirm it:

   ```http
   PATCH /api/intelligence/dna/
   Content-Type: application/json

   {
     "confirmed": true,
     "profile": {
       "core_topic": "Japan travel",
       "target_audience": "Bangladeshi travellers",
       "primary_language": "bn",
       "geographic_focus": "BD",
       "intent": "Budget travel planning",
       "main_content_formats": ["guide", "vlog"],
       "creator_direction": "Continue"
     }
   }
   ```

   Other editable profile fields are `presentation_style`,
   `winning_topic_patterns` (array), `winning_video_length`, and
   `traffic_source_pattern`. Profile updates merge with the saved draft.
   Confirmation attaches a shared niche and queues collection when needed.
5. `GET /api/intelligence/niche/` returns collection status and evidence
   timestamps. A pending or failed collection does not prevent AI suggestions.
6. `POST /api/intelligence/ideas/` with `{"count": 5}` (1–10) makes one LLM
   call using stored information. It returns `201`:

   ```json
   {
     "data": {
       "ideas": [{
         "id": 1,
         "idea": "A first-time Japan budget checklist",
         "hook": "Plan the costs before booking your first trip.",
         "why_this_fits_creator": "Matches the reviewed budget travel profile.",
         "why_now": "An evergreen suggestion based on your Channel DNA and available creator history. YouTube trend evidence was not available for this idea.",
         "supporting_videos": [],
         "suggested_format": "guide",
         "suggested_video_length": "8–10 minutes",
         "risk": "Travel costs vary; verify prices before filming.",
         "confidence": 0.2,
         "evidence_mode": "AI_FALLBACK",
         "evidence_label": "AI-suggested idea",
         "evidence_message": "YouTube trend evidence was not available for this idea.",
         "data_timestamp": "2026-09-12T00:00:00+00:00"
       }],
       "evidence_mode": "AI_FALLBACK",
       "data_timestamp": "2026-09-12T00:00:00+00:00",
       "refresh_status": "not_needed",
       "creator_refresh_status": "not_needed"
     }
   }
   ```

Render the evidence mode and timestamp on **each idea**. The response's aggregate
mode uses the weakest mode among its ideas. Supporting URLs are constructed from saved,
officially validated video IDs, never trusted directly from LLM output.

Analysis dispatch failure returns `503` in the project's error envelope and
persists `failed`. Polling an analysis stuck for ten minutes marks it failed.
Stale niche refresh dispatch failure returns a
`queue_unavailable` refresh status while keeping saved evidence usable.

## Storage and evidence

`youtube_channels.YouTubeChannel` remains the OAuth connection: it owns the
encrypted token and user relationship. `intelligence.PublicChannel` is the
separate shared public channel entity. This avoids duplicating secrets or
copying private analytics into public competitor rows.

The intelligence app stores ChannelDNA, NichePool, NichePoolChannel,
YouTubeVideo, VideoStatSnapshot, CompetitorBaseline, TrendSignal,
GeneratedIdea, IdeaEvidence, and QuotaLedger. Source records carry
`source`, `fetched_at`, and `expires_at`; derived records also carry model and
calculation versions, confidence, and evidence mode. Disconnecting the existing
OAuth connection cascades deletion of its private DNA and generated ideas.

Niche identity normalizes the creator's topic, audience, language, geography,
intent and format. Matching is deliberately conservative; it uses no embedding
service or extra model request. Identical canonical definitions share a unique
database row. No private analytics are placed in the niche definition.

Discovery reserves the Search attempt before making the request. Weak results
and retries do not trigger another discovery Search. Monitoring uses uploads
playlists and batched video metadata/statistics. Candidate validation and web
fallback may use additional ordinary Data API requests, so quota estimates are
not guaranteed fixed totals; the ledger records actual attempted operations.

The modes are `EVIDENCE_BACKED` (3–5 supporting channels), `LIMITED_EVIDENCE`
(1–2), and `AI_FALLBACK` (none). Confidence is a conservative heuristic, not a
statistically calibrated probability. Sparse samples do not establish reliable
outliers, and a channel match alone does not establish a broad market trend.

Outliers compare long-form uploads in age cohorts within the same channel,
excluding the candidate from its median baseline. The Data API does not expose
a definitive Shorts flag. Videos up to 180 seconds remain an ambiguous cohort
and are excluded from outlier scoring rather than mixed with long-form videos.

## Configuration and operation

Apply migrations and start the existing Celery worker before enabling this UI:

```bash
cd core
../.venv/bin/python manage.py migrate
../.venv/bin/celery -A core worker --loglevel=info --concurrency=2
```

Use the existing `YOUTUBE_API_KEY`, OAuth credentials, token encryption key,
LLM settings, and `CELERY_BROKER_URL`. The default `CELERY_BEAT_SCHEDULE` checks
due niches every three hours. Run a separate beat process:

```bash
cd core
../.venv/bin/celery -A core beat --loglevel=info
```

Alternatively, have an external scheduler run
`../.venv/bin/python manage.py refresh_intelligence` from `core/` every three
hours. Use one scheduler. Only pools linked to confirmed creator profiles are
scheduled. Redis is used for the queue; PostgreSQL is the evidence source of
truth, so this MVP does not require a second cache invalidation layer.

`INTELLIGENCE_POOL_REFRESH_HOURS` defaults to 24 (minimum 12) for standard
niches. Explicit breaking-news topics refresh every six hours; dormant pools
refresh every 72 hours. Discovery runs at most once per 30 days for active
pools. Stale private creator analytics are also queued for refresh when ideas
are generated; the current request still uses the saved summary.

Set `INTELLIGENCE_WEB_SEARCH_API_KEY` to a Brave Search API key to enable web
fallback. Without it, no web request is made and AI fallback uses saved creator
information. Web search only runs during background collection, never during
idea generation. Provider failures do not turn AI suggestions into trends.

Private analytics may be unavailable for a new/small channel or a particular
report. Such metrics are explicitly recorded as unavailable, never invented.
Thumbnail impressions/CTR require existing accessible Reporting data; connection
alone does not backfill reports.

Official API references:

- [Current quota allocation](https://developers.google.com/youtube/v3/getting-started)
  separates Search calls from ordinary Data API units.
- [Search parameters](https://developers.google.com/youtube/v3/docs/search/list)
  allow up to 50 results in the single discovery request.
- [Analytics channel reports](https://developers.google.com/youtube/analytics/channel_reports)
  define supported metric/dimension combinations.
- [Reporting reports](https://developers.google.com/youtube/reporting/v1/reports/full_report_list)
  describe available bulk report types.
