from pydantic import BaseModel, Field

class UserVerification(BaseModel):
  password: str
  new_password: str = Field(min_length=6)

class CreateUserRequest(BaseModel):
  first_name: str
  last_name: str
  email: str
  phone: str
