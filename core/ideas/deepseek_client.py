from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any

from django.conf import settings
from rest_framework.exceptions import ValidationError


DEEPSEEK_CHAT_COMPLETIONS_URL = "https://api.deepseek.com/chat/completions"
performance_logger = logging.getLogger("ideas.performance")


class DeepSeekClient:
    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.api_key = api_key or settings.DEEPSEEK_API_KEY
        self.model = model or settings.DEEPSEEK_MODEL

        if not self.api_key:
            raise ValidationError(
                {"deepseek_api_key": "DEEPSEEK_API_KEY is not configured."}
            )
        if not self.model:
            raise ValidationError(
                {"deepseek_model": "DEEPSEEK_MODEL is not configured."}
            )

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
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload)},
            ],
        }
        body = json.dumps(request_payload).encode("utf-8")
        request = urllib.request.Request(
            DEEPSEEK_CHAT_COMPLETIONS_URL,
            data=body,
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
            with urllib.request.urlopen(
                request,
                timeout=settings.DEEPSEEK_TIMEOUT_SECONDS,
            ) as response:
                data = json.loads(response.read().decode("utf-8"))
            outcome = "succeeded"
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise ValidationError(
                {
                    "deepseek_api": (
                        f"Failed to generate content: HTTP {exc.code} {exc.reason}. "
                        f"Response: {error_body}"
                    )
                }
            ) from exc
        except Exception as exc:
            raise ValidationError(
                {"deepseek_api": f"Failed to generate content: {exc}"}
            ) from exc
        finally:
            performance_logger.info(
                "ideas.provider_timing provider=deepseek operation=generate_json "
                "outcome=%s duration_seconds=%.3f",
                outcome,
                time.perf_counter() - started_at,
            )

        try:
            content = data["choices"][0]["message"]["content"]
            return json.loads(content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise ValidationError(
                {
                    "deepseek_response": (
                        f"DeepSeek returned invalid JSON content: {exc}"
                    )
                }
            ) from exc
