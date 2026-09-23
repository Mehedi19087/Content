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
5. `GET /api/intelligence/niche/` returns collection status and timestamps.
   Pending collection is polled every 2–3 seconds. Stuck jobs become failed after
   ten minutes so clients can retry.
6. `POST /api/intelligence/ideas/` with `{"count": 5}` (1–10) uses stored official
   YouTube evidence. It never substitutes AI-only suggestions. With no eligible
   videos it makes no LLM call and returns HTTP 200:

   ```json
   {"data": {
     "ideas": [], "status": "collecting_evidence",
     "message": "Collecting official YouTube video evidence. Try again when collection finishes.",
     "evidence_mode": "INSUFFICIENT_EVIDENCE", "data_timestamp": null,
     "refresh_status": "queued", "creator_refresh_status": "not_needed"
   }}
   ```

   `status` can also be `insufficient_evidence` when collection produced no
   usable sources or the model could not support its ideas. Display `message`;
   do not fabricate placeholder ideas. A failed queue is `queue_unavailable`.

   HTTP 201 has `status: "ready"` and one or more ideas. Fewer than `count` may
   be returned; unsupported ideas are discarded, never padded. Each idea adds:

   - `calculation_version: "youtube-evidence-v2"` and `evidence_expires_at`.
   - `demand_status`: `observed_outperformance` or `not_established`.
   - Source video `views`, `channel_title`, `published_at`, `fetched_at`, and
     `source: "youtube_data_api"`, copied from saved API results, never the LLM.
   - Nullable `outlier_multiplier` and `baseline` (`baseline_views`, `sample_size`,
     `age_bucket`) calculated by the backend.

   Eligible sources are relevant competitor videos published within 180 days,
   fetched within 24 hours, with unexpired metadata from the official API.
   Missing view counts are unavailable, not zero. Expired trend calculations
   are not used. `why_now` is server-written from these observations. The title,
   hook, creator fit, format and risk remain explicitly labelled AI interpretations.

Render the evidence mode and timestamp on **each idea**. The response's aggregate
mode uses the weakest mode among its ideas. Supporting URLs are constructed from saved,
officially validated video IDs, never trusted directly from LLM output.

Analysis dispatch failure returns `503` in the project's error envelope and
persists `failed`. Polling an analysis stuck for ten minutes marks it failed.
Stale niche refresh dispatch failure returns a
`queue_unavailable` refresh status. Only independently fresh video evidence remains usable.

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

Discovery reserves the Search attempt before making the request. Empty or failed discovery can retry after 24 hours; healthy pools retain the
30-day rediscovery interval. Repeated requests within that cooldown do not repeat Search.
The search query uses only the reviewed topic; audience and format are not appended.
Language and region are passed as API parameters. Monitoring uses uploads
playlists and batched video metadata/statistics. Candidate validation and web
fallback may use additional ordinary Data API requests, so quota estimates are
not guaranteed fixed totals; the ledger records actual attempted operations.

Idea modes are `EVIDENCE_BACKED` (3–5 supporting channels) and `LIMITED_EVIDENCE`
(1–2). These describe source breadth, not verified high demand. Empty responses use
`INSUFFICIENT_EVIDENCE`. The legacy pool value `AI_FALLBACK` means no collected
competitor evidence; it no longer enables AI-only idea generation. Confidence is a conservative heuristic, not a
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
refresh every 72 hours. Discovery runs at most once per 30 days for healthy active
pools, or once per day for empty pools. Stale private creator analytics are also queued for refresh when ideas
are generated; the current request still uses the saved summary.

Set `INTELLIGENCE_WEB_SEARCH_API_KEY` to a Brave Search API key to enable web
fallback. Without it, no web request is made. Web text never serves as idea evidence;
YouTube video statistics must be validated through the official API. Web search only runs during background collection, never during
idea generation. Provider failures never produce AI-only suggestions.

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

## Evidence-first deployment

Deploy the backend and `creator-intent` frontend together, and restart the Celery
worker to load the new collection code. No schema migration or new secret is
required by this change. The frontend uses a new session cache version and refuses
legacy AI-only or expired ideas. Keep the worker, Redis and scheduler running.
After deployment, confirm a narrow channel topic, check collection completes,
and generate ideas. Open source links and compare the shown views and collection
timestamps. Current live counts may have changed since collection.

This is observed video-performance research, not exact YouTube keyword volume.
The official Data API does not provide market-wide search volume. Channel-owned
Analytics search terms describe traffic to that channel, not the whole market.
AI relevance judgements and the age-cohort outlier heuristic are not guarantees
of audience demand or future views. Empty evidence is a valid result.
