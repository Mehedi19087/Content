from __future__ import annotations

import base64
import json
import uuid
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from django.conf import settings
from rest_framework.exceptions import ValidationError


OPENAI_IMAGES_URL = "https://api.openai.com/v1/images/generations"


class OpenAIImageClient:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or settings.OPENAI_API_KEY
        if not self.api_key:
            raise ValidationError({"openai_api_key": "OPENAI_API_KEY is not configured."})

    def generate_thumbnail(
        self,
        *,
        prompt: str,
        filename_prefix: str = "thumbnail",
    ) -> dict[str, str]:
        request_payload: dict[str, Any] = {
            "model": settings.OPENAI_IMAGE_MODEL,
            "prompt": prompt,
            "size": settings.OPENAI_IMAGE_SIZE,
            "quality": settings.OPENAI_IMAGE_QUALITY,
            "n": 1,
            "output_format": settings.OPENAI_IMAGE_OUTPUT_FORMAT,
        }
        body = json.dumps(request_payload).encode("utf-8")
        request = urllib.request.Request(
            OPENAI_IMAGES_URL,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "content-youtube-thumbnail-generator/1.0",
            },
        )

        try:
            with urllib.request.urlopen(
                request,
                timeout=settings.OPENAI_TIMEOUT_SECONDS,
            ) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise ValidationError(
                {
                    "openai_image_api": (
                        f"Failed to generate thumbnail: HTTP {exc.code} {exc.reason}. "
                        f"Response: {error_body}"
                    )
                }
            )
        except Exception as exc:
            raise ValidationError({"openai_image_api": f"Failed to generate thumbnail: {exc}"})

        try:
            image_base64 = data["data"][0]["b64_json"]
        except (KeyError, IndexError) as exc:
            raise ValidationError(
                {"openai_image_response": f"OpenAI returned invalid image data: {exc}"}
            )

        return self._save_image(
            image_base64=image_base64,
            filename_prefix=filename_prefix,
            output_format=settings.OPENAI_IMAGE_OUTPUT_FORMAT,
        )

    def _save_image(
        self,
        *,
        image_base64: str,
        filename_prefix: str,
        output_format: str,
    ) -> dict[str, str]:
        output_format = output_format.lower().strip() or "png"
        image_bytes = base64.b64decode(image_base64)
        filename = f"{filename_prefix}-{uuid.uuid4().hex}.{output_format}"
        relative_path = Path("generated_thumbnails") / filename
        absolute_path = Path(settings.MEDIA_ROOT) / relative_path
        absolute_path.parent.mkdir(parents=True, exist_ok=True)
        absolute_path.write_bytes(image_bytes)

        return {
            "url": f"{settings.MEDIA_URL}{relative_path.as_posix()}",
            "path": str(absolute_path),
            "model": settings.OPENAI_IMAGE_MODEL,
            "size": settings.OPENAI_IMAGE_SIZE,
            "quality": settings.OPENAI_IMAGE_QUALITY,
        }
