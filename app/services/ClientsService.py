from typing import List
from sqlalchemy import select
from app.models import Clients
from sqlalchemy.orm import Session
from .ErrorService import ErrorService
from .SuccessService import SuccessService
from app.schemas.auth import ReqUser
from app.schemas.clients import ClientResponse, NewClientRequest
from app.services.auth_service import bcrypt_context

class ClientService():
  db: Session
  req_user: ReqUser
  error: ErrorService
  success: SuccessService

  def __init__(self, db: Session, req_user: dict):
    self.db = db
    self.req_user = req_user
    self.error = ErrorService()
    self.success = SuccessService()
  

  def get_all(self) -> List[ClientResponse]:
    stmt = select(Clients).where(Clients.entity_id == self.req_user.get("entity_id"))
    clients_model = self.db.execute(stmt).scalars().all()
    return clients_model


  def create(self, new_client_request: NewClientRequest):
    """
    Creates a new client in the requesting client's entity.
    """
    client_exists_model = self.db.query(Clients).filter(
      Clients.email == new_client_request.email
    ).first()

    if client_exists_model:
      self.error.raise_conflict(f"Cliente {client_exists_model.email} ya existe.")
    
    auto_generated_password = (new_client_request.first_name[:2] + new_client_request.last_name + "123").lower()

    create_client_model = Clients(
      first_name=new_client_request.first_name,
      last_name=new_client_request.last_name,
      email=new_client_request.email,
      hashed_password=bcrypt_context.hash(auto_generated_password),
      phone=new_client_request.phone,
      perm_id=2,
      entity_id=self.req_user.get('entity_id')
    )

    self.db.add(create_client_model)
    self.db.commit()
    return self.success.response({'message': 'Cliente creado con exito!', 'generated_password': auto_generated_password})