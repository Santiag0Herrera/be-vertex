from __future__ import annotations

import base64
import json
import logging
import os
import re
from typing import Any

import httpx

from app.services.extractor.gemini_models import (
    GeminiDocumentFields,
    gemini_response_schema,
)


logger = logging.getLogger(__name__)


class GeminiFallbackError(Exception):
    def __init__(
        self,
        reason: str,
        *,
        status_code: int | None = None,
        retry_after: str | None = None,
        model: str | None = None,
    ) -> None:
        self.reason = reason
        self.status_code = status_code
        self.retry_after = retry_after
        self.model = model
        super().__init__(reason)


def is_gemini_configured() -> bool:
    return bool(os.getenv("GEMINI_API_KEY"))


async def extract_document_fields(
    data: bytes,
    content_type: str,
    partial: dict[str, Any],
    required_fields: set[str],
    request_id: str = "unknown",
) -> GeminiDocumentFields:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise GeminiFallbackError("not_configured")

    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    timeout_seconds = max(
        1.0,
        float(os.getenv("GEMINI_TIMEOUT_SECONDS", "20")),
    )
    api_url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent"
    )
    prompt = build_prompt(partial, required_fields)
    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "inlineData": {
                            "mimeType": content_type,
                            "data": base64.b64encode(data).decode("ascii"),
                        }
                    },
                    {"text": prompt},
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
            "responseSchema": gemini_response_schema(),
        },
    }

    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.post(
                api_url,
                headers={
                    "Content-Type": "application/json",
                    "x-goog-api-key": api_key,
                },
                json=payload,
            )
            response.raise_for_status()
    except httpx.TimeoutException as exc:
        raise GeminiFallbackError("timeout", model=model) from exc
    except httpx.HTTPStatusError as exc:
        raise GeminiFallbackError(
            classify_google_error(exc.response),
            status_code=exc.response.status_code,
            retry_after=get_retry_after(exc.response),
            model=model,
        ) from exc
    except httpx.HTTPError as exc:
        raise GeminiFallbackError("connection_error", model=model) from exc

    try:
        response_data = response.json()
        parts = response_data["candidates"][0]["content"]["parts"]
        output_text = "".join(part.get("text", "") for part in parts)
        return GeminiDocumentFields.model_validate_json(output_text)
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise GeminiFallbackError("invalid_response", model=model) from exc


def build_prompt(partial: dict[str, Any], required_fields: set[str]) -> str:
    return (
        "Analiza este comprobante de transferencia bancaria argentino. "
        "Extrae solamente información visible en el documento. No infieras ni inventes datos. "
        "Si un campo no aparece claramente, devuelve null. "
        "Los CUIT/CUIL deben contener 11 dígitos, los CBU/CVU 22 dígitos y date debe usar "
        "formato YYYY-MM-DD. amount debe conservar sus decimales y trx_id debe ser el "
        "identificador de operación, transacción o comprobante. "
        f"Completa prioritariamente estos campos: {sorted(required_fields)}. "
        "Textract ya obtuvo este resultado parcial; úsalo sólo como contexto y no lo contradigas: "
        f"{json.dumps(partial, ensure_ascii=False, default=str)}"
    )


def get_google_error_message(response: httpx.Response) -> str:
    try:
        detail = response.json().get("error", {}).get("message")
    except ValueError:
        detail = None

    return " ".join(str(detail or "").split())


def classify_google_error(response: httpx.Response) -> str:
    status_code = response.status_code
    message = get_google_error_message(response).lower()

    if status_code == 429:
        return "quota_exceeded" if "quota" in message else "rate_limited"
    if status_code in {401, 403}:
        return "authentication_error"
    if status_code == 400:
        return "invalid_request"
    if status_code >= 500:
        return "provider_error"
    return "http_error"


def get_retry_after(response: httpx.Response) -> str | None:
    header_value = response.headers.get("Retry-After")
    if header_value:
        return header_value

    try:
        error_details = response.json().get("error", {}).get("details", [])
    except ValueError:
        error_details = []

    for detail in error_details:
        if isinstance(detail, dict) and detail.get("retryDelay"):
            return str(detail["retryDelay"])

    match = re.search(
        r"retry in\s+([0-9]+(?:\.[0-9]+)?s)",
        get_google_error_message(response),
        re.IGNORECASE,
    )
    return match.group(1) if match else None
