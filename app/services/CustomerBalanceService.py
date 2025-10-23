from .ErrorService import ErrorService
from .SuccessService import SuccessService
from sqlalchemy.orm import Session
from app.models import CustomersBalance, Clients, Payments, Trx
from sqlalchemy.orm import joinedload
from app.schemas.customerBalance import CustomerBalanceCreateRequest

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

  def get_all(self):
    entity_id = self.req_user.get("entity_id")
    balances_model = (
      self.db.query(CustomersBalance)
      .join(CustomersBalance.client)
      .join(CustomersBalance.currency)
      .filter(Clients.entity_id == entity_id)
      .options(
        joinedload(CustomersBalance.client), 
        joinedload(CustomersBalance.currency)
      )
      .all()
    )
    return balances_model
  
  def get_all_movements(self, client_id: int):
    balance_model = (
      self.db.query(CustomersBalance)
      .join(CustomersBalance.client)
      .join(CustomersBalance.currency)
      .filter(CustomersBalance.client_id == client_id)
      .options(
        joinedload(CustomersBalance.client), 
        joinedload(CustomersBalance.currency)
      )
      .first()
    )

    if balance_model is None:
      return {"status": "ok", "data": None}
    
    # Movimientos de ingresos (TRX)
    trxs = (
      self.db.query(Trx)
      .filter(Trx.client_id == client_id)
      .limit(20)
      .all()
    )

    # Pagos hechos (EGRESOS)
    payments = (
      self.db.query(Payments)
      .join(CustomersBalance)
      .filter(CustomersBalance.client_id == client_id)
      .limit(20)
      .all()
    )

    # Combinar ambos en un solo resultado (opcional: los podés ordenar por fecha después)
    combined = []
    for trx in trxs:
      combined.append({
        "type": "Transaccion",
        "amount": f"{balance_model.currency.name} {trx.amount}",
        "date": trx.date,
        "status": trx.status,
      })

    for payment in payments:
      combined.append({
        "type": "Pago",
        "amount": f"{balance_model.currency.name} {payment.amount}",
        "date": payment.date,
        "status": payment.status
      })

    # Ordenar por fecha descendente
    combined.sort(key=lambda x: str(x["date"]), reverse=True)

    return {"status": "ok", "data": {
      "balance": balance_model,
      "movements": combined[:10]
    }}
  
  def create(
    self, 
    client_id: int, 
    customer_balance_request: CustomerBalanceCreateRequest
  ):
    client_model = self.db.query(Clients).filter(Clients.id == client_id).first()
    
    if client_model is None:
      return self.error.raise_not_found("Client")
    
    create_customer_balance = CustomersBalance(
      client_id=client_model.id,
      balance_amount=customer_balance_request.balance_amount,
      balance_currency_id=customer_balance_request.balance_currency_id
    )
    self.db.add(create_customer_balance)
    self.db.commit()
    return {'status': 'ok', 'result': "Balance creado correctamente."}