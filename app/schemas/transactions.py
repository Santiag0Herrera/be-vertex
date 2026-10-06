from pydantic import BaseModel, Field, field_validator
from datetime import date as dt_date, datetime
from typing import Optional
from zoneinfo import ZoneInfo


BUSINESS_TIMEZONE = ZoneInfo("America/Argentina/Buenos_Aires")

class DocumentRequest(BaseModel):
  document_name: Optional[str] = None
  file_sha256: Optional[str] = Field(None, pattern=r"^[0-9a-fA-F]{64}$")
  receipt_fingerprint: Optional[str] = Field(None, pattern=r"^[0-9a-fA-F]{64}$")
  amount: float = Field(..., gt=0, description="Transaction amount, must be greater than 0")
  trx_id: Optional[str] = None
  emisor_name: Optional[str] = None
  emisor_cuit: Optional[str] = None
  emisor_cbu: Optional[str] = None
  receptor_name: Optional[str] = None
  receptor_cuit: Optional[str] = None
  receptor_cbu: Optional[str] = None
  date: datetime = Field(..., description="Transaction date and time in ISO format")
  received_date: Optional[dt_date] = Field(
    None,
    description="Date when the receipt was received from the client in YYYY-MM-DD format",
  )
  account_id: Optional[int] = None

  @field_validator("date", mode="before")
  @classmethod
  def normalize_transaction_datetime(cls, value):
    if value is None:
      return value
    if isinstance(value, datetime):
      return value.replace(tzinfo=None) if value.tzinfo is not None else value
    if isinstance(value, dt_date):
      return datetime.combine(value, datetime.min.time())
    if isinstance(value, str):
      raw = value.strip()
      try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=None) if parsed.tzinfo is not None else parsed
      except ValueError:
        return value
    return value

  @field_validator("received_date", mode="before")
  @classmethod
  def normalize_received_date(cls, value):
    if value is None:
      return value
    if isinstance(value, datetime):
      return value.date()
    if isinstance(value, str):
      raw = value.strip()
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

  @field_validator("received_date")
  @classmethod
  def validate_received_date(cls, value):
    if value is not None and value > datetime.now(BUSINESS_TIMEZONE).date():
      raise ValueError("La fecha de recepción no puede ser futura")
    return value


class MultipleDocumentRequest(BaseModel):
  transactions: list[DocumentRequest]
  account_id: int
  owner_account_number: str
  document_name: Optional[str] = None

class MovementsRequest(BaseModel):
  account_number: str
  bank_number: str
  date_since: Optional[str]
  date_until: Optional[str]


class ReconciliationJobResponse(BaseModel):
  checked: int
  conciliated: int
  repeated: int
  expired: int
  skipped: int
  still_pending: int
  duration_seconds: float
