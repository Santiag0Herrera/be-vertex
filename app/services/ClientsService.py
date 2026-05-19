from typing import List
from sqlalchemy import select
from app.models import Clients, Users, Permission, CustomersBalance
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
    stmt = select(Clients).where(Clients.entity_id == self.req_user.get("entity_id")).where(Clients.enabled == True)
    clients_model = self.db.execute(stmt).scalars().all()
    return clients_model


  def create(self, new_client_request: NewClientRequest):
    """
    Creates a new client in the requesting client's entity.
    """
    client_exists_model = self.db.query(Clients).filter(
      Clients.email == new_client_request.email.strip().lower()
    ).first()

    user_exists_model = self.db.query(Users).filter(
      Users.email == new_client_request.email.strip().lower()
    ).first()

    if client_exists_model or user_exists_model:
      self.error.raise_conflict(f"Cliente {new_client_request.email} ya existe.")
    
    auto_generated_password = (new_client_request.first_name[:2] + new_client_request.last_name + "123").lower()

    # Buscamos el id del permiso para clientes
    clients_permission_model = self.db.query(Permission).filter(Permission.level == 'client').first()

    create_client_model = Clients(
      first_name=new_client_request.first_name,
      last_name=new_client_request.last_name,
      email=new_client_request.email.strip().lower(),
      hashed_password=bcrypt_context.hash(auto_generated_password),
      phone=new_client_request.phone,
      perm_id=clients_permission_model.id,
      entity_id=self.req_user.get('entity_id')
    )

    self.db.add(create_client_model)
    self.db.commit()
    return self.success.response({'message': 'Cliente creado con exito!', 'generated_password': auto_generated_password})
  

  def delete(self, id_client: int):
    """
    Deletes client by client_id
    """
    client_model = self.db.query(Clients).filter(Clients.id == id_client).first()

    if client_model is None:
      self.error.raise_not_found("Cliente")
    
    client_model.enabled = False
    self.db.add(client_model)
    self.db.commit()
    return self.success.response(f"Cliente {client_model.first_name} {client_model.last_name} fue eliminado exitosamente.")
    
  
  def get_current(self):
    client_model = self.db.query(Clients).filter(
        Clients.id == self.req_user.get("id"),
        Clients.enabled == True
    ).first()

    if client_model is None:
        self.error.raise_not_found("Cliente")

    if client_model.entity is None:
        self.error.raise_not_found("Entidad asociada al cliente")

    return self.success.response({
        'id': client_model.id,
        'first_name': client_model.first_name,
        'last_name': client_model.last_name,
        'email': client_model.email,
        'permission_level': client_model.permission,
        'phone': client_model.phone,
        'accounts': [
            {
                'id': balance.id,
                'balance_amount': balance.balance_amount,
                'last_update': balance.last_update,
                'currency': {
                    'id': balance.currency.id,
                    'name': balance.currency.name
                } if balance.currency else None
            }
            for balance in client_model.balance
        ],
        'entity': {
            'name': client_model.entity.name,
            'id': client_model.entity.id,
            'accounts': [
                {
                    'id': entity_cbu.id,
                    'cbu': {
                        'id': entity_cbu.cbu.id,
                        'nro': entity_cbu.cbu.nro,
                        'banco': entity_cbu.cbu.banco,
                        'alias': entity_cbu.cbu.alias,
                        'cuit': entity_cbu.cbu.cuit
                    } if entity_cbu.cbu else None,
                    'currency': {
                        'id': entity_cbu.currency.id,
                        'name': entity_cbu.currency.name
                    } if entity_cbu.currency else None
                }
                for entity_cbu in client_model.entity.cbus
            ]
        }
    })