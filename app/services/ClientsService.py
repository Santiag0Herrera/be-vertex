from app.models import Permission, Users

from sqlalchemy.orm import Session
from .ErrorService import ErrorService
from .SuccessService import SuccessService

class ClientService():
  db: Session
  req_user: dict
  error: ErrorService
  success: SuccessService

  def __init__(self, db: Session, req_user: dict):
    self.db = db
    self.req_user = req_user
    self.error = ErrorService()
    self.success = SuccessService()
  
  def get_all(self):
    perm_model = self.db.query(Permission).filter(
      Permission.level == 'client'
    ).first()
    self.error.raise_if_none(perm_model, "Permissions")
    
    clients_model = self.db.query(Users).filter(
      Users.perm_id == perm_model.id, 
      Users.entity_id == self.req_user.get('entity_id')
    ).all()
    self.error.raise_if_none(clients_model, "Clients")
    
    return clients_model