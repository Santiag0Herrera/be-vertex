import json
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import (
    Base,
    Clients,
    Currency,
    CustomersBalance,
    Entity,
    Permission,
    Trx,
)
from app.schemas.transactions import DocumentRequest, MultipleDocumentRequest
from app.services.ReceiptIdentityService import (
    build_receipt_fingerprint,
    duplicate_payload,
)
from app.services.TransactionsService import TransactionsService
from app.services.extractor.models import DocumentExtractResponse
from app.services.extractor.service import attach_document_identity


def complete_document(**overrides):
    values = {
        "document_name": "comprobante.pdf",
        "amount": 1500,
        "trx_id": "OP-ABC-123",
        "emisor_name": "Emisor",
        "emisor_cuit": "20-12345678-9",
        "receptor_name": "Receptor",
        "receptor_cuit": "30-98765432-1",
        "date": datetime(2026, 10, 6, 14, 30),
    }
    values.update(overrides)
    return DocumentRequest(**values)


def transaction_context():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    permission = Permission(level="admin", hierarchy=1)
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
    service = TransactionsService(
        db,
        {"entity_id": entity.id, "account_type": "user"},
    )
    return db, entity, account, service


def multiple_request(account_id, *documents):
    return MultipleDocumentRequest(
        account_id=account_id,
        owner_account_number="0430509162",
        transactions=list(documents),
    )


def test_semantic_fingerprint_survives_formatting_changes():
    first = complete_document()
    second = complete_document(
        trx_id=" op abc 123 ",
        emisor_cuit="20123456789",
        receptor_cuit="30.987.654.321",
        amount="1500.00",
    )

    assert build_receipt_fingerprint(first) == build_receipt_fingerprint(second)


def test_semantic_fingerprint_ignores_optional_operation_and_sender_data():
    first = complete_document()
    second = complete_document(
        trx_id=None,
        emisor_name=None,
        emisor_cuit=None,
        receptor_name=None,
        receptor_cuit=None,
    )

    assert build_receipt_fingerprint(first) == build_receipt_fingerprint(second)


def test_semantic_fingerprint_changes_for_a_different_time():
    first = complete_document()
    second = complete_document(date=datetime(2026, 10, 6, 14, 31))

    assert build_receipt_fingerprint(first) != build_receipt_fingerprint(second)


def test_extractor_attaches_exact_and_semantic_hashes():
    document = complete_document()
    result = DocumentExtractResponse(ok=True, document=document, partial={})

    attached = attach_document_identity(result, "comprobante.pdf", "a" * 64)

    assert attached.document.file_sha256 == "a" * 64
    assert attached.document.receipt_fingerprint == build_receipt_fingerprint(document)
    assert attached.partial["file_sha256"] == "a" * 64
    assert attached.partial["receipt_fingerprint"] == build_receipt_fingerprint(document)


def test_reexported_receipt_is_skipped_by_semantic_fingerprint():
    db, _, account, service = transaction_context()
    first = complete_document(file_sha256="a" * 64)
    reexported = complete_document(
        document_name="comprobante-reexportado.png",
        file_sha256="b" * 64,
    )

    first_result = service.create_multiple(multiple_request(account.id, first))
    duplicate_result = service.create_multiple(multiple_request(account.id, reexported))

    assert first_result["result"]["created"] == 1
    assert duplicate_result["result"]["created"] == 0
    assert duplicate_result["result"]["duplicates"][0]["matched_by"] == [
        "receipt_fingerprint"
    ]
    assert db.query(Trx).count() == 1
    db.close()


def test_same_file_is_skipped_even_when_extracted_fields_change():
    db, _, account, service = transaction_context()
    first = complete_document(file_sha256="c" * 64)
    changed_extraction = complete_document(
        trx_id="OTHER-OPERATION",
        amount=999,
        file_sha256="c" * 64,
    )

    service.create_multiple(multiple_request(account.id, first))
    duplicate_result = service.create_multiple(
        multiple_request(account.id, changed_extraction)
    )

    assert duplicate_result["result"]["created"] == 0
    assert duplicate_result["result"]["duplicates"][0]["matched_by"] == [
        "file_sha256"
    ]
    assert db.query(Trx).count() == 1
    db.close()


def test_duplicate_inside_one_batch_is_not_created_twice():
    db, _, account, service = transaction_context()
    first = complete_document(file_sha256="d" * 64)
    second = complete_document(
        document_name="otra-exportacion.jpg",
        file_sha256="e" * 64,
    )

    result = service.create_multiple(multiple_request(account.id, first, second))

    assert result["result"]["created"] == 1
    assert len(result["result"]["duplicates"]) == 1
    assert result["result"]["duplicates"][0]["matched_by"] == [
        "receipt_fingerprint"
    ]
    assert db.query(Trx).count() == 1
    db.close()


def test_receipt_without_optional_sender_data_can_be_created():
    db, _, account, service = transaction_context()
    minimal = DocumentRequest(
        amount=1500,
        date=datetime(2026, 10, 6, 14, 30),
    )

    result = service.create_multiple(multiple_request(account.id, minimal))
    transaction = db.query(Trx).one()

    assert result["result"]["created"] == 1
    assert transaction.source_trx_id is None
    assert transaction.emisor_name is None
    assert transaction.emisor_cuit is None
    assert transaction.emisor_cbu is None
    assert transaction.receipt_fingerprint
    db.close()


def test_duplicate_error_payload_is_json_serializable():
    db, entity, account, service = transaction_context()
    service.create_multiple(
        multiple_request(account.id, complete_document(file_sha256="f" * 64))
    )
    duplicate = db.query(Trx).filter(Trx.entity_id == entity.id).one()

    payload = duplicate_payload(duplicate, ["file_sha256"])

    assert json.loads(json.dumps(payload))["date"].startswith("2026-10-06")
    db.close()
