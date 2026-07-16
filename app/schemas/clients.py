from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

class ClientResponse(BaseModel):
  model_config = ConfigDict(from_attributes=True)

  id: int
  first_name: str
  last_name: str
  phone: str
  email: str
  cuit: Optional[str] = None
  perm_id: int
  entity_id: int

class NewClientRequest(BaseModel):
  first_name: str
  last_name: str
  email: str
  phone: str
  cuit: str = Field(..., min_length=11, max_length=11, pattern=r'^\d{11}$')

class UpdateClientRequest(BaseModel):
  model_config = ConfigDict(extra='forbid')

  first_name: str
  last_name: str
  phone: str
  cuit: str = Field(..., min_length=11, max_length=11, pattern=r'^\d{11}$')
