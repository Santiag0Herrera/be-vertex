from .ErrorService import ErrorService
from .SuccessService import SuccessService
from sqlalchemy.orm import Session
from app.models import CustomersBalance, Clients, FeeWithdrawals, Payments, Trx, Users
from sqlalchemy.orm import joinedload
from app.schemas.customerBalance import CustomerBalanceCreateRequest, FeeWithdrawalRequest

class CustomerBalanceService:
  def __init__(self, db: Session, req_user: dict):
    self.db = db
    self.req_user = req_user
    self.error = ErrorService()
    self.success = SuccessService()
  
  def _get_balance(self, id):
    balance_model = self.db.query(CustomersBalance).filter(
      CustomersBalance.id == id,
      CustomersBalance.enabled == True
    ).first()
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
      .filter(Clients.enabled == True)
      .filter(Clients.entity_id == entity_id)
      .filter(CustomersBalance.enabled == True)
      .options(
        joinedload(CustomersBalance.client), 
        joinedload(CustomersBalance.currency)
      )
      .all()
    )
    return balances_model


  def get_all_movements(self, account_id: int):
    balance_model = (
      self.db.query(CustomersBalance)
      .join(CustomersBalance.client)
      .join(CustomersBalance.currency)
      .filter(Clients.enabled == True)
      .filter(Clients.entity_id == self.req_user.get("entity_id"))
      .filter(CustomersBalance.id == account_id)
      .filter(CustomersBalance.enabled == True)
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
      .filter(Trx.account_id == balance_model.id)
      .filter(Trx.status == "conciliado")
      .all()
    )
    # Pagos hechos (EGRESOS)
    payments = (
      self.db.query(Payments)
      .filter(Payments.customer_balance_id == balance_model.id)
      .all()
    )
    fee_withdrawals = (
      self.db.query(FeeWithdrawals)
      .filter(FeeWithdrawals.customer_balance_id == balance_model.id)
      .all()
    )
    # Combinar ambos en un solo resultado (opcional: los podés ordenar por fecha después)
    combined = []
    for trx in trxs:
      combined.append({
        "type": "Transaccion",
        "amount": f"{balance_model.currency.name} {trx.amount}",
        "fee_amount": trx.fee_amount,
        "net_amount": trx.amount - (trx.fee_amount or 0),
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
    for withdrawal in fee_withdrawals:
      combined.append({
        "type": "Retiro de comision",
        "amount": f"{balance_model.currency.name} {withdrawal.amount}",
        "date": withdrawal.date,
        "status": withdrawal.status
      })
    # Ordenar por fecha descendente
    combined.sort(key=lambda x: str(x["date"]), reverse=True)
    return {"status": "ok", "data": {
      "balance": balance_model,
      "movements": combined[:10]
    }}


  def create(
    self,
    customer_balance_request: CustomerBalanceCreateRequest
  ):
    client_model = self.db.query(Clients).filter(Clients.id == customer_balance_request.client_id).first()
    
    if client_model is None:
      return self.error.raise_not_found("Client")
    
    create_customer_balance = CustomersBalance(
      client_id=client_model.id,
      balance_amount=0,
      fee_amount=0,
      balance_currency_id=customer_balance_request.balance_currency_id,
      fee_percentage=customer_balance_request.fee_percentage
    )
    self.db.add(create_customer_balance)
    self.db.commit()
    return {'status': 'ok', 'result': "Balance creado correctamente."}
  

  def update_fee_percentage(self, balance_id: int, new_fee_percentage: float):
    balance_model = self._get_balance(balance_id)
    balance_model.fee_percentage = new_fee_percentage
    self.db.add(balance_model)
    self.db.commit()
    return {'status': 'ok', 'result': "Porcentaje de fee actualizado correctamente."}


  def delete(self, balance_id: int):
    balance_model = (
      self.db.query(CustomersBalance)
      .join(CustomersBalance.client)
      .filter(
        CustomersBalance.id == balance_id,
        Clients.entity_id == self.req_user.get("entity_id"),
        CustomersBalance.enabled == True
      )
      .first()
    )

    if balance_model is None:
      self.error.raise_not_found("Balance")

    balance_model.enabled = False
    self.db.add(balance_model)
    self.db.commit()
    return self.success.response("Balance deshabilitado correctamente.")


  def withdraw_fee(self, withdrawal_request: FeeWithdrawalRequest):
    user_model = self.db.query(Users).filter(
      Users.id == self.req_user.get("id"),
      Users.entity_id == self.req_user.get("entity_id"),
      Users.enabled == True
    ).first()

    if user_model is None:
      self.error.raise_forbidden("Solo un usuario activo puede retirar comisiones.")

    balance_model = (
      self.db.query(CustomersBalance)
      .join(CustomersBalance.client)
      .filter(
        CustomersBalance.id == withdrawal_request.customer_balance_id,
        CustomersBalance.enabled == True,
        Clients.enabled == True,
        Clients.entity_id == self.req_user.get("entity_id")
      )
      .with_for_update(of=CustomersBalance)
      .first()
    )

    if balance_model is None:
      self.error.raise_not_found("Balance")

    if withdrawal_request.amount > balance_model.fee_amount:
      self.error.raise_conflict(
        "El monto a retirar supera la comision disponible."
      )

    balance_model.fee_amount = round(
      balance_model.fee_amount - withdrawal_request.amount,
      2
    )
    balance_model.last_update = withdrawal_request.date

    withdrawal_model = FeeWithdrawals(
      customer_balance_id=balance_model.id,
      withdrawn_by_user_id=user_model.id,
      entity_id=self.req_user.get("entity_id"),
      currency_id=balance_model.balance_currency_id,
      amount=withdrawal_request.amount,
      date=withdrawal_request.date,
      status="consolidado"
    )

    self.db.add(balance_model)
    self.db.add(withdrawal_model)
    self.db.commit()
    self.db.refresh(withdrawal_model)

    return self.success.response({
      "message": "Comision retirada correctamente.",
      "fee_amount": balance_model.fee_amount,
      "withdrawal": {
        "id": withdrawal_model.id,
        "customer_balance_id": withdrawal_model.customer_balance_id,
        "amount": withdrawal_model.amount,
        "date": withdrawal_model.date,
        "currency_id": withdrawal_model.currency_id,
        "status": withdrawal_model.status
      }
    })


  def get_fee_withdrawals(self, balance_id: int):
    balance_model = (
      self.db.query(CustomersBalance)
      .join(CustomersBalance.client)
      .filter(
        CustomersBalance.id == balance_id,
        CustomersBalance.enabled == True,
        Clients.entity_id == self.req_user.get("entity_id")
      )
      .first()
    )

    if balance_model is None:
      self.error.raise_not_found("Balance")

    withdrawals = (
      self.db.query(FeeWithdrawals)
      .filter(FeeWithdrawals.customer_balance_id == balance_id)
      .options(
        joinedload(FeeWithdrawals.withdrawn_by_user),
        joinedload(FeeWithdrawals.currency)
      )
      .order_by(FeeWithdrawals.date.desc(), FeeWithdrawals.id.desc())
      .all()
    )

    return self.success.response([
      {
        "id": withdrawal.id,
        "customer_balance_id": withdrawal.customer_balance_id,
        "amount": withdrawal.amount,
        "date": withdrawal.date,
        "currency_id": withdrawal.currency_id,
        "status": withdrawal.status,
        "withdrawn_by_user_id": withdrawal.withdrawn_by_user_id,
        "withdrawn_by_user": {
          "id": withdrawal.withdrawn_by_user.id,
          "first_name": withdrawal.withdrawn_by_user.first_name,
          "last_name": withdrawal.withdrawn_by_user.last_name,
          "email": withdrawal.withdrawn_by_user.email
        },
        "currency": {
          "id": withdrawal.currency.id,
          "name": withdrawal.currency.name
        }
      }
      for withdrawal in withdrawals
    ])
