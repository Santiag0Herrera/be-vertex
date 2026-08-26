from unittest.mock import Mock, patch

import pytest
from fastapi import HTTPException

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, Clients, Entity, Permission, Users
from app.router.auth import get_login_token
from app.services.auth_service import authenticate_user, bcrypt_context


@pytest.mark.asyncio
@pytest.mark.parametrize("authenticated_user", [False, None])
async def test_login_returns_descriptive_message_for_invalid_credentials(authenticated_user):
    form_data = Mock(username="persona@example.com", password="incorrecta")

    with patch("app.router.auth.authenticate_user", return_value=authenticated_user):
        with pytest.raises(HTTPException) as exception:
            await get_login_token(form_data=form_data, db=Mock())

    assert exception.value.status_code == 401
    assert exception.value.detail == "CUIT, correo electrónico o contraseña incorrectos."
    assert exception.value.headers == {"WWW-Authenticate": "Bearer"}


def test_authenticates_clients_by_cuit_and_internal_users_by_email():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    permission = Permission(level="client", hierarchy=1)
    entity = Entity(name="Entidad", mail="entidad@example.com", status="enabled")
    db.add_all([permission, entity])
    db.flush()
    client = Clients(
        first_name="Cliente",
        last_name="Prueba",
        email="cliente@example.com",
        cuit="20123456789",
        hashed_password=bcrypt_context.hash("clave-cliente"),
        perm_id=permission.id,
        entity_id=entity.id,
    )
    user = Users(
        first_name="Usuario",
        last_name="Interno",
        email="usuario@example.com",
        hashed_password=bcrypt_context.hash("clave-usuario"),
        perm_id=permission.id,
        entity_id=entity.id,
    )
    db.add_all([client, user])
    db.commit()

    assert authenticate_user("20123456789", "clave-cliente", db).id == client.id
    assert authenticate_user("20-12345678-9", "clave-cliente", db).id == client.id
    assert authenticate_user("cliente@example.com", "clave-cliente", db) is False
    assert authenticate_user("USUARIO@EXAMPLE.COM", "clave-usuario", db).id == user.id

    db.close()
