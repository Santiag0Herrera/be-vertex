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

