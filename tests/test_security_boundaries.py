from datetime import date, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base as DatabaseBase
from app.models import (
    Base,
    Clients,
    Currency,
    CustomersBalance,
    Entity,
    Permission,
    Users,
)
from app.services.ClientsService import ClientService
from app.services.CustomerBalanceService import CustomerBalanceService
from app.services.EntitiesService import EntitiesService
from app.services.TransactionsService import TransactionsService
from app.services.auth_service import create_token, get_current_user
from app.schemas.transactions import DocumentRequest, MultipleDocumentRequest


@pytest.fixture
def security_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    permission = Permission(level="admin", hierarchy=100)
    currency = Currency(name="ARS")
    own_entity = Entity(
        name="Entidad propia",
        mail="propia@example.com",
        status="enabled",
    )
    other_entity = Entity(
        name="Entidad ajena",
        mail="ajena@example.com",
        status="enabled",
    )
    db.add_all([permission, currency, own_entity, other_entity])
    db.flush()

    user = Users(
        first_name="Admin",
        last_name="Propio",
        email="admin@example.com",
        hashed_password="hash",
        perm_id=permission.id,
        entity_id=own_entity.id,
    )
    other_client = Clients(
        first_name="Cliente",
        last_name="Ajeno",
        email="ajeno@example.com",
        cuit="20999999991",
        hashed_password="hash",
        perm_id=permission.id,
        entity_id=other_entity.id,
    )
    db.add_all([user, other_client])
    db.flush()
    other_balance = CustomersBalance(
        client_id=other_client.id,
        balance_currency_id=currency.id,
    )
    db.add(other_balance)
    db.commit()

    yield db, permission, own_entity, other_entity, user, other_client, other_balance
    db.close()


def test_models_and_database_share_the_same_declarative_base():
    assert Base is DatabaseBase


@pytest.mark.asyncio
async def test_token_is_revalidated_against_current_database_state(
    security_db,
    monkeypatch,
):
    db, permission, own_entity, _, user, _, _ = security_db
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret")
    token = create_token(
        email=user.email,
        user_id=user.id,
        permission_level=permission.level,
        perm_id=permission.id,
        hierarchy=permission.hierarchy,
        entity_id=own_entity.id,
        account_type="user",
        expires_delta=timedelta(minutes=5),
        db=db,
    )

    authenticated = await get_current_user(token=token, db=db)
    assert authenticated["id"] == user.id
    assert authenticated["entity_id"] == own_entity.id

    user.enabled = False
    db.commit()
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(token=token, db=db)
    assert exc_info.value.status_code == 401


def test_cross_entity_records_are_not_addressable(security_db):
    db, permission, own_entity, other_entity, user, other_client, other_balance = security_db
    request_user = {
        "id": user.id,
        "entity_id": own_entity.id,
        "user_perm": permission.level,
        "user_perm_id": permission.id,
        "account_type": "user",
    }

    with pytest.raises(HTTPException) as client_error:
        ClientService(db, request_user).delete(other_client.id)
    assert client_error.value.status_code == 404

    with pytest.raises(HTTPException) as balance_error:
        CustomerBalanceService(db, request_user).get_by_id(other_balance.id)
    assert balance_error.value.status_code == 404

    with pytest.raises(HTTPException) as entity_error:
        EntitiesService(db, request_user).get_by_id(other_entity.id)
    assert entity_error.value.status_code == 404

    cross_entity_request = MultipleDocumentRequest(
        account_id=other_balance.id,
        owner_account_number="0" * 22,
        transactions=[DocumentRequest(amount=100, date=date(2026, 9, 17))],
    )
    with pytest.raises(HTTPException) as transaction_error:
        TransactionsService(db, request_user).create_multiple(cross_entity_request)
    assert transaction_error.value.status_code == 404
