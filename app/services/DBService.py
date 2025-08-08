from sqlalchemy.orm import Session
from .UserService import UserService

class DBService:
  db: Session
  req_user: dict
  users: UserService
  
  def __init__(self, db, req_user):
    self.db = db
    self.req_user = req_user
    self.users = UserService(db, req_user)
  



