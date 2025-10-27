from .ErrorService import ErrorService
from .SuccessService import SuccessService
from sqlalchemy.orm import Session
from app.models import Currency

class CurrencyService:
  def __init__(self, db: Session, req_user: dict):
    self.db = db
    self.req_user = req_user
    self.error = ErrorService()
    self.success = SuccessService()
  
  def get_all(self):
    currencies_model = self.db.query(Currency).all()
    return currencies_model