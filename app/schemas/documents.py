from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints, field_validator

from app.text_sanitization import remove_nul_characters


Sha256Hex = Annotated[
    str,
    StringConstraints(pattern=r"^[0-9a-fA-F]{64}$"),
]


class UploadDocumentRequest(BaseModel):
    client_document_id: UUID
    original_name: str = Field(..., min_length=1, max_length=255)
    mime_type: str = Field(..., min_length=1, max_length=100)
    size_bytes: int = Field(..., gt=0)
    sha256: Sha256Hex

    @field_validator("original_name", mode="before")
    @classmethod
    def normalize_original_name(cls, value: str) -> str:
        value = remove_nul_characters(value)
        if not isinstance(value, str):
            return value
        normalized = value.replace("\\", "/").split("/")[-1].strip()
        if not normalized or normalized in {".", ".."}:
            raise ValueError("Invalid original file name")
        return normalized

    @field_validator("mime_type", mode="before")
    @classmethod
    def normalize_mime_type(cls, value: str) -> str:
        value = remove_nul_characters(value)
        if not isinstance(value, str):
            return value
        return value.strip().lower()

    @field_validator("sha256")
    @classmethod
    def normalize_sha256(cls, value: str) -> str:
        return value.lower()


class CreateUploadSessionRequest(BaseModel):
    documents: list[UploadDocumentRequest] = Field(..., min_length=1)


class RefreshUploadSessionRequest(BaseModel):
    client_document_ids: list[UUID] | None = None
