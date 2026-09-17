from app.models import Entity

from sqlalchemy.orm import Session
from .ErrorService import ErrorService
from .SuccessService import SuccessService

class EntitiesService():
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
    query = self.db.query(Entity)
    if self.req_user.get('user_perm') != 'super':
      query = query.filter(Entity.id == self.req_user.get('entity_id'))
    entities_model = query.all()
    return self.success.response(entities_model)
  
  def get_by_id(self, entity_id: int):
    query = self.db.query(Entity).filter(Entity.id == entity_id)
    if self.req_user.get('user_perm') != 'super':
      query = query.filter(Entity.id == self.req_user.get('entity_id'))
    entity_model = query.first()
    self.error.raise_if_none(entity_model, "Entity")
    return self.success.response(entity_model)
