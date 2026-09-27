# Repository Guidelines

## Project Structure & Module Organization

Django REST Framework backend for a YouTube packaging studio. The Django project lives one level down at `core/` — `manage.py` and the project package (`core/core/`) are there, not at the repo root. Run every `manage.py` and `celery` command from inside `core/` (the Procfile uses `--workdir core` / `--chdir core` accordingly).

Domain apps live under `core/`:

- `users/` — custom `User` model (`AUTH_USER_MODEL = 'users.User'`), JWT auth, OAuth helpers, tier/role permissions.
- `categories/` — top-level content categories.
- `ideas/` — trending ideas, YouTube intent research, content-package generation (Celery), script guide, thumbnail prep, asset uploads.
- `youtube_channels/` — YouTube Data API + OAuth, channel analytics, Fernet-encrypted refresh tokens.
- `billing/` — Lemon Squeezy plans, checkout, webhooks, subscription state.

Each app keeps `models.py`, `serializers.py`, `views.py`, `urls.py`, `services.py`, `migrations/`, `tests.py`, and (when applicable) `admin.py`, `tasks.py`, `exceptions.py`, `management/commands/`, and external-API client modules (`*_client.py`).

Architecture rules worth knowing:

- Business/database workflows live in `services.py`. Views only validate and respond — keep them thin.
- External HTTP/SDK calls live in dedicated `*_client.py` modules (e.g. `ideas/deepseek_client.py`, `ideas/groq_client.py`, `ideas/openai_image_client.py`, `ideas/youtube_client.py`, `youtube_channels/youtube_client.py`, `billing/client.py`).
- All API errors go through `core.exceptions.api_exception_handler`. Every error response is wrapped as `{ error: { status, code, message, details }, ...original }`. Match this shape when adding custom exceptions.
- Project-level docs: `architecture.md` (high-level design), `architecture_deep_dive.md`, `API_DOCUMENTATION.md`, `BACKGROUND_JOBS.md` (read this before touching `ideas/`).

## Setup, Test, and Development Commands

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cd core
python manage.py migrate
python manage.py runserver
```

Database is selected automatically in `core/settings.py`: if `test` appears in `sys.argv` it uses SQLite (`core/db.sqlite3`); otherwise it reads `DATABASE_URL` (parsed via `dj_database_url`) and falls back to `DB_NAME/DB_USER/DB_PASS/DB_HOST/DB_PORT`. Don't hardcode a DB choice — let the env decide.

Management commands (run from `core/`):

- `python manage.py migrate` / `makemigrations <app>` — schema changes.
- `python manage.py test` — run the full suite (Django test runner, not pytest).
- `python manage.py test <app>` — single app; `python manage.py test <app>.tests.<ClassName>.<test_method>` for one test.
- `python manage.py seed_categories` — load the default category list (run once on a fresh DB).
- `python manage.py setup_roles` — create the `Free Users` and `Premium Users` auth groups and bind Django model perms.
- `python manage.py seed_plans` — create `Plan` rows and `Starter Users` / `Pro Users` / `Ultra Users` / `Creator Users` groups. Requires the `*_VARIANT_ID` env vars (see below).
- `python manage.py refresh_ideas` — invoke the same code path the cron endpoint uses; useful for local sanity checks.
- `python manage.py createsuperuser` — works against the custom `users.User` model.

For background work locally you also need Redis:

```bash
redis-server                                       # or run via docker/systemd
celery --workdir core -A core worker --loglevel=info --concurrency=2
```

## Coding Style & Naming Conventions

Four-space indent, `snake_case` functions/modules, `PascalCase` classes, uppercase constants. No formatter or linter is wired up — keep changes PEP 8-compliant by hand and avoid unrelated reformatting. Use explicit imports and mirror existing DRF response shapes (see the API error envelope above). Name routes consistently with their domain and use descriptive Django migration names (`add_<thing>`, `alter_<field>`, etc.).

## Testing Guidelines

Tests live in each app's `tests.py` (and `test_<feature>.py` for larger flows like `ideas/test_package_jobs.py` and `ideas/test_performance_logging.py`). Use `django.test.TestCase` or `rest_framework.test.APITestCase`. Method naming: `test_<behavior>`. Cover happy path, validation failures, permission denial, and service edge cases.

Mandatory: mock every external call. YouTube (Data API + OAuth), DeepSeek, Groq, OpenAI image gen, Cloudinary, and Lemon Squeezy must never run live in tests — patch the `*_client` modules at the import site (e.g. `@patch("ideas.deepseek_client.urllib.request.urlopen")`, `@patch("ideas.views.generate_content_package_task.apply_async")`). When Redis is unreachable, the API is expected to mark the job failed and return 503; tests assert that behavior.

Run `python manage.py test` from `core/` before submitting. No coverage gate is configured.

## Commit & Pull Request Guidelines

Recent commits use short imperative summaries (`Add cryptography dependency for YouTube OAuth`, `Refresh ideas asynchronously and improve cluster quality`). Keep each commit focused on one user-visible outcome. PRs should include a concise summary, the testing performed (`python manage.py test` and any manual steps), related issue links, notes on migrations or env-var changes, and sample request/response payloads for API changes. Add screenshots only when documentation or visual output changes.

## Security & Configuration

Secrets live in `.env` (loaded by `python-dotenv` at import time in `settings.py`); never commit `.env`, `db.sqlite3`, `media/`, or `staticfiles/`. Document new env vars and provide safe development defaults in `settings.py` (the pattern used throughout).

### Environment variables

YouTube / OAuth:

- `YOUTUBE_API_KEY` — Data API key.
- `YOUTUBE_OAUTH_REDIRECT_URI`, `FRONTEND_YOUTUBE_REDIRECT_URL` — OAuth redirects.
- `YOUTUBE_TOKEN_ENCRYPTION_KEY` — used by `youtube_channels.services.get_token_cipher` (Fernet key derived via SHA-256). Falls back to `DJANGO_SECRET_KEY` if unset — set it explicitly in any non-dev environment.

LLM providers:

- `DEEPSEEK_API_KEY`, `DEEPSEEK_MODEL`, `DEEPSEEK_TIMEOUT_SECONDS`.
- `GROQ_API_KEY`, `GROQ_MODEL`, `GROQ_TIMEOUT_SECONDS`, `GROQ_REASONING_EFFORT`, `GROQ_MAX_COMPLETION_TOKENS`, `GROQ_RATE_LIMIT_RETRIES`, `GROQ_MAX_RETRY_WAIT_SECONDS`.
- `OPENAI_API_KEY`, `OPENAI_IMAGE_MODEL`, `OPENAI_IMAGE_SIZE`, `OPENAI_IMAGE_QUALITY`, `OPENAI_IMAGE_OUTPUT_FORMAT`, `OPENAI_TIMEOUT_SECONDS`.

Assets / media:

- `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, `CLOUDINARY_API_SECRET`, `CLOUDINARY_TIMEOUT_SECONDS`. Media is local FileSystemStorage in dev; Cloudinary is used in production — confirm storage backend in `STORAGES` before assuming a URL is reachable.

