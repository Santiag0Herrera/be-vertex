from pydantic import BaseModel, Field, field_validator
from datetime import date as dt_date, datetime
from typing import Optional

class DocumentRequest(BaseModel):
  amount: float = Field(..., gt=0, description="Transaction amount, must be greater than 0")
  trx_id: Optional[str] = None
  emisor_name: Optional[str] = None
  emisor_cuit: Optional[str] = None
  emisor_cbu: Optional[str] = None
  receptor_name: Optional[str] = None
  receptor_cuit: Optional[str] = None
  receptor_cbu: Optional[str] = None
  date: dt_date = Field(..., description="Transaction date in YYYY-MM-DD format")
  account_id: Optional[int] = None

  @field_validator("date", mode="before")
  @classmethod
  def normalize_date(cls, value):
    if isinstance(value, datetime):
      return value.date()
    if isinstance(value, str):
      raw = value.strip()
      # Accept ISO datetimes from extractor: 2024-09-25T10:34:13
      try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
      except ValueError:
        pass
      # Accept plain date
      try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
      except ValueError:
        pass
    return value


class MultipleDocumentRequest(BaseModel):
  transactions: list[DocumentRequest]
  account_id: int

class UploadDocumentRequest(BaseModel):
  base64: str
  name: str
  ext: str

class MovementsRequest(BaseModel):
  account_number: str
  bank_number: str
  date_since: Optional[str]
  date_until: Optional[str]


class AllMovementsRequest:
  date_since: Optional[str]
  date_until: Optional[str]
