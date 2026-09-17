import csv
import io
from datetime import date, datetime

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Clients, Currency, CustomersBalance, Entity, Permission, Trx
from app.db.database import get_db
from app.router.transactions import router as transactions_router
from app.services.TransactionReportService import TransactionReportService
from app.services.auth_service import require_internal_user


@pytest.fixture
def report_data():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    permission = Permission(level="client", hierarchy=1)
    currency = Currency(name="ARS")
    entity = Entity(name="Vertex", mail="vertex@example.test", status="enabled")
    other_entity = Entity(name="Otra", mail="otra@example.test", status="enabled")
    db.add_all([permission, currency, entity, other_entity])
    db.flush()

    client = Clients(
        first_name="Adriana",
        last_name="Fili",
        email="adriana@example.test",
        hashed_password="hash",
        perm_id=permission.id,
        entity_id=entity.id,
        enabled=True,
    )
    second_client = Clients(
        first_name="Abel",
        last_name="Eberts",
        email="abel@example.test",
        hashed_password="hash",
        perm_id=permission.id,
        entity_id=entity.id,
        enabled=True,
    )
    other_client = Clients(
        first_name="Otro",
        last_name="Cliente",
        email="otro@example.test",
        hashed_password="hash",
        perm_id=permission.id,
        entity_id=other_entity.id,
        enabled=True,
    )
    db.add_all([client, second_client, other_client])
    db.flush()

    account = CustomersBalance(
        client_id=client.id,
        balance_currency_id=currency.id,
        balance_amount=0,
        fee_amount=0,
    )
    second_account = CustomersBalance(
        client_id=second_client.id,
        balance_currency_id=currency.id,
        balance_amount=0,
        fee_amount=0,
    )
    other_account = CustomersBalance(
        client_id=other_client.id,
        balance_currency_id=currency.id,
        balance_amount=0,
        fee_amount=0,
    )
    db.add_all([account, second_account, other_account])
    db.flush()

    db.add_all(
        [
            Trx(
                trx_id="DEC-02",
                emisor_name="Emisor",
                emisor_cuit="20111111111",
                receptor_cbu="0" * 22,
                entity_id=entity.id,
                client_id=client.id,
                account_id=account.id,
                amount=200000,
                date=datetime(2025, 12, 2, 18, 30),
                creation_date=datetime(2025, 12, 3, 9),
                status="conciliado",
            ),
            Trx(
                trx_id="DEC-01-DUP",
                emisor_name="Emisor",
                emisor_cuit="20222222222",
                receptor_cbu="1" * 22,
                entity_id=entity.id,
                client_id=second_client.id,
                account_id=second_account.id,
                amount=30800.5,
                date=datetime(2025, 12, 1, 14),
                creation_date=datetime(2025, 12, 1, 15),
                status="repetido",
            ),
            Trx(
                trx_id="DEC-01",
                emisor_name="Emisor",
                emisor_cuit="20333333333",
                receptor_cbu="2" * 22,
                entity_id=entity.id,
                client_id=client.id,
                account_id=account.id,
                amount=115500,
                date=datetime(2025, 12, 1, 16),
                creation_date=datetime(2025, 12, 2, 10),
                status="conciliado",
            ),
            Trx(
                trx_id="JAN-01",
                emisor_name="Emisor",
                emisor_cuit="20444444444",
                receptor_cbu="3" * 22,
                entity_id=entity.id,
                client_id=client.id,
                account_id=account.id,
                amount=100,
                date=datetime(2026, 1, 1),
                creation_date=datetime(2026, 1, 1),
                status="pendiente",
            ),
            Trx(
                trx_id="OTHER-ENTITY",
                emisor_name="Emisor",
                emisor_cuit="20555555555",
                receptor_cbu="4" * 22,
                entity_id=other_entity.id,
                client_id=other_client.id,
                account_id=other_account.id,
                amount=999999,
                date=datetime(2025, 12, 1),
                creation_date=datetime(2025, 12, 1),
                status="conciliado",
            ),
        ]
    )
    db.commit()

    yield {
        "db": db,
        "entity": entity,
        "client": client,
        "second_client": second_client,
        "account": account,
        "second_account": second_account,
        "other_account": other_account,
    }
    db.close()


def _rows(content: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(content.removeprefix("\ufeff")), delimiter=";"))


@pytest.mark.parametrize("value", ["=1+1", " +SUM(A1:A2)", "@IMPORT", "\t=1+1"])
def test_report_escapes_spreadsheet_formulas(value):
    assert TransactionReportService._safe_text(value).startswith("'")