Billing (Lemon Squeezy):

- `LEMON_SQUEEZY_API_KEY`, `LEMON_SQUEEZY_WEBHOOK_SECRET`, `LEMON_SQUEEZY_STORE_ID` (optional for MVP), `LEMON_SQUEEZY_API_BASE_URL`, `LEMON_SQUEEZY_TIMEOUT_SECONDS`.
- `STARTER_VARIANT_ID`, `PRO_VARIANT_ID`, `ULTRA_VARIANT_ID` (legacy `CREATOR_VARIANT_ID` is accepted during migration), plus `*_YEARLY_VARIANT_ID` for each.
- `FRONTEND_BILLING_SUCCESS_URL`, `FRONTEND_BILLING_CANCEL_URL`, `MOBILE_BILLING_SUCCESS_URL` — post-checkout landing pages (web vs mobile deep link).
- The webhook URL to register in LS is `https://api.creatorintent.com/api/billing/webhook/`.

Background jobs:

- `CELERY_BROKER_URL` — required in any env that processes jobs (`redis://...` or `rediss://...`). Worker and web must share this.
- `CELERY_TASK_SOFT_TIME_LIMIT` (default 420s) / `CELERY_TASK_TIME_LIMIT` (450s).
- `CONTENT_PACKAGE_JOB_STALE_SECONDS` (default 600s) — when a stuck job is considered failed.
- `IDEA_EXPIRY_HOURS` (80), `IDEA_CRON_SECRET` (protects the cron refresh endpoint), `IDEA_CRON_MAX_ATTEMPTS`, `IDEA_CRON_RETRY_BASE_SECONDS`, `IDEA_CRON_RETRY_MAX_SECONDS`.

CORS / hosts:

- `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `ALLOWED_HOSTS`.
- `CORS_ALLOWED_ORIGINS` (comma-separated) and `CORS_ALLOWED_ORIGIN_REGEXES` (regex strings, comma-separated). Defaults already cover Lovable preview hosts and localhost.

## Tier & Auth Model

`AUTH_USER_MODEL = 'users.User'`. Default DRF auth class is `users.authentication.LoggingJWTAuthentication` (logs token fingerprints and signing-key fingerprints on every request — useful for debugging 401s, do not silence). Default permission is `IsAuthenticated`; tier-specific permissions live in `users/permissions.py`.

Auth groups (run `setup_roles` and `seed_plans`):

- `Free Users`, `Premium Users` — Django model perms for `categories` and `ideas` (created by `setup_roles`).
- `Starter Users`, `Pro Users`, `Ultra Users`, `Creator Users` — tier gating for paid features (created by `seed_plans`). `HasUltraPermission` is an alias for `HasCreatorPermission`. Tiers are cumulative: each higher tier unlocks everything below.

## Background Jobs & Deployment

Production runs three processes (see `Procfile`):

- `release`: `python core/manage.py migrate && python core/manage.py collectstatic --noinput`.
- `web`: `gunicorn --chdir core core.wsgi --bind 0.0.0.0:$PORT --threads 4 --timeout 300 --graceful-timeout 30`.
- `worker`: `celery --workdir core -A core worker --loglevel=info --concurrency=2`.

Static files are served by `whitenoise` from `core/staticfiles/`. Media goes to `core/media/` locally; switch to Cloudinary in production by changing the `STORAGES` default backend.

Frontend contract for async package generation (read `BACKGROUND_JOBS.md` for full detail):

1. `POST /api/ideas/generate-package/` once — receive `{ id, status: "pending" }`. Store the `id`; don't resubmit on page refresh.
2. Poll `GET /api/ideas/generation-jobs/{id}/` every 2–3 s.
3. Stop polling on `succeeded` (render `data.result`) or `failed` (show `error_message`).
4. Disable the submit button while the initial POST is in flight; pause polling when the user leaves the page.
5. If Redis is unreachable at dispatch time, the API marks the job failed and returns `503` — never blocks a web thread.

Do not deploy the async package endpoints without a running worker; requests would queue in Redis and never resolve.
