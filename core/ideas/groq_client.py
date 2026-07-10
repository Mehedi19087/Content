from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from django.conf import settings
from rest_framework.exceptions import ValidationError


GROQ_CHAT_COMPLETIONS_URL = "https://api.groq.com/openai/v1/chat/completions"


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
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload)},
            ],
        }
        body = json.dumps(request_payload).encode("utf-8")
        request = urllib.request.Request(
            GROQ_CHAT_COMPLETIONS_URL,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "content-youtube-idea-generator/1.0",
            },
        )

        try:
            with urllib.request.urlopen(
                request,
                timeout=settings.GROQ_TIMEOUT_SECONDS,
            ) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise ValidationError(
                {
                    "groq_api": (
                        f"Failed to generate ideas: HTTP {exc.code} {exc.reason}. "
                        f"Response: {error_body}"
                    )
                }
            )
        except Exception as exc:
            raise ValidationError({"groq_api": f"Failed to generate ideas: {exc}"})

        try:
            content = data["choices"][0]["message"]["content"]
            return json.loads(content)
        except (KeyError, IndexError, json.JSONDecodeError) as exc:
            raise ValidationError(
                {"groq_response": f"Groq returned invalid JSON content: {exc}"}
            )
