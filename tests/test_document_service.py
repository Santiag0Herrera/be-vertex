import base64
import datetime
import os
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from dateutil.relativedelta import relativedelta

os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/vertex_document_tests.db")

from app.models import (
    Base,
    Clients,
    Currency,
    CustomersBalance,
    Entity,
    Permission,
    TransactionDocument,
    Trx,
    Users,
)
from app.schemas.documents import CreateUploadSessionRequest, UploadDocumentRequest
from app.schemas.transactions import DocumentRequest, MultipleDocumentRequest
from app.services.DocumentService import DocumentService
from app.jobs import validate_trx


class FakeStorage:
    max_size_bytes = 10 * 1024 * 1024
    view_ttl_seconds = 120

    def __init__(self):
        self.documents = {}
        self.deleted = []
        self.copied = []

    @staticmethod
    def staging_key(entity_id, session_id, document_id):
        return f"staging/{entity_id}/{session_id}/{document_id}"

    @staticmethod
    def object_key(entity_id, document_id):
        return f"documents/{entity_id}/{document_id}"

    def create_upload_form(self, *, key, mime_type, sha256, size_bytes):
        prefixes = {
            "application/pdf": b"%PDF-1.7",
            "image/jpeg": b"\xff\xd8\xff",
            "image/png": b"\x89PNG\r\n\x1a\n",
            "image/tiff": b"II*\x00",
        }
        self.documents[key] = {
            "ContentLength": size_bytes,
            "ContentType": mime_type,
            "Metadata": {"sha256": sha256},
            "ChecksumSHA256": base64.b64encode(bytes.fromhex(sha256)).decode(
                "ascii"
            ),
            "Body": prefixes[mime_type],
        }
        return {"url": "https://example.invalid", "fields": {"key": key}}

    def head(self, key):
        return self.documents[key]

    def read_prefix(self, key, length=16):
        return self.documents[key]["Body"][:length]

    def copy(self, source_key, destination_key):
        self.documents[destination_key] = self.documents[source_key]
        self.copied.append((source_key, destination_key))

    def delete(self, key):
        self.deleted.append(key)
        self.documents.pop(key, None)

    def create_view_url(self, *, key, original_name, mime_type):
        return f"https://example.invalid/view/{key}"


def _database():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine)()


