# Content Package Background Jobs

Content-package generation runs in a Celery worker so the public HTTP request
does not remain open while AI providers generate text and images.

## Production components

- The existing web service runs the Gunicorn command in `Procfile`.
- A Redis service provides `CELERY_BROKER_URL`.
- A worker service runs the `worker` command in `Procfile`.
- PostgreSQL stores every `ContentPackageJob`, including status and result.

Both web and worker services need the same application environment variables,
including database, Redis, DeepSeek, Groq, OpenAI, and Cloudinary credentials.

Required background-job setting:

```env
CELERY_BROKER_URL=redis://username:password@host:port/0
```

For a TLS Redis provider, use its supplied `rediss://` URL unchanged.

Optional defaults:

```env
CLOUDINARY_TIMEOUT_SECONDS=60
CELERY_TASK_SOFT_TIME_LIMIT=420
CELERY_TASK_TIME_LIMIT=450
CONTENT_PACKAGE_JOB_STALE_SECONDS=600
```

## Deployment order

1. Provision Redis and set `CELERY_BROKER_URL` on web and worker services.
2. Deploy the release command so migration `ideas.0003` is applied.
3. Start one worker service using the `worker` Procfile process.
4. Deploy the web service.
5. Submit one package request and poll its job endpoint to completion.

Do not deploy the asynchronous API without a running worker. Requests would be
accepted into Redis but remain pending until a worker becomes available.

## Frontend contract

1. Send `POST /api/ideas/generate-package/` once.
2. Store the returned job `id` so a page refresh does not create another job.
3. Poll `GET /api/ideas/generation-jobs/{id}/` every 2–3 seconds.
4. Stop polling when status becomes `succeeded` or `failed`.
5. On `succeeded`, render `data.result` using the previous package response UI.
6. On `failed`, show `error_message` and allow the user to start a new job.

The frontend should disable the submit button while the initial POST is in
progress. Polling should stop when the user leaves the page and resume from the
stored job id when they return.

Queue publishing does not retry inside the HTTP request. If Redis cannot be
reached within five seconds, the job is marked failed and the API returns `503`
so the user can try again without keeping a web thread occupied.

## Operational checks

Web logs show request dispatch time:

```text
ideas.request_timing endpoint=generate_package ...
```

Worker logs show DeepSeek, Groq, OpenAI, Cloudinary, and final job outcomes.
The Django admin can inspect `ContentPackageJob` rows when investigating failed
or stuck jobs.
