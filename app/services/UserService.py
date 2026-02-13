from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models import Users, Permission
from app.schemas.users import ChangePasswordRequest, CreateUserRequest, ChangePermissonRequest, ChangeUserInfoRequest
from app.services.auth_service import bcrypt_context

from .ErrorService import ErrorService
from .SuccessService import SuccessService

class UserService():
  def __init__(self, db: Session, req_user: dict):
    self.db = db
    self.req_user = req_user
    self.error = ErrorService()
    self.success = SuccessService()

  def get_all(self):
      """
      Gets all users from them same requesting users's entity.
      """
      users_model = self.db.query(Users).filter(
        Users.entity_id == self.req_user.get('entity_id')
      ).all()

      self.error.raise_if_none(users_model)
      
      return self.success.response(users_model)
  
  
  def get_current(self):
    """
    Gets the requesting user's info.
    """
    user_model = self.db.query(Users).filter(
      Users.id == self.req_user.get('id')
    ).first()
    
    self.error.raise_if_none(user_model)
    
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
    ).first() # func.lower(Users.email) → genera LOWER(email) en la query SQL.

    if not bcrypt_context.verify(change_password_request.password, user_model.hashed_password):
      self.error.raise_unauthorized('Incorrect password')
    
    user_model.hashed_password = bcrypt_context.hash(change_password_request.new_password)
    self.db.add(user_model)
    self.db.commit()
    return self.success.response('Password changed successfully!')
  

  def create(self, create_user_request: CreateUserRequest):
    """
    Creates a new user in the requesting user's entity.
    """
    user_exists_model = self.db.query(Users).filter(func.lower(Users.email) == create_user_request.email.lower()).first()
  
    if user_exists_model:
      self.error.raise_conflict(f"Usuario {create_user_request.email} ya existe.")
    
    auto_generated_password = (create_user_request.first_name[:2] + create_user_request.last_name + "123").lower()

    # Buscamos el id del permiso para usuarios
    users_permission_model = self.db.query(Permission).filter(Permission.level == 'users').first()

    create_user_model = Users(
      first_name=create_user_request.first_name,
      last_name=create_user_request.last_name,
      email=create_user_request.email.lower(),
      hashed_password=bcrypt_context.hash(auto_generated_password),
      phone=create_user_request.phone,
      perm_id=users_permission_model.id,
      entity_id=self.req_user.get('entity_id')
    )
    self.db.add(create_user_model)
    self.db.commit()
    return self.success.response({'message': 'Usuario creado con exito!', 'generated_password': auto_generated_password})
  

  def delete(self, user_id: int):
    if self.req_user.get("id") == user_id:
      self.error.raise_conflict("You can not delete your own user account.")
  
    user_model = self.db.query(Users).filter(Users.id == user_id).first()

    if user_model is None:
      self.error.raise_bad_request(f"User N°: {user_id} does not exist.")
    
    # Buscamos el id del permiso para clientes
    clients_permission_model = self.db.query(Permission).filter(Permission.level == 'client').first()

    if user_model.perm_id == clients_permission_model.id:
      self.error.raise_bad_request("The account is a client type.")
    
    self.db.delete(user_model)
    self.db.commit()
    return self.success.response(f"Usuario {user_model.first_name} {user_model.last_name} fue eliminado exitosamente.")
  

  def change_permission(self, change_permisson_request: ChangePermissonRequest):
    if self.req_user.get("id") == change_permisson_request.user_id:
      self.error.raise_bad_request("User can not change his own permission.")
    
    user_model = self.db.query(Users).filter(
      Users.id == change_permisson_request.user_id
    ).first()
    self.error.raise_if_none(user_model, f"User")
    
    if user_model.perm_id == change_permisson_request.perm_id:
      return self.error.raise_bad_request("User already has the selected permisson.")

    user_model.perm_id = change_permisson_request.perm_id
    self.db.add(user_model)
    self.db.commit()
    return self.success.response("Permisson changed successfully!")


  def change_info(self, change_user_info_request: ChangeUserInfoRequest):
    user_model = self.db.query(Users).filter(
      Users.id == self.req_user.get('id')
    ).first()
    self.error.raise_if_none(user_model, f"User")
    
    user_model.first_name = change_user_info_request.first_name
    user_model.last_name = change_user_info_request.last_name
    user_model.phone = change_user_info_request.phone
    self.db.add(user_model)
    self.db.commit()

    return self.success.response("User info updated")



