from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import (
  Base,
  Clients,
  Currency,
  CustomersBalance,
  Entity,
  Permission,
  Trx,
)
from app.services.DashboardService import DashboardService


NOW = datetime(2026, 8, 5, 12, 0, 0)


@pytest.fixture
def dashboard_response(monkeypatch):
  engine = create_engine("sqlite:///:memory:")
  Base.metadata.create_all(engine)
  db = sessionmaker(bind=engine)()

  permission = Permission(level="client", hierarchy=1)
  currency = Currency(name="ARS")
  entity = Entity(name="Vertex Entity", mail="entity@vertex.test", status="enabled")
  other_entity = Entity(name="Other Entity", mail="other@vertex.test", status="enabled")
  db.add_all([permission, currency, entity, other_entity])
  db.flush()

  client = Clients(
    first_name="Internal",
    last_name="Client",
    email="client@vertex.test",
    hashed_password="hash",
    perm_id=permission.id,
    entity_id=entity.id,
    enabled=True,
  )
  other_client = Clients(
    first_name="Other",
    last_name="Client",
    email="other-client@vertex.test",
    hashed_password="hash",
    perm_id=permission.id,
    entity_id=other_entity.id,
    enabled=True,
  )
  db.add_all([client, other_client])
  db.flush()

  balance = CustomersBalance(
    client_id=client.id,
    balance_amount=100,
    fee_amount=25,
    balance_currency_id=currency.id,
    fee_percentage=5,
  )
  other_balance = CustomersBalance(
    client_id=other_client.id,
    balance_amount=500,
    fee_amount=500,
    balance_currency_id=currency.id,
    fee_percentage=5,
  )
  db.add_all([balance, other_balance])
  db.flush()

  db.add_all([
    Trx(
      trx_id="CURRENT-ENTITY",
      emisor_name="Sender",
      emisor_cuit="20111111111",
      receptor_cbu="0" * 22,
      entity_id=entity.id,
      amount=100,
      date=datetime(2026, 8, 3),
      status="conciliado",
      account_id=balance.id,
      fee_amount=10,
    ),
    Trx(
      trx_id="NULL-FEE",
      emisor_name="Sender",
      emisor_cuit="20222222222",
      receptor_cbu="1" * 22,
      entity_id=entity.id,
      amount=50,
      date=datetime(2026, 6, 15),
      status="conciliado",
      account_id=balance.id,
      fee_amount=None,
    ),
    Trx(
      trx_id="CURRENT-PENDING",
      emisor_name="Sender",
      emisor_cuit="20444444444",
      receptor_cbu="3" * 22,
      entity_id=entity.id,
      amount=40,
      date=datetime(2026, 8, 4),
      status="pendiente",
      account_id=balance.id,
      fee_amount=None,
    ),
    Trx(
      trx_id="CURRENT-FAILED",
      emisor_name="Sender",
      emisor_cuit="20555555555",
      receptor_cbu="4" * 22,
      entity_id=entity.id,
      amount=30,
      date=datetime(2026, 8, 4),
      status="repetido",
      account_id=balance.id,
      fee_amount=0,
    ),
    Trx(
      trx_id="PREVIOUS-YEAR",
      emisor_name="Sender",
      emisor_cuit="20666666666",
      receptor_cbu="5" * 22,
      entity_id=entity.id,
      amount=80,
      date=datetime(2025, 8, 5, 10),
      status="conciliado",
      account_id=balance.id,
      fee_amount=8,
    ),
    Trx(
      trx_id="OTHER-ENTITY",
      emisor_name="Sender",
      emisor_cuit="20333333333",
      receptor_cbu="2" * 22,
      entity_id=other_entity.id,
      amount=9999,
      date=datetime(2026, 8, 4),
      status="conciliado",
      account_id=other_balance.id,
      fee_amount=999,
    ),
  ])
  db.commit()

  monkeypatch.setattr(DashboardService, "_now", staticmethod(lambda: NOW))
  response = DashboardService(
    db,
    {"id": 1, "entity_id": entity.id, "user_perm": "admin"},
  ).get_summary()
  yield response
  db.close()


def test_dashboard_always_returns_twelve_months(dashboard_response):
  assert len(dashboard_response.fees.last_12_months) == 12


def test_dashboard_fills_missing_months_with_zero(dashboard_response):
  july = next(
    month
    for month in dashboard_response.fees.last_12_months
    if month.year == 2026 and month.month == 7
  )
  assert july.amount == 0.0


def test_dashboard_marks_current_month(dashboard_response):
  current_months = [
    month for month in dashboard_response.fees.last_12_months
    if month.is_current_month
  ]
  assert len(current_months) == 1
  assert (current_months[0].year, current_months[0].month) == (2026, 8)


def test_dashboard_excludes_other_entities(dashboard_response):
  assert dashboard_response.fees.current_month == 10.0
  assert dashboard_response.summary.processed_volume_current_month == 170.0


def test_dashboard_treats_null_fee_as_zero(dashboard_response):
  june = next(
    month
    for month in dashboard_response.fees.last_12_months
    if month.year == 2026 and month.month == 6
  )
  assert june.amount == 0.0


def test_available_fees_comes_from_customer_balances(dashboard_response):
  assert dashboard_response.summary.available_fees == 25.0
  assert dashboard_response.summary.available_fees != dashboard_response.fees.current_month


def test_dashboard_compares_current_year_with_same_previous_year_period(
  dashboard_response,
):
  assert dashboard_response.fees.current_year == 10.0
  assert dashboard_response.fees.previous_year_same_period == 8.0


def test_dashboard_reconciliation_categories_sum_to_total(dashboard_response):
  reconciliation = dashboard_response.reconciliation
  assert reconciliation.period == "current_month"
  assert reconciliation.total_transactions == 3
  assert reconciliation.reconciled_transactions == 1
  assert reconciliation.pending_transactions == 1
  assert reconciliation.failed_transactions == 1
  assert (
    reconciliation.reconciled_transactions
    + reconciliation.pending_transactions
    + reconciliation.failed_transactions
    == reconciliation.total_transactions
  )


def test_dashboard_summary_includes_processed_transactions_and_active_clients(
  dashboard_response,
):
  assert dashboard_response.summary.processed_transactions_current_month == 3
  assert dashboard_response.summary.active_clients == 1
