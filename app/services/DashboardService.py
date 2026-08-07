import calendar
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import and_, case, extract, func
from sqlalchemy.orm import Session
from starlette import status

from app.models import Clients, CustomersBalance, Trx
from app.schemas.dashboard import (
  DashboardFeesResponse,
  DashboardReconciliationResponse,
  DashboardResponse,
  DashboardSummaryMetrics,
  MonthlyFeeResponse,
)


class DashboardService:
  def __init__(self, db: Session, req_user: dict):
    self.db = db
    self.req_user = req_user

  @staticmethod
  def _now() -> datetime:
    return datetime.now()

  @staticmethod
  def _shift_month(month_start: datetime, offset: int) -> datetime:
    month_index = month_start.year * 12 + month_start.month - 1 + offset
    year, zero_based_month = divmod(month_index, 12)
    return datetime(year, zero_based_month + 1, 1)

  @staticmethod
  def _money(value) -> float:
    return round(float(value or 0), 2)

  @staticmethod
  def _previous_year_same_moment(value: datetime) -> datetime:
    try:
      return value.replace(year=value.year - 1)
    except ValueError:
      return value.replace(year=value.year - 1, day=28)

  def get_summary(self) -> DashboardResponse:
    entity_id = self.req_user.get("entity_id")
    if entity_id is None:
      raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing entity in authenticated user",
      )

    if self.req_user.get("user_perm") == "client":
      raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Dashboard is only available to internal users",
      )

    now = self._now()
    current_month_start = datetime(now.year, now.month, 1)
    first_month_start = self._shift_month(current_month_start, -11)
    previous_month_start = self._shift_month(current_month_start, -1)
    current_year_start = datetime(now.year, 1, 1)
    previous_year_start = datetime(now.year - 1, 1, 1)
    previous_year_cutoff = self._previous_year_same_moment(now)

    monthly_rows = (
      self.db.query(
        extract("year", Trx.date).label("year"),
        extract("month", Trx.date).label("month"),
        func.coalesce(func.sum(Trx.fee_amount), 0).label("fee_amount"),
        func.coalesce(func.sum(Trx.amount), 0).label("processed_volume"),
      )
      .filter(
        Trx.entity_id == entity_id,
        Trx.date >= first_month_start,
        Trx.date <= now,
      )
      .group_by(extract("year", Trx.date), extract("month", Trx.date))
      .all()
    )

    monthly_values = {
      (int(row.year), int(row.month)): {
        "fees": self._money(row.fee_amount),
        "volume": self._money(row.processed_volume),
      }
      for row in monthly_rows
    }

    monthly_fees = []
    for offset in range(12):
      month_start = self._shift_month(first_month_start, offset)
      month_key = (month_start.year, month_start.month)
      monthly_fees.append(
        MonthlyFeeResponse(
          year=month_start.year,
          month=month_start.month,
          label=f"{calendar.month_abbr[month_start.month]} {month_start.year}",
          amount=monthly_values.get(month_key, {}).get("fees", 0.0),
          is_current_month=month_start == current_month_start,
        )
      )

    current_key = (current_month_start.year, current_month_start.month)
    previous_key = (previous_month_start.year, previous_month_start.month)
    current_month_fees = monthly_values.get(current_key, {}).get("fees", 0.0)
    current_month_volume = monthly_values.get(current_key, {}).get("volume", 0.0)
    previous_month_fees = monthly_values.get(previous_key, {}).get("fees", 0.0)

    comparison_row = (
      self.db.query(
        func.coalesce(func.sum(case(
          (
            and_(Trx.date >= current_year_start, Trx.date <= now),
            func.coalesce(Trx.fee_amount, 0),
          ),
          else_=0,
        )), 0).label("current_year_fees"),
        func.coalesce(func.sum(case(
          (
            and_(
              Trx.date >= previous_year_start,
              Trx.date <= previous_year_cutoff,
            ),
            func.coalesce(Trx.fee_amount, 0),
          ),
          else_=0,
        )), 0).label("previous_year_fees"),
        func.coalesce(func.sum(case(
          (and_(Trx.date >= current_month_start, Trx.date <= now), 1),
          else_=0,
        )), 0).label("total_transactions"),
        func.coalesce(func.sum(case(
          (
            and_(
              Trx.date >= current_month_start,
              Trx.date <= now,
              Trx.status == "conciliado",
            ),
            1,
          ),
          else_=0,
        )), 0).label("reconciled_transactions"),
        func.coalesce(func.sum(case(
          (
            and_(
              Trx.date >= current_month_start,
              Trx.date <= now,
              Trx.status == "pendiente",
            ),
            1,
          ),
          else_=0,
        )), 0).label("pending_transactions"),
      )
      .filter(
        Trx.entity_id == entity_id,
        Trx.date >= previous_year_start,
        Trx.date <= now,
      )
      .one()
    )

    total_transactions = int(comparison_row.total_transactions or 0)
    reconciled_transactions = int(comparison_row.reconciled_transactions or 0)
    pending_transactions = int(comparison_row.pending_transactions or 0)
    failed_transactions = (
      total_transactions - reconciled_transactions - pending_transactions
    )

    available_fees, active_clients = (
      self.db.query(
        func.coalesce(func.sum(CustomersBalance.fee_amount), 0),
        func.count(func.distinct(case(
          (Clients.enabled == True, Clients.id),
          else_=None,
        ))),
      )
      .join(Clients, CustomersBalance.client_id == Clients.id)
      .filter(Clients.entity_id == entity_id)
      .one()
    )

    return DashboardResponse(
      summary=DashboardSummaryMetrics(
        processed_volume_current_month=current_month_volume,
        processed_transactions_current_month=total_transactions,
        active_clients=int(active_clients or 0),
        fees_earned_current_month=current_month_fees,
        available_fees=self._money(available_fees),
      ),
      fees=DashboardFeesResponse(
        current_month=current_month_fees,
        previous_month=previous_month_fees,
        current_year=self._money(comparison_row.current_year_fees),
        previous_year_same_period=self._money(
          comparison_row.previous_year_fees
        ),
        last_12_months=monthly_fees,
      ),
      reconciliation=DashboardReconciliationResponse(
        period="current_month",
        total_transactions=total_transactions,
        reconciled_transactions=reconciled_transactions,
        pending_transactions=pending_transactions,
        failed_transactions=failed_transactions,
      ),
    )
