from datetime import datetime
from decimal import Decimal

from fastapi import HTTPException

from app.models import PaymentOrders, Payments
from app.schemas.payments import NewPaymentRequest
from app.services.PaymentService import PaymentService
from app.services.SuccessService import SuccessService


class PaymentOrderService:
    def __init__(self, db, req_user):
        self.db = db
        self.req_user = req_user
        self.payments = PaymentService(db, req_user)

    def _query(self):
        query = self.db.query(PaymentOrders).filter(PaymentOrders.entity_id == self.req_user.get("entity_id"))
        if self.req_user.get("account_type") == "client":
            query = query.filter(PaymentOrders.client_id == self.req_user.get("id"))
        else:
            self.payments.require_user()
        return query

    def _serialize(self, order, payments=None):
        if payments is None:
            payments = (
                self.db.query(Payments)
                .filter(Payments.payment_order_id == order.id)
                .order_by(Payments.id)
                .all()
            )
        return {
            "id": order.id, "client_id": order.client_id,
            "customer_balance_id": order.customer_balance_id, "currency_id": order.currency_id,
            "amount": order.amount, "executed_amount": order.executed_amount,
            "remaining_amount": order.amount - order.executed_amount,
            "status": order.status, "created_at": order.created_at, "updated_at": order.updated_at,
            "payments": [{"id": p.id, "amount": p.amount, "date": p.date,
                          "payee_user_id": p.payee_user_id, "status": p.status} for p in payments],
        }

    def create(self, request):
        if self.req_user.get("account_type") != "client":
            raise HTTPException(403, "Solo los clientes pueden crear órdenes de pago.")
        try:
            balance = self.payments.get_balance(request.customer_balance_id)
            if balance.client_id != self.req_user.get("id"):
                raise HTTPException(404, "Cuenta no encontrada.")
            if request.amount > Decimal(str(balance.balance_amount)):
                raise HTTPException(409, "El monto supera el saldo disponible.")
            order = PaymentOrders(
                client_id=balance.client_id, customer_balance_id=balance.id,
                entity_id=self.req_user.get("entity_id"), currency_id=balance.balance_currency_id,
                amount=request.amount, executed_amount=0, status="pendiente_aprobacion",
            )
            self.db.add(order)
            self.db.flush()
            result = self._serialize(order)
            self.db.commit()
            return SuccessService.response(result)
        except Exception:
            self.db.rollback()
            raise

    def get_all(
        self,
        page=0,
        records_per_page=10,
        status=None,
        customer_balance_id=None,
    ):
        query = self._query()
        if status is not None:
            query = query.filter(PaymentOrders.status == status)
        if customer_balance_id is not None:
            query = query.filter(PaymentOrders.customer_balance_id == customer_balance_id)
        total_records = query.count()
        orders = (
            query.order_by(PaymentOrders.id.desc())
            .offset(page * records_per_page)
            .limit(records_per_page)
            .all()
        )

        payments_by_order = {order.id: [] for order in orders}
        if payments_by_order:
            payments = (
                self.db.query(Payments)
                .filter(Payments.payment_order_id.in_(payments_by_order))
                .order_by(Payments.id)
                .all()
            )
            for payment in payments:
                payments_by_order[payment.payment_order_id].append(payment)

        return SuccessService.response({
            "payment_orders": [
                self._serialize(order, payments_by_order[order.id])
                for order in orders
            ],
            "page": page,
            "recordsPerPage": records_per_page,
            "totalRecords": total_records,
            "totalPages": (
                total_records + records_per_page - 1
            ) // records_per_page,
        })

    def get_detail(self, order_id, page=0, records_per_page=10):
        order = self._query().filter(PaymentOrders.id == order_id).first()
        if order is None:
            raise HTTPException(404, "Orden no encontrada.")
        payments_query = self.db.query(Payments).filter(
            Payments.payment_order_id == order.id
        )
        total_records = payments_query.count()
        payments = (
            payments_query.order_by(Payments.id.desc())
            .offset(page * records_per_page)
            .limit(records_per_page)
            .all()
        )
        result = self._serialize(order, payments)
        result.update({
            "page": page,
            "recordsPerPage": records_per_page,
            "totalRecords": total_records,
            "totalPages": (
                total_records + records_per_page - 1
            ) // records_per_page,
        })
        return SuccessService.response(result)

    def execute(self, request):
        try:
            self.payments.require_user()
            order = self._query().filter(PaymentOrders.id == request.order_id).populate_existing().with_for_update().first()
            if order is None:
                raise HTTPException(404, "Orden no encontrada.")
            if order.status not in ("pendiente_aprobacion", "parcialmente_ejecutada"):
                raise HTTPException(409, "La orden ya fue ejecutada.")
            remaining = order.amount - order.executed_amount
            amount = request.amount if request.amount is not None else remaining
            if amount > remaining:
                raise HTTPException(409, "El monto supera el pendiente de la orden.")
            self.payments.create_record(NewPaymentRequest(
                amount=float(amount), date=request.date,
                customer_balance_id=order.customer_balance_id, currency_id=order.currency_id,
            ), payment_order_id=order.id)
            order.executed_amount += amount
            order.status = "ejecutada" if order.executed_amount == order.amount else "parcialmente_ejecutada"
            order.updated_at = datetime.utcnow()
            self.db.flush()
            result = self._serialize(order)
            self.db.commit()
            return SuccessService.response(result)
        except Exception:
            self.db.rollback()
            raise
