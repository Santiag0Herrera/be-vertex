import importlib
import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.middlewares.PermissionMiddleware import PermissionMiddleware
from app.models import Base, Endpoints, Permission, Product


permission_middleware_module = importlib.import_module(
    "app.middlewares.PermissionMiddleware"
)


@pytest.fixture
def permission_app(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)

    db = session_factory()
    product = Product(
        name="Vertex",
        description="Vertex",
        img="vertex.png",
        path="/",
    )
    client_permission = Permission(level="client", hierarchy=1, product_rel=product)
    admin_permission = Permission(level="admin", hierarchy=100, product_rel=product)
    db.add_all([product, client_permission, admin_permission])
    db.flush()
    db.add_all([
        Endpoints(path="/public", perm_id=None),
        Endpoints(path="/protected", perm_id=client_permission.id),
        Endpoints(path="/items/{item_id}", perm_id=client_permission.id),
        Endpoints(path="/admin", perm_id=admin_permission.id),
        Endpoints(path="/preflight", perm_id=client_permission.id),
    ])
    db.commit()

    monkeypatch.setattr(
        permission_middleware_module,
        "SessionLocal",
        session_factory,
    )
    monkeypatch.setattr(
        permission_middleware_module,
        "decode_access_token",
        lambda _: {
            "sub": "client@example.com",
            "perm_id": client_permission.id,
            "hierarchy": client_permission.hierarchy,
            "account_type": "client",
        },
    )

    app = FastAPI()

    @app.get("/public")
    def public_route():
        return {"ok": True}

    @app.get("/protected")
    def protected_route():
        return {"ok": True}

    @app.get("/items/{item_id}")
    def dynamic_route(item_id: int):
        return {"item_id": item_id}

    @app.get("/admin")
    def admin_route():
        return {"ok": True}

    @app.get("/preflight")
    def preflight_route():
        return {"ok": True}

    @app.get("/preflight-unregistered")
    def unregistered_preflight_route():
        return {"ok": True}

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://frontend.test"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(PermissionMiddleware)

    yield TestClient(app), client_permission

    db.close()
    engine.dispose()


def test_registered_public_endpoint_is_checked_and_allowed(permission_app):
    client, _ = permission_app

    response = client.get("/public")

    assert response.status_code == 200


def test_unregistered_endpoint_is_denied(permission_app):
    client, _ = permission_app

    response = client.get("/not-registered")

    assert response.status_code == 403
    assert response.json()["detail"] == "Endpoint not registered"


def test_registered_protected_endpoint_requires_token(permission_app):
    client, _ = permission_app

    without_token = client.get("/protected")
    with_token = client.get(
        "/protected",
        headers={"Authorization": "Bearer valid-token"},
    )

    assert without_token.status_code == 401
    assert with_token.status_code == 200


def test_dynamic_route_uses_registered_template(permission_app):
    client, _ = permission_app

    response = client.get(
        "/items/42",
        headers={"Authorization": "Bearer valid-token"},
    )

    assert response.status_code == 200
    assert response.json() == {"item_id": 42}


def test_database_hierarchy_is_enforced(permission_app):
    client, _ = permission_app

    response = client.get(
        "/admin",
        headers={"Authorization": "Bearer valid-token"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Permission denied"


def test_cors_preflight_must_also_reference_registered_endpoint(permission_app):
    client, _ = permission_app
    headers = {
        "Origin": "http://frontend.test",
        "Access-Control-Request-Method": "GET",
    }

    registered = client.options("/preflight", headers=headers)
    unregistered = client.options("/preflight-unregistered", headers=headers)

    assert registered.status_code == 200
    assert unregistered.status_code == 403


def test_registry_migration_contains_every_fastapi_route():
    from app.main import app

    migration = (
        Path(__file__).parents[1]
        / "migrations"
        / "20261102_enforce_endpoint_registry.sql"
    ).read_text()
    registered_paths = set(re.findall(r"\('(/[^']+)'\)", migration))
    application_paths = {route.path for route in app.routes}

    assert application_paths <= registered_paths
