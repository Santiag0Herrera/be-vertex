import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, Clients, Entity, Permission
from app.schemas.users import ChangePasswordRequest
from app.services.ClientsService import ClientService
from app.services.auth_service import bcrypt_context


@pytest.fixture
def client_password_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    permission = Permission(level="client", hierarchy=1)
    entity = Entity(
        name="Entidad",
        mail="entidad@example.com",
        status="enabled",
    )
    db.add_all([permission, entity])
    db.flush()

    client = Clients(
        first_name="Cliente",
        last_name="Prueba",
        email="cliente@example.com",
        cuit="20123456789",
        hashed_password=bcrypt_context.hash("clave-anterior"),
        perm_id=permission.id,
        entity_id=entity.id,
    )
    db.add(client)
    db.commit()

    yield db, entity, client
    db.close()


def test_client_can_change_own_password(client_password_db):
    db, entity, client = client_password_db
    service = ClientService(
        db,
        {"id": client.id, "entity_id": entity.id, "account_type": "client"},
    )

    service.change_own_password(
        ChangePasswordRequest(
            password="clave-anterior",
            new_password="clave-nueva",
        )
    )

    db.refresh(client)
    assert bcrypt_context.verify("clave-nueva", client.hashed_password)
    assert not bcrypt_context.verify("clave-anterior", client.hashed_password)


def test_client_must_provide_current_password(client_password_db):
    db, entity, client = client_password_db
    original_hash = client.hashed_password
    service = ClientService(
        db,
        {"id": client.id, "entity_id": entity.id, "account_type": "client"},
    )

    with pytest.raises(HTTPException) as exc_info:
        service.change_own_password(
            ChangePasswordRequest(
                password="clave-incorrecta",
                new_password="clave-nueva",
            )
        )

    assert exc_info.value.status_code == 400
    db.refresh(client)
    assert client.hashed_password == original_hash
