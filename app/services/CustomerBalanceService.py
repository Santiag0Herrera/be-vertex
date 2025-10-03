from .ErrorService import ErrorService
from .SuccessService import SuccessService
from sqlalchemy.orm import Session
from app.models import CustomersBalance

class CustomerBalanceService:
  def __init__(self, db: Session, req_user: dict):
    self.db = db
    self.req_user = req_user
    self.error = ErrorService()
    self.success = SuccessService()
  
  def _get_balance(self, id):
    balance_model = self.db.query(CustomersBalance).filter(CustomersBalance.id == id).first()
    self.error.raise_if_none(balance_model, "Balance")
    return balance_model

  def get_by_id(self, id):
    balance_model = self._get_balance(id)
    self.error.raise_if_none(balance_model, "Balance")
    return self.success.response(balance_model)

  def add_amount(self, id, amount_added):
    balance_model = self._get_balance(id)
    balance_model.balance_amount = balance_model.balance_amount + amount_added
    self.db.add(balance_model)
    self.db.commit()

  def subtract_amount(self, id, amount_added):
    balance_model = self._get_balance(id)
    balance_model.balance_amount = balance_model.balance_amount - amount_added
    self.db.add(balance_model)
    self.db.commit()