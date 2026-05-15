from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.schemas.transactions import DocumentRequest


class ExtractedField(BaseModel):
    key: str
    value: str
    confidence: Optional[float] = None


class ParseIssue(BaseModel):
    field: str
    message: str


class DocumentExtractResponse(BaseModel):
    ok: bool
    document: Optional[DocumentRequest] = None
    partial: Dict[str, Any] = Field(default_factory=dict)
    missing: List[str] = Field(default_factory=list)
    errors: List[ParseIssue] = Field(default_factory=list)
    raw_fields: List[ExtractedField] = Field(default_factory=list)
