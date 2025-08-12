from app.models import Entity, CBU
from app.schemas.entities import NewEntityRequest

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
    entities_model = self.db.query(Entity).all()
    return entities_model
  
  def get_by_id(self, entity_id: int):
    entity_model = self.db.query(Entity).filter(
      Entity.id == entity_id
    ).first()
    self.success.response(entity_model, "Entity")
    return entity_model
  
  def create(self, entity_request: NewEntityRequest):
    entity_exists_model = self.db.query(Entity).filter(Entity.mail == entity_request.mail).first()
    if entity_exists_model is not None:
      self.error.raise_conflict(f"Entity with mail {entity_request.mail} already exists")

    create_cbu_model = CBU(
      nro=entity_request.cbu_number,
      banco=entity_request.cbu_bank_account,
      alias=entity_request.cbu_alias,
      cuit=entity_request.cbu_cuit
    )

    try:
      self.db.add(create_cbu_model)
      self.db.commit()
    except Exception as e:
      self.db.rollback()
      raise e
    
    create_entity_model = Entity(
      name=entity_request.name,
      mail=entity_request.mail,
      phone=entity_request.phone,
      products=entity_request.products, 
      status=entity_request.status,
      cbu_id=create_cbu_model.id,
    )
    
    try:
      self.db.add(create_entity_model)
      self.db.commit()
      self.db.refresh(create_entity_model)
    except Exception as e:
      self.db.rollback()
      raise e