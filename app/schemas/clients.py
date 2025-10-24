from pydantic import BaseModel

class ClientResponse(BaseModel):
  id: int
  first_name: str
  last_name: str
  phone: str
  email: str
  perm_id: int
  entity_id: int

class Config:
  orm_mode = True  # permite usar instancias de SQLAlchemy directamente
    
class NewClientRequest(BaseModel):
  first_name: str
  last_name: str
  email: str
  phone: str