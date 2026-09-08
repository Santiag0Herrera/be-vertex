from datetime import datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import (
    Base,
    Clients,
    Currency,
    CustomersBalance,
    Entity,
    FeeWithdrawals,
    Payments,
    Permission,
    Trx,
    Users,
)
from app.services.CustomerBalanceService import CustomerBalanceService


@pytest.fixture
def client_balances():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    permission = Permission(level="client", hierarchy=1)
    currency = Currency(name="ARS")
    entity = Entity(name="Entidad", mail="entidad@example.com", status="enabled")
    db.add_all([permission, currency, entity])
    db.flush()

    client = Clients(
        first_name="Cliente",
        last_name="Propio",
        email="propio@example.com",
        cuit="20123456789",
        hashed_password="hash",
        perm_id=permission.id,
        entity_id=entity.id,
    )
    other_client = Clients(
        first_name="Otro",
        last_name="Cliente",
        email="otro@example.com",
        cuit="20987654321",
        hashed_password="hash",
        perm_id=permission.id,
        entity_id=entity.id,
    )
    db.add_all([client, other_client])
    db.flush()
    own_balance = CustomersBalance(
        client_id=client.id,
        balance_amount=100,
        balance_currency_id=currency.id,
    )
    other_balance = CustomersBalance(
        client_id=other_client.id,
        balance_amount=999,
        balance_currency_id=currency.id,
    )
    db.add_all([own_balance, other_balance])
    db.flush()
    db.add(Trx(
        trx_id="OWN-TRX",
        emisor_name="Pagador",
        emisor_cuit="20333444556",
        receptor_cbu="0" * 22,
        entity_id=entity.id,
        client_id=client.id,
        amount=50,
        date=datetime(2026, 8, 20),
        status="conciliado",
        account_id=own_balance.id,
        fee_amount=5,
    ))
    db.commit()

    service = CustomerBalanceService(db, {
        "id": client.id,
        "entity_id": entity.id,
        "account_type": "client",
    })
    yield service, own_balance.id, other_balance.id
    db.close()


def test_client_only_sees_own_balances(client_balances):
    service, own_balance_id, _ = client_balances

    response = service.get_client_balances()

    assert [balance["id"] for balance in response["result"]] == [own_balance_id]
    assert "client" not in response["result"][0]


def test_client_sees_movements_for_own_balance(client_balances):
    service, own_balance_id, _ = client_balances

    response = service.get_client_balance_movements(own_balance_id)

    assert response["result"]["balance"]["id"] == own_balance_id
    assert response["result"]["movements"][0]["type"] == "Transaccion"
    assert response["result"]["movements"][0]["net_amount"] == 45
    assert response["result"]["page"] == 0
    assert response["result"]["recordsPerPage"] == 10
    assert response["result"]["totalRecords"] == 1
    assert response["result"]["totalPages"] == 1


def test_client_balance_movements_are_paginated(client_balances):
    service, own_balance_id, _ = client_balances
    for index, day in enumerate((21, 22), start=2):
        service.db.add(Trx(
            trx_id=f"OWN-TRX-{index}",
            emisor_name="Pagador",
            emisor_cuit="20333444556",
            receptor_cbu="0" * 22,
            entity_id=service.req_user["entity_id"],
            client_id=service.req_user["id"],
            amount=index * 10,
            date=datetime(2026, 8, day),
            status="conciliado",
            account_id=own_balance_id,
            fee_amount=0,
        ))
    service.db.commit()

    first_page = service.get_client_balance_movements(
        own_balance_id,
        page=0,
        records_per_page=2,
    )["result"]
    second_page = service.get_client_balance_movements(
        own_balance_id,
        page=1,
        records_per_page=2,
    )["result"]

    assert [movement["amount"] for movement in first_page["movements"]] == [
        "ARS 30.0",
        "ARS 20.0",
    ]
    assert [movement["amount"] for movement in second_page["movements"]] == [
        "ARS 50.0",
    ]
    assert first_page["totalRecords"] == 3
    assert first_page["totalPages"] == 2


def test_client_balance_movements_combine_all_movement_types(client_balances):
    service, own_balance_id, _ = client_balances
    balance = service.db.get(CustomersBalance, own_balance_id)
    user = Users(
        first_name="Usuario",
        last_name="Interno",
        email="interno@example.com",
        hashed_password="hash",
        entity_id=service.req_user["entity_id"],
    )
    service.db.add(user)
    service.db.flush()
    service.db.add_all([
        Payments(
            payee_user_id=user.id,
            amount=10,
            date=datetime(2026, 8, 22),
            status="consolidado",
            customer_balance_id=own_balance_id,
            currency_id=balance.balance_currency_id,
            entity_id=service.req_user["entity_id"],
        ),
        FeeWithdrawals(
            customer_balance_id=own_balance_id,
            withdrawn_by_user_id=user.id,
            entity_id=service.req_user["entity_id"],
            currency_id=balance.balance_currency_id,
            amount=5,
            date=datetime(2026, 8, 21),
            status="consolidado",
        ),
    ])
    service.db.commit()

    result = service.get_client_balance_movements(
        own_balance_id,
        page=0,
        records_per_page=10,
    )["result"]

    assert [movement["type"] for movement in result["movements"]] == [
        "Pago",
        "Retiro de comision",
        "Transaccion",
    ]
    assert result["totalRecords"] == 3


def test_client_cannot_access_another_clients_balance(client_balances):
    service, _, other_balance_id = client_balances

    with pytest.raises(HTTPException) as exception:
        service.get_client_balance_movements(other_balance_id)

    assert exception.value.status_code == 404


def test_internal_user_cannot_use_client_balance_endpoint(client_balances):
    service, _, _ = client_balances
    service.req_user["account_type"] = "user"

    with pytest.raises(HTTPException) as exception:
        service.get_client_balances()

    assert exception.value.status_code == 403
