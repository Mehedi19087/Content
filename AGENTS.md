# Repository Guidelines

## Project Structure & Module Organization

This repository contains a Django REST Framework backend for a YouTube packaging studio. Run Django commands from `core/`, where `manage.py` and the project package (`core/core/`) live. Features are split into domain apps: `users/`, `categories/`, `ideas/`, `youtube_channels/`, and `billing/`. Each app keeps models, serializers, views, URL routes, services, migrations, and tests together. Put database and business workflows in `services.py`; keep API views focused on validation and response handling. Project documentation and architecture notes live at the repository root.

## Setup, Test, and Development Commands

Create and activate a virtual environment, then install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

From `core/`, use:

- `python manage.py migrate` — apply database migrations.
- `python manage.py runserver` — start the local API server.
- `python manage.py test` — run the complete test suite using SQLite.
- `python manage.py test ideas` — run one app's tests.
- `python manage.py makemigrations <app>` — generate migrations after model changes.
- `python manage.py seed_categories` and `python manage.py setup_roles` — load initial categories and permissions.
- `python manage.py seed_plans` — seed billing Plan rows and create the Free / Starter / Pro / Creator auth groups (requires `STARTER_VARIANT_ID`, `PRO_VARIANT_ID`, `CREATOR_VARIANT_ID` env vars after you create the LS variants in the dashboard).

## Coding Style & Naming Conventions

Follow standard Python conventions: four-space indentation, `snake_case` for functions and modules, `PascalCase` for classes, and uppercase names for constants. Keep serializers and API methods small, use explicit imports, and match existing DRF response shapes and status codes. No formatter or linter is currently configured, so keep changes PEP 8-compliant and avoid unrelated reformatting. Name routes consistently with their domain and use descriptive Django migration names.

## Testing Guidelines

Tests use Django's `TestCase` and DRF's `APITestCase`, generally in each app's `tests.py`. Name test methods `test_<behavior>` and cover successful requests, validation failures, permissions, and service edge cases. Mock calls to YouTube, Groq, and OpenAI; tests must not depend on live APIs. Run `python manage.py test` before submitting changes. No formal coverage threshold is configured.

## Commit & Pull Request Guidelines

Recent commits use short, imperative summaries such as `Add cryptography dependency for YouTube OAuth`. Keep each commit focused and explain the user-visible outcome. Pull requests should include a concise summary, testing performed, related issue links, migration or environment-variable notes, and sample request/response payloads for API changes. Add screenshots only when documentation or visual output changes.

## Security & Configuration

Store secrets in `.env`; never commit API keys, JWT secrets, credentials, or generated databases. Document new environment variables and provide safe development defaults where appropriate.

### Billing (Lemon Squeezy) environment variables

- `LEMON_SQUEEZY_API_KEY` — API key from your LS dashboard (Settings → API).
- `LEMON_SQUEEZY_WEBHOOK_SECRET` — signing secret shown when you create the webhook in LS.
- `LEMON_SQUEEZY_STORE_ID` — your LS store id (optional for MVP).
- `STARTER_VARIANT_ID`, `PRO_VARIANT_ID`, `CREATOR_VARIANT_ID` — LS variant ids for each tier; required by `python manage.py seed_plans`.
- `FRONTEND_BILLING_SUCCESS_URL`, `FRONTEND_BILLING_CANCEL_URL`, `MOBILE_BILLING_SUCCESS_URL` — post-checkout landing pages (web vs mobile deep link).
- The webhook URL to register in LS is `https://api.creatorintent.com/api/billing/webhook/`.
