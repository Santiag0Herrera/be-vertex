from datetime import datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, Clients, Currency, CustomersBalance, Entity, Permission, Trx
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
