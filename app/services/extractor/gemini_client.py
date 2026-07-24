from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any

import httpx

from app.services.extractor.gemini_models import (
    GeminiDocumentFields,
    gemini_response_schema,
)


logger = logging.getLogger(__name__)


class GeminiFallbackError(Exception):
    pass


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
        raise GeminiFallbackError("GEMINI_API_KEY is not configured")

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
        raise GeminiFallbackError("Gemini request timed out") from exc
    except httpx.HTTPStatusError as exc:
        error_detail = get_google_error_detail(exc.response)
        logger.error(
            "Gemini rejected request request_id=%s status_code=%s detail=%s",
            request_id,
            exc.response.status_code,
            error_detail,
        )
        raise GeminiFallbackError(
            f"Gemini rejected the request ({exc.response.status_code}): {error_detail}"
        ) from exc
    except httpx.HTTPError as exc:
        raise GeminiFallbackError("Unable to connect to Gemini") from exc

    try:
        response_data = response.json()
        parts = response_data["candidates"][0]["content"]["parts"]
        output_text = "".join(part.get("text", "") for part in parts)
        return GeminiDocumentFields.model_validate_json(output_text)
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise GeminiFallbackError("Gemini returned an invalid structured response") from exc


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


def get_google_error_detail(response: httpx.Response) -> str:
    try:
        detail = response.json().get("error", {}).get("message")
    except ValueError:
        detail = None

    return str(detail or "No error detail returned")[:500]
