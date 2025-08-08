from sqlalchemy.orm import Session
from app.models import Users
from app.schemas.users import ChangePasswordRequest, CreateUserRequest
from app.services.auth_service import bcrypt_context

from .ErrorService import ErrorService
from .SuccessService import SuccessService

class UserService():
  def __init__(self, db: Session, req_user: dict):
    self.db = db
    self.req_user = req_user
    self.raise_error = ErrorService()
    self.success = SuccessService()

  def get_all(self):
      """
      Gets all users from them same requesting users's entity.
      """
      users_model = self.db.query(Users).filter(
        Users.entity_id == self.req_user.get('entity_id'),
        Users.perm_id != 3
      ).all()

      self.raise_error.raise_if_none(users_model)
      
      return self.success.response(users_model)
  
  def get_current(self):
    """
    Gets the requesting user's info.
    """
    user_model = self.db.query(Users).filter(
      Users.id == self.req_user.get('id')
    ).first()
    
    self.raise_error.raise_if_none(user_model)
    
    return self.success.response({
      'id': user_model.id,
      'first_name': user_model.first_name,
      'last_name': user_model.last_name,
      'email': user_model.email,
      'permission_level': user_model.permission,
      'phone': user_model.phone,
      'entity': {
        'name': user_model.entity.name,
        'id': user_model.entity.id
      }
    })
  
  def change_password(self, change_password_request: ChangePasswordRequest):
    """
    Changes requesting user's password
    """
    user_model = self.db.query(Users).filter(
      Users.id == self.req_user.get('id')
    ).first()

    if not bcrypt_context.verify(change_password_request.password, user_model.hashed_password):
      self.raise_error.raise_unauthorized('Incorrect password')
    
    user_model.hashed_password = bcrypt_context.hash(change_password_request.new_password)
    self.db.add(user_model)
    self.db.commit()
    return self.success.response('Password changed successfully!')
  
  def create(self, create_user_request: CreateUserRequest):
    """
    Creates a new user in the requesting user's entity.
    """
    user_exists_model = self.db.query(Users).filter(Users.email == create_user_request.email).first()
  
    if user_exists_model:
      self.raise_error.raise_conflict(f"Usuario {create_user_request.email} ya existe.")
    
    auto_generated_password = (create_user_request.first_name[:2] + create_user_request.last_name + "123").lower()

    create_user_model = Users(
      first_name=create_user_request.first_name,
      last_name=create_user_request.last_name,
      email=create_user_request.email,
      hashed_password=bcrypt_context.hash(auto_generated_password),
      phone=create_user_request.phone,
      perm_id=2,
      entity_id=self.req_user.get('entity_id')
    )
    self.db.add(create_user_model)
    self.db.commit()
    return self.success.response('User created successfully!')
  
  def delete(self, user_id: int):
    if self.req_user.get("id") == user_id:
      self.raise_error.raise_conflict("You can not delete your own user account.")
  
    user_model = self.db.query(Users).filter(Users.id == user_id).first()

    if user_model is None:
      self.raise_error.raise_bad_request(f"User N°: {user_id} does not exist.")
    
    if user_model.perm_id == 3:
      self.raise_error.raise_bad_request("The account is a client type.")
    
    self.db.delete(user_model)
    self.db.commit()
    return self.success.response(f"Usuario {user_model.first_name} {user_model.last_name} fue eliminado exitosamente.")