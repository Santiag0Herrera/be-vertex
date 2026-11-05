from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import AccountAdjustments, Base, Clients, Currency, CustomersBalance, Entity, Permission, Users
from app.schemas.adjustments import AnnulAdjustmentRequest, NewAdjustmentRequest
from app.services.AccountAdjustmentService import AccountAdjustmentService
from app.services.CustomerBalanceService import CustomerBalanceService


@pytest.fixture
def setup():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    entity = Entity(name="Entidad", mail="e@test", status="enabled")
    other_entity = Entity(name="Otra", mail="o@test", status="enabled")
    currency = Currency(name="ARS")
    usd = Currency(name="USD")
    perm = Permission(level="client", hierarchy=1)
    db.add_all([entity, other_entity, currency, usd, perm]); db.flush()
    client = Clients(first_name="C", last_name="C", email="c@test", hashed_password="h", perm_id=perm.id, entity_id=entity.id)
    admin = Users(first_name="A", last_name="A", email="a@test", hashed_password="h", entity_id=entity.id)
    db.add_all([client, admin]); db.flush()
    balance = CustomersBalance(client_id=client.id, balance_amount=100, balance_currency_id=currency.id)
    db.add(balance); db.commit()
    admin_user = {"id": admin.id, "entity_id": entity.id, "account_type": "user", "user_perm": "admin"}
    service = AccountAdjustmentService(db, admin_user)
    yield {"db": db, "balance": balance, "service": service, "client": client, "entity": entity,
           "other_entity": other_entity, "usd": usd, "admin_user": admin_user}
    db.close(); engine.dispose()


def note(ctx, type_="credito", amount="25.50", **kwargs):
    data = dict(customer_balance_id=ctx["balance"].id, type=type_, amount=amount,
                currency_id=ctx["balance"].balance_currency_id, reason="Ajuste por error")
    data.update(kwargs)
    return ctx["service"].create(NewAdjustmentRequest(**data))["result"]


def test_credit_note_increases_balance(setup):
    result = note(setup)
    assert setup["balance"].balance_amount == 125.5
    assert result["label"] == "NC-0001"
    assert result["balance_before"] == 100 and result["balance_after"] == 125.5
    assert result["status"] == "emitida"


def test_debit_note_decreases_balance(setup):
    result = note(setup, "debito", "40")
    assert setup["balance"].balance_amount == 60
    assert result["label"] == "ND-0001"


def test_debit_note_cannot_exceed_balance(setup):
    with pytest.raises(HTTPException) as error:
        note(setup, "debito", "100.01")
    assert error.value.status_code == 409
    assert setup["balance"].balance_amount == 100
    assert setup["db"].query(AccountAdjustments).count() == 0


def test_debit_note_can_empty_balance(setup):
    note(setup, "debito", "100")
    assert setup["balance"].balance_amount == 0


def test_currency_must_match(setup):
    with pytest.raises(HTTPException) as error:
        note(setup, currency_id=setup["usd"].id)
    assert error.value.status_code == 409


def test_numbers_are_sequential_per_type(setup):
    labels = [note(setup)["label"], note(setup, "debito", "1")["label"], note(setup)["label"]]
    assert labels == ["NC-0001", "ND-0001", "NC-0002"]


def test_blank_reason_rejected(setup):
    with pytest.raises(HTTPException) as error:
        note(setup, reason="     ")
    assert error.value.status_code == 400


def test_only_admins_can_issue(setup):
    setup["service"].req_user["user_perm"] = "user"
    with pytest.raises(HTTPException) as error:
        note(setup)
    assert error.value.status_code == 403
    setup["service"].req_user.update(user_perm="admin", account_type="client")
    with pytest.raises(HTTPException):
        note(setup)
    assert setup["balance"].balance_amount == 100


