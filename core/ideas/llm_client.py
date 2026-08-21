from __future__ import annotations

import logging
from typing import Any

from rest_framework.exceptions import ValidationError

from .deepseek_client import DeepSeekClient
from .groq_client import GroqClient


logger = logging.getLogger(__name__)


class TextGenerationClient:
    """Generate with DeepSeek first and use Groq only when DeepSeek fails."""

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
        try:
            return DeepSeekClient().generate_json(**request)
        except ValidationError as deepseek_error:
            logger.warning("DeepSeek generation failed; trying Groq fallback.")
            try:
                return GroqClient().generate_json(**request)
            except ValidationError as groq_error:
                raise ValidationError(
                    {
                        "llm_api": (
                            "DeepSeek and Groq generation both failed. "
                            f"DeepSeek: {deepseek_error.detail}. "
                            f"Groq: {groq_error.detail}."
                        )
                    }
                ) from groq_error
