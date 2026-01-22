from pydantic import BaseModel, Field

class ChangePasswordRequest(BaseModel):
  password: str
  new_password: str = Field(min_length=6)

class CreateUserRequest(BaseModel):
  first_name: str
  last_name: str
  email: str
  phone: str

class ChangePermissonRequest(BaseModel):
  user_id: int
  perm_id: int

class ChangeUserInfoRequest(BaseModel):
  first_name: str
  last_name: str
  phone: str