def test_other_entity_account_not_found(setup):
    other_admin = Users(first_name="O", last_name="O", email="o@u", hashed_password="h", entity_id=setup["other_entity"].id)
    setup["db"].add(other_admin); setup["db"].commit()
    service = AccountAdjustmentService(setup["db"], {"id": other_admin.id, "entity_id": setup["other_entity"].id,
                                                     "account_type": "user", "user_perm": "admin"})
    with pytest.raises(HTTPException) as error:
        service.create(NewAdjustmentRequest(customer_balance_id=setup["balance"].id, type="credito", amount=1,
                                            currency_id=setup["balance"].balance_currency_id, reason="x" * 5))
    assert error.value.status_code == 404


def test_annul_credit_reverses_and_cannot_repeat(setup):
    created = note(setup, amount="50")
    annulled = setup["service"].annul(AnnulAdjustmentRequest(adjustment_id=created["id"], reason="Cargada por error"))["result"]
    assert annulled["status"] == "anulada"
    assert annulled["annul_reason"] == "Cargada por error"
    assert setup["balance"].balance_amount == 100
    with pytest.raises(HTTPException) as error:
        setup["service"].annul(AnnulAdjustmentRequest(adjustment_id=created["id"], reason="Otra vez"))
    assert error.value.status_code == 409


def test_annul_debit_restores_balance(setup):
    created = note(setup, "debito", "30")
    setup["service"].annul(AnnulAdjustmentRequest(adjustment_id=created["id"], reason="Error de carga"))
    assert setup["balance"].balance_amount == 100


def test_annul_credit_blocked_when_balance_already_spent(setup):
    created = note(setup, amount="50")
    note(setup, "debito", "120")
    with pytest.raises(HTTPException) as error:
        setup["service"].annul(AnnulAdjustmentRequest(adjustment_id=created["id"], reason="Error de carga"))
    assert error.value.status_code == 409
    assert setup["balance"].balance_amount == 30


def test_commit_failure_rolls_back(setup, monkeypatch):
    def fail():
        raise RuntimeError("commit failed")
    monkeypatch.setattr(setup["db"], "commit", fail)
    with pytest.raises(RuntimeError):
        note(setup)
    assert setup["balance"].balance_amount == 100
    assert setup["db"].query(AccountAdjustments).count() == 0


@pytest.mark.parametrize("amount", [0, -1, "NaN", "Infinity", "0.001", "100000000"])
def test_invalid_amount(amount):
    with pytest.raises(ValidationError):
        NewAdjustmentRequest(customer_balance_id=1, type="credito", amount=amount, currency_id=1, reason="Motivo")


def test_invalid_type():
    with pytest.raises(ValidationError):
        NewAdjustmentRequest(customer_balance_id=1, type="otro", amount=1, currency_id=1, reason="Motivo")


def test_notes_listed_and_in_movements(setup):
    note(setup, date=datetime.utcnow() - timedelta(minutes=1))
    note(setup, "debito", "5")
    listed = setup["service"].get_all(setup["balance"].id)["result"]
    assert [n["label"] for n in listed] == ["ND-0001", "NC-0001"]

    internal = CustomerBalanceService(setup["db"], setup["admin_user"]).get_all_movements(setup["balance"].id)["result"]
    assert [m["type"] for m in internal["movements"]] == ["Nota de debito", "Nota de credito"]
    assert internal["movements"][0]["note_label"] == "ND-0001"

    client_service = CustomerBalanceService(setup["db"], {"id": setup["client"].id, "entity_id": setup["entity"].id,
                                                           "account_type": "client"})
    page = client_service.get_client_balance_movements(setup["balance"].id)["result"]
    assert [m["type"] for m in page["movements"]] == ["Nota de debito", "Nota de credito"]
    assert page["movements"][1]["amount"] == "ARS 25.5"
    assert page["movements"][1]["reason"] == "Ajuste por error"
    assert page["movements"][1]["note_label"] == "NC-0001"


def test_client_cannot_list_notes(setup):
    setup["service"].req_user["account_type"] = "client"
    with pytest.raises(HTTPException) as error:
        setup["service"].get_all(setup["balance"].id)
    assert error.value.status_code == 403
