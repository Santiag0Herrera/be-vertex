from __future__ import annotations

import os
from typing import Any, Dict

import boto3
from botocore.config import Config
from fastapi.concurrency import run_in_threadpool


AWS_REGION = os.getenv("AWS_REGION", "us-east-1")


def create_textract_client():
    return boto3.client(
        "textract",
        region_name=AWS_REGION,
        config=Config(
            retries={"max_attempts": 3, "mode": "standard"},
            connect_timeout=10,
            read_timeout=60,
        ),
    )


_textract_client = create_textract_client()


async def analyze_document_bytes(data: bytes) -> Dict[str, Any]:
    return await run_in_threadpool(
        _textract_client.analyze_document,
        Document={"Bytes": data},
        FeatureTypes=["FORMS"],
    )
