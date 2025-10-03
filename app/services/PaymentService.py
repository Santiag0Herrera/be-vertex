from .ErrorService import ErrorService
from .SuccessService import SuccessService
from .CustomerBalanceService import CustomerBalanceService
from app.models import Payments
from sqlalchemy.orm import Session
from app.schemas.payments import NewPaymentRequest

class PaymentService:
  def __init__(self, db: Session, req_user: dict):
    self.db = db
    self.req_user = req_user
    self.error = ErrorService()
    self.success = SuccessService()
    self.customer_balance_service = CustomerBalanceService(db, req_user)

  def create(self, payment_request: NewPaymentRequest):
    # VALIDAR QUE LAS CURRENCIES SEAN CONGRUENTES Y QUE PERTENEZCAN A LAS MISMA ENTIDAD
    create_payment_model = Payments(
      payee_user_id = self.req_user.get("id"),
      amount = payment_request.amount,
      date = payment_request.date,
      status = "consolidado",
      entity_id = self.req_user.get("entity_id"),
      customer_balance_id = payment_request.customer_balance_id,
      currency_id = payment_request.currency_id,
    )
    self.db.add(create_payment_model)
    self.db.commit()
    balance_id = payment_request.customer_balance_id
    payment_amount = payment_request.amount
    self.customer_balance_service.subtract_amount(balance_id, payment_amount)
    return self.success.response("Pago creado correctamente")
  
  def get_all(self):
    payments_model = self.db.query(Payments).filter()