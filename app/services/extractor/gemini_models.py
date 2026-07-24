from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict


class GeminiDocumentFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: Optional[str] = None
    trx_id: Optional[str] = None
    emisor_name: Optional[str] = None
    emisor_cuit: Optional[str] = None
    emisor_cbu: Optional[str] = None
    receptor_name: Optional[str] = None
    receptor_cuit: Optional[str] = None
    receptor_cbu: Optional[str] = None
    date: Optional[str] = None


def gemini_response_schema() -> dict:
    field_names = list(GeminiDocumentFields.model_fields)
    return {
        "type": "OBJECT",
        "properties": {
            field_name: {
                "type": "STRING",
                "nullable": True,
            }
            for field_name in field_names
        },
        "required": field_names,
    }
