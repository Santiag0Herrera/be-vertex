import csv
import io
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from itertools import groupby

from fastapi import HTTPException
from sqlalchemy.orm import Session, joinedload
from starlette import status as http_status

from app.models import Clients, CustomersBalance, Trx


class TransactionReportService:
    HEADERS = (
        "Cliente",
        "Fecha",
        "Importe",
        "Fecha Comp.",
        "Nº Comprobante",
        "Comp. Rechazados/Duplicados",
    )
    ALLOWED_STATUSES = {"pendiente", "conciliado", "repetido", "vencida", "rechazado"}
    REJECTED_STATUS_LABELS = {
        "repetido": "Duplicado",
        "vencida": "Vencido",
        "rechazado": "Rechazado",
    }

    def __init__(self, db: Session, req_user: dict):
        self.db = db
        self.req_user = req_user

    def generate(
        self,
        *,
        month: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        transaction_status: str | None = None,
        client_id: int | None = None,
        account_ids: list[int] | None = None,
    ) -> tuple[str, str]:
        entity_id = self.req_user.get("entity_id")
        if entity_id is None:
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail="El usuario no tiene una entidad asociada.",
            )

        normalized_status = transaction_status.strip().lower() if transaction_status else None
        if normalized_status and normalized_status not in self.ALLOWED_STATUSES:
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="El estado del comprobante no es válido.",
            )

        range_start, range_end = self._date_range(month, date_from, date_to)
        selected_accounts = sorted(set(account_ids or []))
        self._validate_scope(entity_id, client_id, selected_accounts)

        query = (
            self.db.query(Trx)
            .join(Trx.account)
            .join(CustomersBalance.client)
            .filter(
                Trx.entity_id == entity_id,
                Clients.entity_id == entity_id,
                Clients.enabled.is_(True),
                CustomersBalance.enabled.is_(True),
            )
            .options(
                joinedload(Trx.account).joinedload(CustomersBalance.client),
                joinedload(Trx.client),
            )
        )

        if range_start is not None:
            query = query.filter(Trx.creation_date >= datetime.combine(range_start, time.min))
        if range_end is not None:
            query = query.filter(Trx.creation_date < datetime.combine(range_end, time.min))
        if normalized_status:
            query = query.filter(Trx.status == normalized_status)
        if client_id is not None:
            query = query.filter(CustomersBalance.client_id == client_id)
        if selected_accounts:
            query = query.filter(Trx.account_id.in_(selected_accounts))

        transactions = query.order_by(Trx.creation_date.asc(), Trx.id.asc()).all()
        if not transactions:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="No hay comprobantes para los filtros seleccionados.",
            )

        return self._filename(month, range_start, range_end), self._build_csv(transactions)

    def _validate_scope(
        self,
        entity_id: int,
        client_id: int | None,
        account_ids: list[int],
    ) -> None:
        if client_id is not None:
            client_exists = (
                self.db.query(Clients.id)
                .filter(
                    Clients.id == client_id,
                    Clients.entity_id == entity_id,
                    Clients.enabled.is_(True),
                )
                .first()
            )
            if client_exists is None:
                raise HTTPException(
                    status_code=http_status.HTTP_404_NOT_FOUND,
                    detail="Cliente no encontrado.",
                )

        if not account_ids:
            return

        accounts = (
            self.db.query(CustomersBalance.id, CustomersBalance.client_id)
            .join(CustomersBalance.client)
            .filter(
                CustomersBalance.id.in_(account_ids),
                CustomersBalance.enabled.is_(True),
                Clients.enabled.is_(True),
                Clients.entity_id == entity_id,
            )
            .all()
        )
        if {row.id for row in accounts} != set(account_ids):
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Una o más cuentas no fueron encontradas.",
            )
        if client_id is not None and any(row.client_id != client_id for row in accounts):
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Todas las cuentas seleccionadas deben pertenecer al cliente indicado.",
            )

    @staticmethod
    def _date_range(
        month: str | None,
        date_from: date | None,
        date_to: date | None,
    ) -> tuple[date | None, date | None]:
        if date_from and date_to and date_from > date_to:
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="La fecha desde no puede ser posterior a la fecha hasta.",
            )

        month_start = None
        next_month = None
        if month:
            try:
                month_start = datetime.strptime(month, "%Y-%m").date().replace(day=1)
            except ValueError as exc:
                raise HTTPException(
                    status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="El mes debe tener el formato AAAA-MM.",
                ) from exc
            next_month = (
                month_start.replace(year=month_start.year + 1, month=1)
                if month_start.month == 12
                else month_start.replace(month=month_start.month + 1)
            )

        range_start = max(filter(None, (month_start, date_from)), default=None)
        explicit_end = date_to + timedelta(days=1) if date_to else None
        range_end = min(filter(None, (next_month, explicit_end)), default=None)
        if range_start is not None and range_end is not None and range_start >= range_end:
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="El mes y el rango de fechas no se superponen.",
            )
        return range_start, range_end

    @classmethod
    def _build_csv(cls, transactions: list[Trx]) -> str:
        output = io.StringIO(newline="")
        writer = csv.writer(output, delimiter=";", lineterminator="\r\n")
        writer.writerow(cls.HEADERS)

        for transaction_date, daily_transactions in groupby(
            transactions,
            key=lambda transaction: transaction.creation_date.date(),
        ):
            daily_total = Decimal("0")
            for transaction in daily_transactions:
                amount = Decimal(str(transaction.amount))
                daily_total += amount
                client = transaction.account.client if transaction.account else transaction.client
                client_name = " ".join(
                    part.strip()
                    for part in (client.first_name, client.last_name)
                    if part and part.strip()
                )
                writer.writerow(
                    (
                        cls._safe_text(client_name),
                        transaction_date.strftime("%d/%m"),
                        cls._format_amount(amount),
                        transaction.date.strftime("%d/%m/%Y"),
                        cls._safe_text(transaction.trx_id),
                        cls.REJECTED_STATUS_LABELS.get(transaction.status.lower(), ""),
                    )
                )
            writer.writerow(
                (
                    "total",
                    transaction_date.strftime("%d/%m"),
                    cls._format_amount(daily_total),
                    "",
                    "",
                    "",
                )
            )

        return "\ufeff" + output.getvalue()

    @staticmethod
    def _safe_text(value: object) -> str:
        text = str(value or "")
        stripped = text.lstrip()
        return (
            f"'{text}"
            if text.startswith(("\t", "\r", "\n"))
            or stripped.startswith(("=", "+", "-", "@"))
            else text
        )

    @staticmethod
    def _format_amount(value: Decimal) -> str:
        return f"{value:,.2f}"

    @staticmethod
    def _filename(
        month: str | None,
        range_start: date | None,
        range_end: date | None,
    ) -> str:
        if month:
            suffix = month
        elif range_start or range_end:
            first = range_start.isoformat() if range_start else "inicio"
            last = (range_end - timedelta(days=1)).isoformat() if range_end else "actualidad"
            suffix = f"{first}_a_{last}"
        else:
            suffix = datetime.now().date().isoformat()
        return f"reporte_comprobantes_{suffix}.csv"
