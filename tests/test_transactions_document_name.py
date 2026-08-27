from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import (
    Base,
    CBU,
    Clients,
    Currency,
    CustomersBalance,
    Entity,
    EntityCBU,
    Permission,
    Trx,
    Users,
)
from app.schemas.transactions import DocumentRequest, MultipleDocumentRequest
from app.services.TransactionsService import TransactionsService


def test_create_multiple_stores_document_name_on_every_transaction():
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
        last_name="Prueba",
        email="cliente@example.com",
        hashed_password="hash",
        perm_id=permission.id,
        entity_id=entity.id,
    )
    db.add(client)
    db.flush()
    account = CustomersBalance(
        client_id=client.id,
        balance_currency_id=currency.id,
    )
    db.add(account)
    db.commit()

    request = MultipleDocumentRequest(
        account_id=account.id,
        owner_account_number="0" * 22,
        document_name="transferencias-agosto.pdf",
        transactions=[
            DocumentRequest(amount=100, date=date(2026, 8, 27)),
            DocumentRequest(amount=200, date=date(2026, 8, 27)),
        ],
    )

    TransactionsService(db, {"entity_id": entity.id}).create_multiple(request)

    assert [trx.document_name for trx in db.query(Trx).all()] == [
        "transferencias-agosto.pdf",
        "transferencias-agosto.pdf",
    ]
    db.close()


def test_transaction_document_name_overrides_common_document_name():
    request = MultipleDocumentRequest(
        account_id=1,
        owner_account_number="0" * 22,
        document_name="archivo-comun.pdf",
        transactions=[
            DocumentRequest(
                amount=100,
                date=date(2026, 8, 27),
                document_name="comprobante-individual.pdf",
            ),
        ],
    )

    assert (
        request.transactions[0].document_name or request.document_name
    ) == "comprobante-individual.pdf"


def test_create_individual_stores_document_name():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    permission = Permission(level="client", hierarchy=1)
    currency = Currency(name="ARS")
    entity = Entity(name="Entidad", mail="entidad@example.com", status="enabled")
    cbu = CBU(
        nro="0" * 22,
        banco="Banco",
        alias="entidad.test",
        cuit="30987654321",
    )
    db.add_all([permission, currency, entity, cbu])
    db.flush()
    db.add(EntityCBU(entity_id=entity.id, cbu_id=cbu.id, currency_id=currency.id))
    client = Clients(
        first_name="Cliente",
        last_name="Prueba",
        email="individual@example.com",
        hashed_password="hash",
        perm_id=permission.id,
        entity_id=entity.id,
    )
    db.add(client)
    db.flush()
    account = CustomersBalance(
        client_id=client.id,
        balance_currency_id=currency.id,
    )
    db.add(account)
    db.commit()

    request = DocumentRequest(
        document_name="comprobante-individual.pdf",
        amount=100,
        trx_id="INDIVIDUAL-001",
        emisor_name="Emisor",
        emisor_cuit="20123456789",
        receptor_cuit=cbu.cuit,
        date=date(2026, 8, 27),
        account_id=account.id,
    )

    TransactionsService(db, {"entity_id": entity.id}).create(request, {})

    transaction = db.query(Trx).one()
    assert transaction.document_name == "comprobante-individual.pdf"
    assert transaction.client_id == client.id
    db.close()


def test_get_all_filters_by_partial_document_name():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    permission = Permission(level="admin", hierarchy=1)
    currency = Currency(name="ARS")
    entity = Entity(name="Entidad", mail="entidad-filter@example.com", status="enabled")
    db.add_all([permission, currency, entity])
    db.flush()
    user = Users(
        first_name="Usuario",
        last_name="Prueba",
        email="usuario-filter@example.com",
        hashed_password="hash",
        perm_id=permission.id,
        entity_id=entity.id,
    )
    client = Clients(
        first_name="Cliente",
        last_name="Prueba",
        email="cliente-filter@example.com",
        hashed_password="hash",
        perm_id=permission.id,
        entity_id=entity.id,
    )
    db.add_all([user, client])
    db.flush()
    account = CustomersBalance(
        client_id=client.id,
        balance_currency_id=currency.id,
    )
    db.add(account)
    db.flush()
    for trx_id, document_name in (
        ("FILTER-001", "Transferencias-Agosto.pdf"),
        ("FILTER-002", "comprobante-julio.jpg"),
    ):
        db.add(
            Trx(
                trx_id=trx_id,
                document_name=document_name,
                emisor_name="Emisor",
                emisor_cuit="20123456789",
                receptor_cbu="0" * 22,
                entity_id=entity.id,
                amount=100,
                date=date(2026, 8, 27),
                status="pendiente",
                account_id=account.id,
            )
        )
    db.commit()

    response = TransactionsService(
        db,
        {"id": user.id, "entity_id": entity.id},
    ).get_all(document_name="agosto")

    transactions = response["result"]["transactions"]
    assert [trx.trx_id for trx in transactions] == ["FILTER-001"]
    db.close()
