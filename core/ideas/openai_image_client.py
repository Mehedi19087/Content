from __future__ import annotations

import base64
import io
import json
import re
import uuid
import urllib.error
import urllib.request
from typing import Any

import cloudinary
import cloudinary.uploader
from django.conf import settings
from rest_framework.exceptions import ValidationError


OPENAI_IMAGES_URL = "https://api.openai.com/v1/images/generations"


class OpenAIImageClient:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or settings.OPENAI_API_KEY
        if not self.api_key:
            raise ValidationError({"openai_api_key": "OPENAI_API_KEY is not configured."})

        missing_cloudinary_settings = [
            name
            for name, value in (
                ("CLOUDINARY_CLOUD_NAME", settings.CLOUDINARY_CLOUD_NAME),
                ("CLOUDINARY_API_KEY", settings.CLOUDINARY_API_KEY),
                ("CLOUDINARY_API_SECRET", settings.CLOUDINARY_API_SECRET),
            )
            if not value
        ]
        if missing_cloudinary_settings:
            raise ValidationError(
                {
                    "cloudinary": (
                        "Missing Cloudinary settings: "
                        f"{', '.join(missing_cloudinary_settings)}."
                    )
                }
            )

        cloudinary.config(
            cloud_name=settings.CLOUDINARY_CLOUD_NAME,
            api_key=settings.CLOUDINARY_API_KEY,
            api_secret=settings.CLOUDINARY_API_SECRET,
            secure=True,
        )

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

        return self._upload_image(
            image_base64=image_base64,
            filename_prefix=filename_prefix,
            output_format=settings.OPENAI_IMAGE_OUTPUT_FORMAT,
        )

    def _upload_image(
        self,
        *,
        image_base64: str,
        filename_prefix: str,
        output_format: str,
    ) -> dict[str, str]:
        output_format = output_format.lower().strip() or "png"
        try:
            image_bytes = base64.b64decode(image_base64)
        except (TypeError, ValueError) as exc:
            raise ValidationError(
                {"openai_image_response": f"OpenAI returned invalid base64 data: {exc}"}
            )

        safe_prefix = re.sub(r"[^a-zA-Z0-9_-]+", "-", filename_prefix).strip("-")
        safe_prefix = safe_prefix or "thumbnail"
        asset_name = f"{safe_prefix}-{uuid.uuid4().hex}"
        public_id = f"creatorintent/generated_thumbnails/{asset_name}"
        image_file = io.BytesIO(image_bytes)
        image_file.name = f"{asset_name}.{output_format}"

        try:
            upload_result = cloudinary.uploader.upload(
                image_file,
                public_id=public_id,
                resource_type="image",
                format=output_format,
                overwrite=False,
            )
        except Exception as exc:
            raise ValidationError(
                {"cloudinary_upload": f"Failed to upload generated thumbnail: {exc}"}
            )

        secure_url = str(upload_result.get("secure_url", "")).strip()
        uploaded_public_id = str(upload_result.get("public_id", "")).strip()
        if not secure_url or not uploaded_public_id:
            raise ValidationError(
                {"cloudinary_upload": "Cloudinary returned incomplete upload data."}
            )

        return {
            "url": secure_url,
            "public_id": uploaded_public_id,
            "model": settings.OPENAI_IMAGE_MODEL,
            "size": settings.OPENAI_IMAGE_SIZE,
            "quality": settings.OPENAI_IMAGE_QUALITY,
        }
