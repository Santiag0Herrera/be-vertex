from typing import List
from sqlalchemy import select
from app.models import Clients
from sqlalchemy.orm import Session
from .ErrorService import ErrorService
from .SuccessService import SuccessService
from app.schemas.auth import ReqUser
from app.schemas.clients import ClientResponse

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