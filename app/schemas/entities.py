from pydantic import BaseModel, Field

class DocumentRequest(BaseModel):
  base64: str = Field(min_length=10)
  type: str
  bank: str

class NewEntityRequest(BaseModel):
  name: str = Field(..., min_length=1, max_length=255)
  mail: str = Field(..., min_length=5, max_length=255, pattern=r'^\S+@\S+\.\S+$', examples=["email@domain.com"])
  phone: str = Field(..., min_length=10, max_length=25, pattern=r'^\+?\d{10,25}$')
  products: str = Field(..., min_length=1, max_length=255)
  status: str = Field(..., min_length=1, max_length=50)
  cbu_number: str = Field(..., min_length=22, max_length=22, pattern=r'^\d{22}$')
  cbu_bank_account: str = Field(..., min_length=1, max_length=255)
  cbu_alias: str = Field(..., min_length=1, max_length=255)
  cbu_cuit: str = Field(..., min_length=13, max_length=13, pattern=r'^\d{2}-\d{8}-\d{1}$')
