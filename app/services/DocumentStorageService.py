import base64
import os
from urllib.parse import quote

import boto3
from botocore.config import Config


class DocumentStorageConfigurationError(RuntimeError):
    pass


class DocumentStorageService:
    def __init__(self, s3_client=None, bucket: str | None = None):
        self.bucket = bucket or os.getenv("DOCUMENT_BUCKET", "").strip()
        if not self.bucket:
            raise DocumentStorageConfigurationError("DOCUMENT_BUCKET is not configured")

        self.region = os.getenv("DOCUMENT_REGION", "us-east-1").strip()
        self.upload_ttl_seconds = int(
            os.getenv("DOCUMENT_UPLOAD_TTL_SECONDS", "600")
        )
        self.view_ttl_seconds = int(os.getenv("DOCUMENT_VIEW_TTL_SECONDS", "120"))
        self.max_size_bytes = int(os.getenv("DOCUMENT_MAX_SIZE_BYTES", "10485760"))
        self.s3 = s3_client or boto3.client(
            "s3",
            region_name=self.region,
            config=Config(signature_version="s3v4"),
        )

    @staticmethod
    def staging_key(entity_id: int, session_id: str, document_id: str) -> str:
        return f"staging/{entity_id}/{session_id}/{document_id}"

    @staticmethod
    def object_key(entity_id: int, document_id: str) -> str:
        return f"documents/{entity_id}/{document_id}"

    def create_upload_form(
        self,
        *,
        key: str,
        mime_type: str,
        sha256: str,
        size_bytes: int,
    ) -> dict:
        if size_bytes <= 0 or size_bytes > self.max_size_bytes:
            raise ValueError("Document size is outside the allowed range")

        fields = {
            "Content-Type": mime_type,
            "x-amz-meta-sha256": sha256,
            "x-amz-checksum-sha256": base64.b64encode(
                bytes.fromhex(sha256)
            ).decode("ascii"),
            "x-amz-server-side-encryption": "AES256",
        }
        conditions = [
            {"key": key},
            {"Content-Type": mime_type},
            {"x-amz-meta-sha256": sha256},
            {"x-amz-checksum-sha256": fields["x-amz-checksum-sha256"]},
            {"x-amz-server-side-encryption": "AES256"},
            ["content-length-range", 1, self.max_size_bytes],
        ]
        return self.s3.generate_presigned_post(
            Bucket=self.bucket,
            Key=key,
            Fields=fields,
            Conditions=conditions,
            ExpiresIn=self.upload_ttl_seconds,
        )

    def head(self, key: str) -> dict:
        return self.s3.head_object(
            Bucket=self.bucket,
            Key=key,
            ChecksumMode="ENABLED",
        )

    def read_prefix(self, key: str, length: int = 16) -> bytes:
        response = self.s3.get_object(
            Bucket=self.bucket,
            Key=key,
            Range=f"bytes=0-{max(length - 1, 0)}",
        )
        return response["Body"].read(length)

    def copy(self, source_key: str, destination_key: str) -> None:
        self.s3.copy_object(
            Bucket=self.bucket,
            Key=destination_key,
            CopySource={"Bucket": self.bucket, "Key": source_key},
            ServerSideEncryption="AES256",
            MetadataDirective="COPY",
        )

    def delete(self, key: str) -> None:
        self.s3.delete_object(Bucket=self.bucket, Key=key)

    def create_view_url(
        self,
        *,
        key: str,
        original_name: str,
        mime_type: str,
    ) -> str:
        safe_name = quote(original_name, safe="")
        return self.s3.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": self.bucket,
                "Key": key,
                "ResponseContentType": mime_type,
                "ResponseContentDisposition": (
                    f"inline; filename*=UTF-8''{safe_name}"
                ),
            },
            ExpiresIn=self.view_ttl_seconds,
        )