def _seed(db):
    permission = Permission(level="admin", hierarchy=100)
    currency = Currency(name="ARS")
    entity = Entity(name="Entidad", mail="entity@example.com", status="enabled")
    db.add_all([permission, currency, entity])
    db.flush()
    user = Users(
        first_name="Admin",
        last_name="Test",
        email="admin-docs@example.com",
        hashed_password="hash",
        perm_id=permission.id,
        entity_id=entity.id,
    )
    client = Clients(
        first_name="Client",
        last_name="Test",
        email="client-docs@example.com",
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
    db.commit()
    request_user = {
        "id": user.id,
        "entity_id": entity.id,
        "account_type": "user",
        "user_perm": "admin",
    }
    return entity, user, client, account, request_user


def test_upload_session_commits_document_and_is_idempotent():
    engine, db = _database()
    try:
        entity, _, _, account, request_user = _seed(db)
        storage = FakeStorage()
        service = DocumentService(db, request_user, storage=storage)
        client_document_id = uuid4()
        sha256 = "a" * 64
        session = service.create_upload_session(
            CreateUploadSessionRequest(
                documents=[
                    UploadDocumentRequest(
                        client_document_id=client_document_id,
                        original_name="comprobante.pdf",
                        mime_type="application/pdf",
                        size_bytes=100,
                        sha256=sha256,
                    )
                ]
            )
        )
        request = MultipleDocumentRequest(
            upload_session_id=session["upload_session_id"],
            account_id=account.id,
            owner_account_number="09170210248397",
            transactions=[
                DocumentRequest(
                    client_document_id=client_document_id,
                    document_name="comprobante.pdf",
                    amount=100,
                    date=datetime.date(2026, 10, 5),
                )
            ],
        )

        response = service.create_multiple_transactions(request)
        repeated_response = service.create_multiple_transactions(request)

        assert response["result"]["created"] == 1
        assert repeated_response == response
        assert db.query(Trx).count() == 1
        document = db.query(TransactionDocument).one()
        assert document.status == "active"
        assert document.trx_id == db.query(Trx).one().id
        assert document.object_key == f"documents/{entity.id}/{document.id}"
        assert len(storage.copied) == 1
    finally:
        db.close()
        engine.dispose()


def test_duplicate_receipt_does_not_leave_a_persisted_document():
    engine, db = _database()
    try:
        _, _, _, account, request_user = _seed(db)
        storage = FakeStorage()
        service = DocumentService(db, request_user, storage=storage)

        def create_receipt(file_sha256: str, client_document_id):
            upload_session = service.create_upload_session(
                CreateUploadSessionRequest(
                    documents=[
                        UploadDocumentRequest(
                            client_document_id=client_document_id,
                            original_name="comprobante.pdf",
                            mime_type="application/pdf",
                            size_bytes=100,
                            sha256=file_sha256,
                        )
                    ]
                )
            )
            return service.create_multiple_transactions(
                MultipleDocumentRequest(
                    upload_session_id=upload_session["upload_session_id"],
                    account_id=account.id,
                    owner_account_number="09170210248397",
                    transactions=[
                        DocumentRequest(
                            client_document_id=client_document_id,
                            document_name="comprobante.pdf",
                            file_sha256=file_sha256,
                            amount=100,
                            date=datetime.datetime(2026, 10, 5, 10, 30),
                        )
                    ],
                )
            )

        first_response = create_receipt("d" * 64, uuid4())
        copies_after_first_receipt = len(storage.copied)
        second_client_document_id = uuid4()
        duplicate_response = create_receipt("e" * 64, second_client_document_id)

        assert first_response["result"]["created"] == 1
        assert duplicate_response["result"]["created"] == 0
        assert len(duplicate_response["result"]["duplicates"]) == 1
        assert db.query(Trx).count() == 1
        assert db.query(TransactionDocument).count() == 1
        assert len(storage.copied) == copies_after_first_receipt
        assert all(
            not key.startswith("staging/") for key in storage.documents
        )
    finally:
        db.close()
        engine.dispose()


def test_manual_delete_only_removes_expired_active_documents():
    engine, db = _database()
    try:
        _, _, _, account, request_user = _seed(db)
        storage = FakeStorage()
        service = DocumentService(db, request_user, storage=storage)
        client_document_id = uuid4()
        session = service.create_upload_session(
            CreateUploadSessionRequest(
                documents=[
                    UploadDocumentRequest(
                        client_document_id=client_document_id,
                        original_name="due.pdf",
                        mime_type="application/pdf",
                        size_bytes=50,
                        sha256="b" * 64,
                    )
                ]
            )
        )
        service.create_multiple_transactions(
            MultipleDocumentRequest(
                upload_session_id=session["upload_session_id"],
                account_id=account.id,
                owner_account_number="09170210248397",
                transactions=[
                    DocumentRequest(
                        client_document_id=client_document_id,
                        amount=50,
                        date=datetime.date(2026, 10, 5),
                    )
                ],
            )
        )
        document = db.query(TransactionDocument).one()
        final_key = document.object_key
        document.delete_after = datetime.datetime.now(
            datetime.timezone.utc
        ) - datetime.timedelta(minutes=1)
        db.commit()

        assert service.expired_summary() == {"eligible": 1, "size_bytes": 50}
        result = service.delete_expired()

        db.refresh(document)
        assert result == {
            "eligible": 1,
            "attempted": 1,
            "deleted": 1,
            "failed": 0,
            "remaining": 0,
            "failed_document_ids": [],
        }
        assert document.status == "deleted"
        assert document.deleted_at is not None
        assert final_key in storage.deleted
    finally:
        db.close()
        engine.dispose()


def test_reconciliation_sets_delete_after_without_deleting_document(monkeypatch):
    engine, db = _database()
    try:
        _, _, _, account, request_user = _seed(db)
        storage = FakeStorage()
        service = DocumentService(db, request_user, storage=storage)
        client_document_id = uuid4()
        session = service.create_upload_session(
            CreateUploadSessionRequest(
                documents=[
                    UploadDocumentRequest(
                        client_document_id=client_document_id,
                        original_name="reconcile.pdf",
                        mime_type="application/pdf",
                        size_bytes=75,
                        sha256="c" * 64,
                    )
                ]
            )
        )
        service.create_multiple_transactions(
            MultipleDocumentRequest(
                upload_session_id=session["upload_session_id"],
                account_id=account.id,
                owner_account_number="09170210248397",
                transactions=[
                    DocumentRequest(
                        client_document_id=client_document_id,
                        amount=75,
                        date=datetime.date(2026, 10, 5),
                    )
                ],
            )
        )
        transaction = db.query(Trx).one()
        monkeypatch.setattr(validate_trx, "SessionLocal", sessionmaker(bind=engine))

        assert validate_trx.update_trx_status(
            trx_id=transaction.trx_id,
            new_status="conciliado",
            customer_balance_id=account.id,
            trx_amount=transaction.amount,
            fee_percentage=0,
            document_fingerprint="fingerprint-1",
        )

        db.expire_all()
        transaction = db.query(Trx).one()
        document = db.query(TransactionDocument).one()
        assert transaction.reconciled_at is not None
        assert document.delete_after == transaction.reconciled_at + relativedelta(
            months=2
        )
        assert document.status == "active"
        assert document.object_key in storage.documents
        assert service.delete_expired()["eligible"] == 0
        db.refresh(document)
        assert document.status == "active"
        assert document.object_key in storage.documents
    finally:
        db.close()
        engine.dispose()
