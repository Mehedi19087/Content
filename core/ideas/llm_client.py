from __future__ import annotations

import logging
from typing import Any

from rest_framework.exceptions import ValidationError

from .deepseek_client import DeepSeekClient
from .groq_client import GroqClient


logger = logging.getLogger(__name__)


class TextGenerationClient:
    """Generate JSON with an ordered DeepSeek/Groq fallback chain."""

    def __init__(
        self,
        *,
        prefer_groq: bool = False,
        timeout_seconds: int | None = None,
        groq_rate_limit_retries: int | None = None,
    ):
        self.prefer_groq = prefer_groq
        self.timeout_seconds = timeout_seconds
        self.groq_rate_limit_retries = groq_rate_limit_retries

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_payload: dict[str, Any],
        temperature: float = 0.25,
    ) -> Any:
        request = {
            "system_prompt": system_prompt,
            "user_payload": user_payload,
            "temperature": temperature,
        }
        providers = (
            (("Groq", self._groq_client), ("DeepSeek", self._deepseek_client))
            if self.prefer_groq
            else (("DeepSeek", self._deepseek_client), ("Groq", self._groq_client))
        )
        errors = {}

        for index, (provider_name, client_factory) in enumerate(providers):
            try:
                return client_factory().generate_json(**request)
            except ValidationError as exc:
                errors[provider_name] = exc.detail
                if index == 0:
                    logger.warning(
                        "%s generation failed; trying %s fallback.",
                        provider_name,
                        providers[1][0],
                    )

        raise ValidationError(
            {
                "llm_api": (
                    "DeepSeek and Groq generation both failed. "
                    f"DeepSeek: {errors.get('DeepSeek')}. "
                    f"Groq: {errors.get('Groq')}."
                )
            }
        )

    def _deepseek_client(self) -> DeepSeekClient:
        return DeepSeekClient(timeout_seconds=self.timeout_seconds)

    def _groq_client(self) -> GroqClient:
        return GroqClient(
            timeout_seconds=self.timeout_seconds,
            rate_limit_retries=self.groq_rate_limit_retries,
        )
