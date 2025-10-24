from pydantic import BaseModel, Field
from datetime import date as dt_date
from typing import Optional

class DocumentRequest(BaseModel):
  amount: float = Field(..., gt=0, description="Transaction amount, must be greater than 0")
  trx_id: str = Field(..., min_length=4, description="Unique transaction ID from the comprobante")
  emisor_name: str = Field(..., min_length=1, description="Name of the sender")
  emisor_cuit: str = Field(..., pattern=r"^\d{11}$", description="CUIT of the sender, must be 11 digits")
  emisor_cbu: Optional[str] = Field(None, pattern=r"^\d{22}$")
  receptor_name: str = Field(..., min_length=1, description="Name of the receiver")
  receptor_cuit: str = Field(..., pattern=r"^\d{11}$", description="CUIT of the receiver, must be 11 digits")
  receptor_cbu: Optional[str] = Field(None, pattern=r"^\d{22}$")
  date: dt_date = Field(..., description="Transaction date in YYYY-MM-DD format")

class MultipleDocumentRequest(DocumentRequest):
  account_id: int

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
  customer_id: str