from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.request
from typing import Any

from django.conf import settings
from rest_framework.exceptions import ValidationError


GROQ_CHAT_COMPLETIONS_URL = "https://api.groq.com/openai/v1/chat/completions"
performance_logger = logging.getLogger("ideas.performance")


class GroqClient:
    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.api_key = api_key or settings.GROQ_API_KEY
        self.model = model or settings.GROQ_MODEL

        if not self.api_key:
            raise ValidationError({"groq_api_key": "GROQ_API_KEY is not configured."})
        if not self.model:
            raise ValidationError({"groq_model": "GROQ_MODEL is not configured."})

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_payload: dict[str, Any],
        temperature: float = 0.25,
    ) -> Any:
        request_payload = {
            "model": self.model,
            "temperature": temperature,
            "reasoning_effort": settings.GROQ_REASONING_EFFORT,
            "max_completion_tokens": settings.GROQ_MAX_COMPLETION_TOKENS,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload)},
            ],
        }
        request = urllib.request.Request(
            GROQ_CHAT_COMPLETIONS_URL,
            data=json.dumps(request_payload).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "content-youtube-idea-generator/1.0",
            },
        )

        started_at = time.perf_counter()
        outcome = "failed"
        try:
            data = self._send_request(request)
            outcome = "succeeded"
        finally:
            performance_logger.info(
                "ideas.provider_timing provider=groq operation=generate_json "
                "outcome=%s duration_seconds=%.3f",
                outcome,
                time.perf_counter() - started_at,
            )

        try:
            content = data["choices"][0]["message"]["content"]
            return json.loads(content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise ValidationError(
                {"groq_response": f"Groq returned invalid JSON content: {exc}"}
            ) from exc

    def _send_request(self, request: urllib.request.Request) -> dict[str, Any]:
        for attempt in range(settings.GROQ_RATE_LIMIT_RETRIES + 1):
            try:
                with urllib.request.urlopen(
                    request,
                    timeout=settings.GROQ_TIMEOUT_SECONDS,
                ) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                error_body = exc.read().decode("utf-8", errors="replace")
                retry_wait = _get_retry_wait_seconds(exc, error_body)
                if (
                    exc.code == 429
                    and attempt < settings.GROQ_RATE_LIMIT_RETRIES
                    and retry_wait <= settings.GROQ_MAX_RETRY_WAIT_SECONDS
                ):
                    time.sleep(retry_wait)
                    continue
                raise ValidationError(
                    {
                        "groq_api": (
                            f"Failed to generate content: HTTP {exc.code} "
                            f"{exc.reason}. Response: {error_body}"
                        )
                    }
                ) from exc
            except Exception as exc:
                raise ValidationError(
                    {"groq_api": f"Failed to generate content: {exc}"}
                ) from exc

        raise ValidationError({"groq_api": "Failed to generate content."})


def _get_retry_wait_seconds(
    error: urllib.error.HTTPError,
    error_body: str,
) -> float:
    retry_after = error.headers.get("Retry-After") if error.headers else None
    if retry_after:
        try:
            return max(0.0, float(retry_after))
        except ValueError:
            pass

    match = re.search(r"try again in ([0-9.]+)s", error_body, flags=re.IGNORECASE)
    if match:
        return max(0.0, float(match.group(1)))
    return settings.GROQ_MAX_RETRY_WAIT_SECONDS + 1
