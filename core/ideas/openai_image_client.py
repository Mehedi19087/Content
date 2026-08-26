from __future__ import annotations

import base64
import io
import json
import logging
import re
import time
import uuid
import urllib.error
import urllib.request
from typing import Any

import cloudinary
import cloudinary.uploader
import requests
from django.conf import settings
from rest_framework.exceptions import ValidationError


OPENAI_IMAGES_URL = "https://api.openai.com/v1/images/generations"
OPENAI_IMAGE_EDITS_URL = "https://api.openai.com/v1/images/edits"
MAX_REFERENCE_IMAGE_BYTES = 5 * 1024 * 1024
performance_logger = logging.getLogger("ideas.performance")


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

        configure_cloudinary()

    def generate_thumbnail(
        self,
        *,
        prompt: str,
        filename_prefix: str = "thumbnail",
        reference_image_url: str = "",
    ) -> dict[str, str]:
        operation = "edit_image" if reference_image_url else "generate_image"
        started_at = time.perf_counter()
        outcome = "failed"
        try:
            if reference_image_url:
                data = self._edit_thumbnail(
                    prompt=prompt,
                    reference_image_url=reference_image_url,
                )
            else:
                data = self._generate_thumbnail(prompt=prompt)
            outcome = "succeeded"
        finally:
            performance_logger.info(
                "ideas.provider_timing provider=openai operation=%s "
                "outcome=%s duration_seconds=%.3f",
                operation,
                outcome,
                time.perf_counter() - started_at,
            )

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

    def _generate_thumbnail(self, *, prompt: str) -> dict[str, Any]:
        request_payload: dict[str, Any] = {
            "model": settings.OPENAI_IMAGE_MODEL,
            "prompt": prompt,
            "size": settings.OPENAI_IMAGE_SIZE,
            "quality": settings.OPENAI_IMAGE_QUALITY,
            "n": 1,
            "output_format": settings.OPENAI_IMAGE_OUTPUT_FORMAT,
        }
        request = urllib.request.Request(
            OPENAI_IMAGES_URL,
            data=json.dumps(request_payload).encode("utf-8"),
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
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise ValidationError(
                {
                    "openai_image_api": (
                        f"Failed to generate thumbnail: HTTP {exc.code} {exc.reason}. "
                        f"Response: {error_body}"
                    )
                }
            ) from exc
        except Exception as exc:
            raise ValidationError(
                {"openai_image_api": f"Failed to generate thumbnail: {exc}"}
            ) from exc

    def _edit_thumbnail(
        self,
        *,
        prompt: str,
        reference_image_url: str,
    ) -> dict[str, Any]:
        try:
            reference_response = requests.get(
                reference_image_url,
                timeout=30,
            )
            reference_response.raise_for_status()
        except requests.RequestException as exc:
            raise ValidationError(
                {"creator_image": "Failed to load the uploaded creator image."}
            ) from exc

        image_bytes = reference_response.content
        if not image_bytes or len(image_bytes) > MAX_REFERENCE_IMAGE_BYTES:
            raise ValidationError(
                {"creator_image": "Uploaded creator image is empty or larger than 5 MB."}
            )
        content_type = reference_response.headers.get("Content-Type", "image/jpeg")
        content_type = content_type.split(";", 1)[0].strip().lower()
        if content_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise ValidationError({"creator_image": "Unsupported creator image format."})

        extension = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}[
            content_type
        ]
        try:
            response = requests.post(
                OPENAI_IMAGE_EDITS_URL,
                headers={"Authorization": f"Bearer {self.api_key}"},
                data={
                    "model": settings.OPENAI_IMAGE_MODEL,
                    "prompt": prompt,
                    "size": settings.OPENAI_IMAGE_SIZE,
                    "quality": settings.OPENAI_IMAGE_QUALITY,
                    "n": "1",
                    "output_format": settings.OPENAI_IMAGE_OUTPUT_FORMAT,
                },
                files={
                    "image[]": (
                        f"creator-reference.{extension}",
                        image_bytes,
                        content_type,
                    )
                },
                timeout=settings.OPENAI_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            response_text = getattr(exc.response, "text", "")[:500]
            raise ValidationError(
                {
                    "openai_image_api": (
                        "Failed to generate thumbnail from the creator image. "
                        f"{response_text}"
                    ).strip()
                }
            ) from exc

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

        started_at = time.perf_counter()
        outcome = "failed"
        try:
            upload_result = cloudinary.uploader.upload(
                image_file,
                public_id=public_id,
                resource_type="image",
                format=output_format,
                overwrite=False,
                timeout=settings.CLOUDINARY_TIMEOUT_SECONDS,
            )
            outcome = "succeeded"
        except Exception as exc:
            raise ValidationError(
                {"cloudinary_upload": f"Failed to upload generated thumbnail: {exc}"}
            )
        finally:
            performance_logger.info(
                "ideas.provider_timing provider=cloudinary operation=upload_image "
                "outcome=%s duration_seconds=%.3f",
                outcome,
                time.perf_counter() - started_at,
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


def configure_cloudinary() -> None:
    cloudinary.config(
        cloud_name=settings.CLOUDINARY_CLOUD_NAME,
        api_key=settings.CLOUDINARY_API_KEY,
        api_secret=settings.CLOUDINARY_API_SECRET,
        secure=True,
    )


def upload_creator_reference_image(*, image_file, user_id: int) -> dict[str, str]:
    configure_cloudinary()
    public_id = f"creatorintent/creator_images/{user_id}/{uuid.uuid4().hex}"
    try:
        upload_result = cloudinary.uploader.upload(
            image_file,
            public_id=public_id,
            resource_type="image",
            overwrite=False,
            timeout=settings.CLOUDINARY_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        raise ValidationError(
            {"creator_image": f"Failed to upload creator image: {exc}"}
        ) from exc

    secure_url = str(upload_result.get("secure_url", "")).strip()
    uploaded_public_id = str(upload_result.get("public_id", "")).strip()
    if not secure_url or not uploaded_public_id:
        raise ValidationError(
            {"creator_image": "Cloudinary returned incomplete creator image data."}
        )
    return {"url": secure_url, "public_id": uploaded_public_id}
