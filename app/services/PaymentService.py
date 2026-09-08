from datetime import datetime
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy.orm import Session, lazyload

from .SuccessService import SuccessService
from app.models import Payments, CustomersBalance, Clients, Users
from app.schemas.payments import NewPaymentRequest


class PaymentService:
    def __init__(self, db: Session, req_user: dict):
        self.db = db
        self.req_user = req_user
        self.success = SuccessService()

    def require_user(self):
        if self.req_user.get("account_type") != "user" or not self.db.query(Users).filter(
            Users.id == self.req_user.get("id"),
            Users.entity_id == self.req_user.get("entity_id"),
            Users.enabled == True,
        ).first():
            raise HTTPException(403, "Solo un usuario activo puede ejecutar pagos.")

    def get_balance(self, balance_id):
        balance = self.db.query(CustomersBalance).options(lazyload(CustomersBalance.client)).join(Clients).filter(
            CustomersBalance.id == balance_id,
            CustomersBalance.enabled == True,
            Clients.enabled == True,
            Clients.entity_id == self.req_user.get("entity_id"),
        ).populate_existing().with_for_update(of=CustomersBalance).first()
        if balance is None:
            raise HTTPException(404, "Cuenta no encontrada.")
        return balance

    def create_record(self, payment_request, payment_order_id=None):
        """Stage the existing payment flow; the caller owns commit/rollback."""
        self.require_user()
        balance = self.get_balance(payment_request.customer_balance_id)
        amount = Decimal(str(payment_request.amount))
        available = Decimal(str(balance.balance_amount))
        if not amount.is_finite() or amount <= 0:
            raise HTTPException(422, "El monto debe ser positivo y finito.")
        if balance.balance_currency_id != payment_request.currency_id:
            raise HTTPException(409, "La moneda no coincide con la cuenta.")
        if amount > available:
            raise HTTPException(409, "El monto supera el saldo disponible.")
        payment = Payments(
            payee_user_id=self.req_user.get("id"), amount=float(amount),
            date=payment_request.date, status="consolidado",
            entity_id=self.req_user.get("entity_id"),
            customer_balance_id=balance.id, currency_id=balance.balance_currency_id,
            payment_order_id=payment_order_id,
        )
        balance.balance_amount = float(available - amount)
        balance.last_update = datetime.utcnow()
        self.db.add(payment)
        self.db.flush()
        return payment

    def create(self, payment_request: NewPaymentRequest):
        try:
            self.create_record(payment_request)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return self.success.response("Pago creado correctamente")

    def get_all(self):
        return self.db.query(Payments).filter(Payments.entity_id == self.req_user.get("entity_id")).all()
