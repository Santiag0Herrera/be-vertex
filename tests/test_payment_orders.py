from datetime import datetime
from decimal import Decimal

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, Clients, Currency, CustomersBalance, Entity, Permission, Users, Payments, PaymentOrders
from app.schemas.payment_orders import NewPaymentOrderRequest, ExecutePaymentOrderRequest
from app.schemas.payments import NewPaymentRequest
from app.services.PaymentOrderService import PaymentOrderService


@pytest.fixture
def setup():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    entity = Entity(name="Entidad", mail="e@test", status="enabled")
    currency = Currency(name="ARS")
    perm = Permission(level="client", hierarchy=1)
    db.add_all([entity, currency, perm]); db.flush()
    client = Clients(first_name="C", last_name="C", email="c@test", hashed_password="hash", perm_id=perm.id, entity_id=entity.id)
    user = Users(first_name="U", last_name="U", email="u@test", hashed_password="hash", entity_id=entity.id)
    db.add_all([client, user]); db.flush()
    balance = CustomersBalance(client_id=client.id, balance_amount=100, balance_currency_id=currency.id)
    db.add(balance); db.commit()
    client_service = PaymentOrderService(db, {"id": client.id, "entity_id": entity.id, "account_type": "client"})
    user_service = PaymentOrderService(db, {"id": user.id, "entity_id": entity.id, "account_type": "user"})
    yield db, balance, client_service, user_service
    db.close(); engine.dispose()


def create(setup, amount="80"):
    return setup[2].create(NewPaymentOrderRequest(customer_balance_id=setup[1].id, amount=amount))["result"]["id"]


def test_partial_then_full(setup):
    db, balance, client, user = setup
    order_id = create(setup)
    assert balance.balance_amount == 100
    detail = client.get_detail(order_id)["result"]
    assert detail["status"] == "pendiente_aprobacion"
    assert detail["page"] == 0
    assert detail["totalRecords"] == 0
    partial = user.execute(ExecutePaymentOrderRequest(order_id=order_id, amount="30"))["result"]
    assert partial["remaining_amount"] == Decimal("50")
    assert partial["status"] == "parcialmente_ejecutada"
    full = user.execute(ExecutePaymentOrderRequest(order_id=order_id))["result"]
    assert full["status"] == "ejecutada"
    assert len(full["payments"]) == 2
    assert balance.balance_amount == 20
    with pytest.raises(HTTPException) as error:
        user.execute(ExecutePaymentOrderRequest(order_id=order_id))
    assert error.value.status_code == 409
    assert db.query(Payments).count() == 2


def test_overexecution_and_insufficient_current_balance(setup):
    db, balance, _, user = setup
    order_id = create(setup)
    with pytest.raises(HTTPException):
        user.execute(ExecutePaymentOrderRequest(order_id=order_id, amount=81))
    user.payments.create(NewPaymentRequest(amount=50, date=datetime.utcnow(), customer_balance_id=balance.id, currency_id=balance.balance_currency_id))
    with pytest.raises(HTTPException):
        user.execute(ExecutePaymentOrderRequest(order_id=order_id))
    assert db.query(Payments).count() == 1
    assert db.get(PaymentOrders, order_id).executed_amount == 0
    assert balance.balance_amount == 50


def test_access_control(setup):
    _, balance, client, user = setup
    order_id = create(setup)
    with pytest.raises(HTTPException) as error:
        client.execute(ExecutePaymentOrderRequest(order_id=order_id))
    assert error.value.status_code == 403
    with pytest.raises(HTTPException):
        user.create(NewPaymentOrderRequest(customer_balance_id=balance.id, amount=1))
    client.req_user["id"] += 100
    assert client.get_all()["result"]["payment_orders"] == []
    with pytest.raises(HTTPException):
        client.create(NewPaymentOrderRequest(customer_balance_id=balance.id, amount=1))
    user.req_user["entity_id"] += 100
    with pytest.raises(HTTPException):
        user.execute(ExecutePaymentOrderRequest(order_id=order_id))


def test_commit_failure_rolls_back_payment_balance_and_order(setup, monkeypatch):
    db, balance, _, user = setup
    order_id = create(setup)
    def fail():
        raise RuntimeError("commit failed")
    monkeypatch.setattr(db, "commit", fail)
    with pytest.raises(RuntimeError):
        user.execute(ExecutePaymentOrderRequest(order_id=order_id, amount=30))
    assert db.query(Payments).count() == 0
    assert balance.balance_amount == 100
    assert db.get(PaymentOrders, order_id).executed_amount == 0


@pytest.mark.parametrize("amount", [0, -1, "NaN", "Infinity", "0.001", "100000000"])
def test_invalid_amount(amount):
    with pytest.raises(ValidationError):
        NewPaymentOrderRequest(customer_balance_id=1, amount=amount)
    with pytest.raises(ValidationError):
        ExecutePaymentOrderRequest(order_id=1, amount=amount)


def test_creation_insufficient_balance(setup):
    with pytest.raises(HTTPException):
        create(setup, "101")
    assert setup[0].query(PaymentOrders).count() == 0


def test_get_all_is_paginated(setup):
    _, _, client, _ = setup
    first_id = create(setup, "10")
    second_id = create(setup, "20")

    first_page = client.get_all(page=0, records_per_page=1)["result"]
    second_page = client.get_all(page=1, records_per_page=1)["result"]

    assert [order["id"] for order in first_page["payment_orders"]] == [second_id]
    assert [order["id"] for order in second_page["payment_orders"]] == [first_id]
    assert first_page["page"] == 0
    assert first_page["recordsPerPage"] == 1
    assert first_page["totalRecords"] == 2
    assert first_page["totalPages"] == 2


def test_get_detail_payments_are_paginated(setup):
    _, _, _, user = setup
    order_id = create(setup)
    user.execute(ExecutePaymentOrderRequest(order_id=order_id, amount="20"))
    user.execute(ExecutePaymentOrderRequest(order_id=order_id, amount="30"))

    first_page = user.get_detail(order_id, page=0, records_per_page=1)["result"]
    second_page = user.get_detail(order_id, page=1, records_per_page=1)["result"]

    assert first_page["payments"][0]["amount"] == 30
    assert second_page["payments"][0]["amount"] == 20
    assert first_page["totalRecords"] == 2
    assert first_page["totalPages"] == 2
