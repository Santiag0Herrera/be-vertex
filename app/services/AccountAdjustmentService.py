from datetime import datetime
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload, lazyload

from .ErrorService import ErrorService
from .SuccessService import SuccessService
from app.models import AccountAdjustments, Clients, CustomersBalance, Entity, Users
from app.schemas.adjustments import AnnulAdjustmentRequest, NewAdjustmentRequest

TYPE_PREFIX = {"credito": "NC", "debito": "ND"}
CENTS = Decimal("0.01")


class AccountAdjustmentService:
  """Notas de crédito/débito internas: ajustan el saldo sin pago ni transacción."""

  def __init__(self, db: Session, req_user: dict):
    self.db = db
    self.req_user = req_user
    self.error = ErrorService()
    self.success = SuccessService()

  # ---- helpers ----

  def _require_admin(self):
    if self.req_user.get("account_type") != "user" or self.req_user.get("user_perm") not in {"admin", "super"}:
      self.error.raise_forbidden("Solo un administrador puede emitir o anular notas.")
    user = self.db.query(Users).filter(
      Users.id == self.req_user.get("id"),
      Users.entity_id == self.req_user.get("entity_id"),
      Users.enabled == True,
    ).first()
    if user is None:
      self.error.raise_forbidden("Solo un usuario activo puede emitir o anular notas.")
    return user

  def _require_internal(self):
    if self.req_user.get("account_type") != "user":
      self.error.raise_forbidden("Este endpoint es exclusivo para usuarios internos.")

  def _lock_balance(self, balance_id: int) -> CustomersBalance:
    balance = (
      self.db.query(CustomersBalance)
      .options(lazyload(CustomersBalance.client))
      .join(Clients)
      .filter(
        CustomersBalance.id == balance_id,
        CustomersBalance.enabled == True,
        Clients.enabled == True,
        Clients.entity_id == self.req_user.get("entity_id"),
      )
      .populate_existing()
      .with_for_update(of=CustomersBalance)
      .first()
    )
    if balance is None:
      self.error.raise_not_found("Cuenta")
    return balance

  def _next_number(self, adjustment_type: str) -> int:
    entity_id = self.req_user.get("entity_id")
    # Serializa la numeración por entidad aunque las notas sean de cuentas distintas.
    self.db.query(Entity).filter(Entity.id == entity_id).with_for_update().first()
    current = self.db.query(func.max(AccountAdjustments.number)).filter(
      AccountAdjustments.entity_id == entity_id,
      AccountAdjustments.type == adjustment_type,
    ).scalar()
    return (current or 0) + 1

  @staticmethod
  def _clean_text(value: str | None):
    if value is None:
      return None
    value = value.strip()
    return value or None

  @staticmethod
  def label(adjustment: AccountAdjustments) -> str:
    return f"{TYPE_PREFIX[adjustment.type]}-{adjustment.number:04d}"

  @classmethod
  def serialize(cls, adjustment: AccountAdjustments) -> dict:
    def user_info(user):
      if user is None:
        return None
      return {"id": user.id, "first_name": user.first_name, "last_name": user.last_name, "email": user.email}

    return {
      "id": adjustment.id,
      "label": cls.label(adjustment),
      "type": adjustment.type,
      "number": adjustment.number,
      "customer_balance_id": adjustment.customer_balance_id,
      "client_id": adjustment.client_id,
      "currency": {"id": adjustment.currency.id, "name": adjustment.currency.name} if adjustment.currency else None,
      "amount": float(adjustment.amount),
      "reason": adjustment.reason,
      "reference": adjustment.reference,
      "date": adjustment.date,
      "balance_before": float(adjustment.balance_before),
      "balance_after": float(adjustment.balance_after),
      "status": adjustment.status,
      "created_at": adjustment.created_at,
      "created_by_user": user_info(adjustment.created_by_user),
      "annulled_at": adjustment.annulled_at,
      "annulled_by_user": user_info(adjustment.annulled_by_user),
      "annul_reason": adjustment.annul_reason,
    }

  def _get_adjustment(self, adjustment_id: int, for_update: bool = False) -> AccountAdjustments:
    query = self.db.query(AccountAdjustments).filter(
      AccountAdjustments.id == adjustment_id,
      AccountAdjustments.entity_id == self.req_user.get("entity_id"),
    )
    if for_update:
      query = query.populate_existing().with_for_update()
    adjustment = query.first()
    if adjustment is None:
      self.error.raise_not_found("Nota")
    return adjustment

  # ---- public API ----

  def create(self, request: NewAdjustmentRequest):
    try:
      user = self._require_admin()
      reason = self._clean_text(request.reason)
      if reason is None:
        self.error.raise_bad_request("El motivo es obligatorio.")
      balance = self._lock_balance(request.customer_balance_id)
      if balance.balance_currency_id != request.currency_id:
        self.error.raise_conflict("La moneda no coincide con la cuenta.")

      amount = Decimal(request.amount).quantize(CENTS)
      before = Decimal(str(balance.balance_amount)).quantize(CENTS)
      if request.type == "credito":
        after = before + amount
      else:
        if amount > before:
          self.error.raise_conflict("El monto de la nota de débito supera el saldo disponible.")
        after = before - amount

      adjustment = AccountAdjustments(
        entity_id=self.req_user.get("entity_id"),
        client_id=balance.client_id,
        customer_balance_id=balance.id,
        currency_id=balance.balance_currency_id,
        type=request.type,
        number=self._next_number(request.type),
        amount=amount,
        reason=reason,
        reference=self._clean_text(request.reference),
        date=request.date,
        balance_before=before,
        balance_after=after,
        status="emitida",
        created_by_user_id=user.id,
      )
      balance.balance_amount = float(after)
      balance.last_update = datetime.utcnow()
      self.db.add(adjustment)
      self.db.commit()
    except Exception:
      self.db.rollback()
      raise
    self.db.refresh(adjustment)
    return self.success.response(self.serialize(adjustment))

  def annul(self, request: AnnulAdjustmentRequest):
    try:
      user = self._require_admin()
      reason = self._clean_text(request.reason)
      if reason is None:
        self.error.raise_bad_request("El motivo de anulación es obligatorio.")
      adjustment = self._get_adjustment(request.adjustment_id, for_update=True)
      if adjustment.status == "anulada":
        self.error.raise_conflict("La nota ya está anulada.")
      balance = self._lock_balance(adjustment.customer_balance_id)

      amount = Decimal(str(adjustment.amount)).quantize(CENTS)
      current = Decimal(str(balance.balance_amount)).quantize(CENTS)
      if adjustment.type == "credito":
        # Revertir una NC resta saldo: puede que ya se haya pagado.
        if amount > current:
          self.error.raise_conflict("No se puede anular: el saldo actual es menor al monto de la nota de crédito.")
        balance.balance_amount = float(current - amount)
      else:
        balance.balance_amount = float(current + amount)
      balance.last_update = datetime.utcnow()

      adjustment.status = "anulada"
      adjustment.annulled_at = datetime.utcnow()
      adjustment.annulled_by_user_id = user.id
      adjustment.annul_reason = reason
      self.db.commit()
    except Exception:
      self.db.rollback()
      raise
    self.db.refresh(adjustment)
    return self.success.response(self.serialize(adjustment))

  def get_all(self, balance_id: int):
    self._require_internal()
    balance = self.db.query(CustomersBalance).join(Clients).filter(
      CustomersBalance.id == balance_id,
      Clients.entity_id == self.req_user.get("entity_id"),
    ).first()
    if balance is None:
      self.error.raise_not_found("Cuenta")
    adjustments = (
      self.db.query(AccountAdjustments)
      .filter(AccountAdjustments.customer_balance_id == balance_id)
      .options(
        joinedload(AccountAdjustments.currency),
        joinedload(AccountAdjustments.created_by_user),
        joinedload(AccountAdjustments.annulled_by_user),
      )
      .order_by(AccountAdjustments.date.desc(), AccountAdjustments.id.desc())
      .all()
    )
    return self.success.response([self.serialize(a) for a in adjustments])

  def get_detail(self, adjustment_id: int):
    self._require_internal()
    return self.success.response(self.serialize(self._get_adjustment(adjustment_id)))
