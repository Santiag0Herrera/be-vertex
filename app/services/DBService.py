from sqlalchemy.orm import Session
from .UserService import UserService
from .TransactionsService import TransactionsService

class DBService:
  db: Session
  req_user: dict
  users: UserService
  trx: TransactionsService
  
  def __init__(self, db, req_user):
    self.db = db
    self.req_user = req_user
    self.users = UserService(db, req_user)
    self.trx = TransactionsService(db, req_user)