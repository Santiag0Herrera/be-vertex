from sqlalchemy.orm import Session
from .UserService import UserService
from .TransactionsService import TransactionsService
from .ProductsService import ProductsService
from .ClientsService import ClientService
from .EntitiesService import EntitiesService

class DBService:
  db: Session
  req_user: dict
  users: UserService
  trx: TransactionsService
  client: ClientService
  entities: EntitiesService
  
  def __init__(self, db, req_user):
    self.db = db
    self.req_user = req_user
    self.users = UserService(db, req_user)
    self.trx = TransactionsService(db, req_user)
    self.products = ProductsService(db, req_user)
    self.client = ClientService(db, req_user)
    self.entities = EntitiesService(db, req_user)