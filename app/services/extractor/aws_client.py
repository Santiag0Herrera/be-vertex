from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from fastapi.concurrency import run_in_threadpool


AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
TEXTRACT_MAX_CONCURRENCY = max(1, int(os.getenv("TEXTRACT_MAX_CONCURRENCY", "5")))
TEXTRACT_MAX_ATTEMPTS = max(1, int(os.getenv("TEXTRACT_MAX_ATTEMPTS", "3")))
TEXTRACT_RETRY_BASE_DELAY_SECONDS = max(
    0.0, float(os.getenv("TEXTRACT_RETRY_BASE_DELAY_SECONDS", "0.5"))
)

TRANSIENT_TEXTRACT_ERROR_CODES = {
    "InternalServerError",
    "LimitExceededException",
    "ProvisionedThroughputExceededException",
    "ServiceUnavailableException",
    "ThrottlingException",
}

logger = logging.getLogger(__name__)
_textract_semaphore = asyncio.Semaphore(TEXTRACT_MAX_CONCURRENCY)


def create_textract_client():
    return boto3.client(
        "textract",
        region_name=AWS_REGION,
        config=Config(
            # Application-level retries below keep the total number of
            # attempts predictable and only retry known transient AWS errors.
            retries={"total_max_attempts": 1, "mode": "standard"},
            connect_timeout=10,
            read_timeout=60,
        ),
    )


_textract_client = create_textract_client()


def get_client_error_code(exc: ClientError) -> str:
    return exc.response.get("Error", {}).get("Code", "Unknown")


async def analyze_document_bytes(
    data: bytes,
    request_id: str = "unknown",
) -> Dict[str, Any]:
    async with _textract_semaphore:
        for attempt in range(1, TEXTRACT_MAX_ATTEMPTS + 1):
            try:
                return await run_in_threadpool(
                    _textract_client.analyze_document,
                    Document={"Bytes": data},
                    FeatureTypes=["FORMS"],
                )
            except ClientError as exc:
                error_code = get_client_error_code(exc)
                should_retry = (
                    error_code in TRANSIENT_TEXTRACT_ERROR_CODES
                    and attempt < TEXTRACT_MAX_ATTEMPTS
                )
                logger.warning(
                    "Textract request failed request_id=%s attempt=%s/%s "
                    "error_code=%s retry=%s",
                    request_id,
                    attempt,
                    TEXTRACT_MAX_ATTEMPTS,
                    error_code,
                    should_retry,
                )
                if not should_retry:
                    raise

                delay = TEXTRACT_RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1))
                await asyncio.sleep(delay)