def test_report_is_sorted_grouped_totalled_and_scoped_by_entity(report_data):
    service = TransactionReportService(
        report_data["db"],
        {"entity_id": report_data["entity"].id},
    )

    filename, content = service.generate(month="2025-12")
    rows = _rows(content)

    assert filename == "reporte_comprobantes_2025-12.csv"
    assert content.startswith("\ufeff")
    assert rows == [
        list(TransactionReportService.HEADERS),
        ["Abel Eberts", "01/12", "30,800.50", "01/12/2025", "DEC-01-DUP", "Duplicado"],
        ["total", "01/12", "30,800.50", "", "", ""],
        ["Adriana Fili", "02/12", "115,500.00", "01/12/2025", "DEC-01", ""],
        ["total", "02/12", "115,500.00", "", "", ""],
        ["Adriana Fili", "03/12", "200,000.00", "02/12/2025", "DEC-02", ""],
        ["total", "03/12", "200,000.00", "", "", ""],
    ]


def test_report_combines_client_account_status_and_date_filters(report_data):
    service = TransactionReportService(
        report_data["db"],
        {"entity_id": report_data["entity"].id},
    )

    _, content = service.generate(
        month="2025-12",
        date_from=date(2025, 12, 1),
        date_to=date(2025, 12, 1),
        transaction_status="repetido",
        client_id=report_data["second_client"].id,
        account_ids=[report_data["second_account"].id],
    )

    rows = _rows(content)
    assert [row[4] for row in rows[1:-1]] == ["DEC-01-DUP"]
    assert rows[-1][2] == "30,800.50"


def test_report_rejects_accounts_outside_the_entity(report_data):
    service = TransactionReportService(
        report_data["db"],
        {"entity_id": report_data["entity"].id},
    )

    with pytest.raises(HTTPException) as exc_info:
        service.generate(account_ids=[report_data["other_account"].id])

    assert exc_info.value.status_code == 404


def test_client_filter_includes_all_accounts_and_can_narrow_them(report_data):
    db = report_data["db"]
    extra_account = CustomersBalance(
        client_id=report_data["client"].id,
        balance_currency_id=report_data["account"].balance_currency_id,
        balance_amount=0,
        fee_amount=0,
    )
    db.add(extra_account)
    db.flush()
    db.add(
        Trx(
            trx_id="SECOND-ACCOUNT",
            emisor_name="Emisor",
            emisor_cuit="20666666666",
            receptor_cbu="5" * 22,
            entity_id=report_data["entity"].id,
            client_id=report_data["client"].id,
            account_id=extra_account.id,
            amount=250,
            date=datetime(2025, 12, 4),
            creation_date=datetime(2025, 12, 4),
            status="conciliado",
        )
    )
    db.commit()
    service = TransactionReportService(
        db,
        {"entity_id": report_data["entity"].id},
    )

    _, all_client_accounts = service.generate(
        month="2025-12",
        client_id=report_data["client"].id,
    )
    _, selected_account = service.generate(
        month="2025-12",
        client_id=report_data["client"].id,
        account_ids=[extra_account.id],
    )

    assert {row[4] for row in _rows(all_client_accounts)} >= {
        "DEC-01",
        "DEC-02",
        "SECOND-ACCOUNT",
    }
    assert [row[4] for row in _rows(selected_account)[1:-1]] == ["SECOND-ACCOUNT"]


def test_report_rejects_account_from_another_selected_client(report_data):
    service = TransactionReportService(
        report_data["db"],
        {"entity_id": report_data["entity"].id},
    )

    with pytest.raises(HTTPException) as exc_info:
        service.generate(
            client_id=report_data["client"].id,
            account_ids=[report_data["second_account"].id],
        )

    assert exc_info.value.status_code == 422


def test_report_rejects_non_overlapping_month_and_dates(report_data):
    service = TransactionReportService(
        report_data["db"],
        {"entity_id": report_data["entity"].id},
    )

    with pytest.raises(HTTPException) as exc_info:
        service.generate(month="2025-12", date_from=date(2026, 1, 1))

    assert exc_info.value.status_code == 422


def test_report_endpoint_returns_a_downloadable_csv(report_data):
    app = FastAPI()
    app.include_router(transactions_router)
    app.dependency_overrides[get_db] = lambda: report_data["db"]
    app.dependency_overrides[require_internal_user] = lambda: {
        "entity_id": report_data["entity"].id,
        "account_type": "user",
    }
    client = TestClient(app)

    response = client.get(
        "/trx/report.csv",
        params={"month": "2025-12", "account_ids": report_data["account"].id},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert response.headers["content-disposition"] == (
        'attachment; filename="reporte_comprobantes_2025-12.csv"'
    )
    assert response.content.startswith(b"\xef\xbb\xbf")
    assert "DEC-01" in response.text
