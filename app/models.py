from datetime import datetime
from zoneinfo import ZoneInfo
from sqlalchemy import BigInteger, Column, Date, DateTime, Integer, String, Float, ForeignKey, Boolean, Numeric, CheckConstraint, Index, Text, UniqueConstraint, text
from sqlalchemy.orm import relationship

from app.db.database import Base


def business_today():
    return datetime.now(ZoneInfo("America/Argentina/Buenos_Aires")).date()

# User Model
class Users(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    first_name = Column(String, nullable=False)
    last_name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    phone = Column(String)
    perm_id = Column(Integer, ForeignKey("permissions.id"))
    entity_id = Column(Integer, ForeignKey("entities.id"))
    enabled = Column(Boolean, nullable=False, default=True)

    entity = relationship("Entity", back_populates="users")
    permission = relationship("Permission", back_populates="users")
    payments = relationship("Payments", back_populates="payee_user")  # ⇦ contraparte de Payments.payee_user


# Entity Model
class Entity(Base):
    __tablename__ = "entities"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    mail = Column(String, nullable=False)
    phone = Column(String)
    products = Column(String)
    status = Column(String)

    users = relationship("Users", back_populates="entity")
    clients = relationship("Clients", back_populates="entity")
    trxs = relationship("Trx", back_populates="entity")
    document_upload_sessions = relationship("DocumentUploadSession", back_populates="entity")
    transaction_documents = relationship("TransactionDocument", back_populates="entity")
    cbus = relationship("EntityCBU", back_populates="entity", cascade="all, delete-orphan")


class EntityCBU(Base):
    __tablename__ = "entities_cbus"

    id = Column(Integer, primary_key=True)
    entity_id = Column(Integer, ForeignKey("entities.id"), nullable=False)
    cbu_id = Column(Integer, ForeignKey("cbus.id"), nullable=False)
    currency_id = Column(Integer, ForeignKey("currency.id"), nullable=False)

    entity = relationship("Entity", back_populates="cbus")
    cbu = relationship("CBU", back_populates="entities")
    currency = relationship("Currency", back_populates="entity_cbus")

# Permission Model
class Permission(Base):
    __tablename__ = "permissions"

    id = Column(Integer, primary_key=True, index=True)
    product = Column(Integer, ForeignKey("products.id"))
    level = Column(String, nullable=False)
    hierarchy = Column(Integer, nullable=False)

    users = relationship("Users", back_populates="permission")
    product_rel = relationship("Product", back_populates="permissions")
    endpoints = relationship("Endpoints", back_populates="permission")
    clients = relationship("Clients", back_populates="permission")      # ⇦ nuevo


# Product Model
class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(String, nullable=False)
    img = Column(String, nullable=False)
    path = Column(String, nullable=False)

    permissions = relationship("Permission", back_populates="product_rel")


# Trx Model
class Trx(Base):
    __tablename__ = "trx"
    __table_args__ = (
        Index(
            "uq_trx_conciliated_document_fingerprint",
            "document_fingerprint",
            unique=True,
            postgresql_where=text(
                "status = 'conciliado' AND document_fingerprint IS NOT NULL"
            ),
            sqlite_where=text(
                "status = 'conciliado' AND document_fingerprint IS NOT NULL"
            ),
        ),
    )

    document_fingerprint = Column(String, nullable=True, index=True)
    document_name = Column(String, nullable=True)
    id = Column(Integer, primary_key=True, index=True)
    trx_id = Column(String, unique=True)
    emisor_cbu = Column(String, nullable=True)
    emisor_name = Column(String, nullable=False)
    emisor_cuit = Column(String, nullable=False)
    receptor_cbu = Column(String, nullable=False)
    entity_id = Column(Integer, ForeignKey("entities.id"))
    client_id = Column(Integer, ForeignKey("clients.id"))
    amount = Column(Float, nullable=False)
    date = Column(DateTime, nullable=False)
    received_date = Column(Date, nullable=False, default=business_today)
    creation_date = Column(DateTime, default=datetime.utcnow)
    reconciled_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(String, nullable=False)
    account_id = Column(Integer, ForeignKey("customers_balance.id"), nullable=False)
    applied_fee_percentage = Column(Float, nullable=True)
    fee_amount = Column(Float, nullable=True)

    entity = relationship("Entity", back_populates="trxs")
    client = relationship("Clients", back_populates="trxs")
    account = relationship("CustomersBalance")
    document = relationship("TransactionDocument", back_populates="trx", uselist=False)


class DocumentUploadSession(Base):
    __tablename__ = "document_upload_sessions"

    id = Column(String(36), primary_key=True)
    entity_id = Column(Integer, ForeignKey("entities.id"), nullable=False, index=True)
    actor_id = Column(Integer, nullable=False)
    actor_type = Column(String(20), nullable=False)
    status = Column(String(20), nullable=False, default="created", index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    committed_at = Column(DateTime(timezone=True), nullable=True)
    result_json = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    entity = relationship("Entity", back_populates="document_upload_sessions")
    documents = relationship(
        "TransactionDocument",
        back_populates="upload_session",
        cascade="all, delete-orphan",
    )


class TransactionDocument(Base):
    __tablename__ = "transaction_documents"
    __table_args__ = (
        UniqueConstraint(
            "upload_session_id",
            "client_document_id",
            name="uq_transaction_documents_session_client_id",
        ),
    )

    id = Column(String(36), primary_key=True)
    upload_session_id = Column(
        String(36),
        ForeignKey("document_upload_sessions.id"),
        nullable=False,
        index=True,
    )
    client_document_id = Column(String(36), nullable=False)
    trx_id = Column(Integer, ForeignKey("trx.id"), nullable=True, unique=True, index=True)
    entity_id = Column(Integer, ForeignKey("entities.id"), nullable=False, index=True)
    staging_key = Column(String, nullable=False, unique=True)
    object_key = Column(String, nullable=True, unique=True)
    original_name = Column(String(255), nullable=False)
    mime_type = Column(String(100), nullable=False)
    size_bytes = Column(BigInteger, nullable=False)
    sha256 = Column(String(64), nullable=False)
    status = Column(String(30), nullable=False, default="pending_upload", index=True)
    uploaded_at = Column(DateTime(timezone=True), nullable=True)
    activated_at = Column(DateTime(timezone=True), nullable=True)
    delete_after = Column(DateTime(timezone=True), nullable=True, index=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    deletion_attempts = Column(Integer, nullable=False, default=0)
    last_deletion_error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    upload_session = relationship("DocumentUploadSession", back_populates="documents")
    trx = relationship("Trx", back_populates="document")
    entity = relationship("Entity", back_populates="transaction_documents")


# CBU Model
class CBU(Base):
    __tablename__ = "cbus"

    id = Column(Integer, primary_key=True, index=True)
    nro = Column(String, unique=True, nullable=False)
    banco = Column(String, nullable=False)
    alias = Column(String, nullable=False)
    cuit = Column(String, nullable=False)

    entities = relationship("EntityCBU", back_populates="cbu", cascade="all, delete-orphan")


class Endpoints(Base):
    __tablename__ = "endpoints"

    id = Column(Integer, primary_key=True, index=True)
    path = Column(String, unique=True, nullable=False)
    perm_id = Column(Integer, ForeignKey("permissions.id"))

    permission = relationship("Permission", back_populates="endpoints")


class Logs(Base):
    __tablename__ = "logs"

    id = Column(Integer, primary_key=True, index=True)
    datetime = Column(String, nullable=False)
    endpoint = Column(String, nullable=False)
    method = Column(String, nullable=False)
    username = Column(String, nullable=False)


class Payments(Base):
    __tablename__= "payments"

    id = Column(Integer, primary_key=True, index=True)
    payee_user_id = Column(Integer, ForeignKey("users.id"))
    amount = Column(Float, nullable=False)
    date = Column(DateTime, default=datetime.utcnow)
    status = Column(String, nullable=False)
    customer_balance_id = Column(Integer, ForeignKey("customers_balance.id"))
    currency_id = Column(Integer, ForeignKey("currency.id"))
    entity_id = Column(Integer, ForeignKey("entities.id"), nullable=False)

    payment_order_id = Column(Integer, ForeignKey("payment_orders.id"), nullable=True, index=True)

    payee_user = relationship("Users", back_populates="payments")
    customer_balance = relationship("CustomersBalance")
    currency = relationship("Currency")
    entity = relationship("Entity")

class Clients(Base):
    __tablename__ = "clients"

    id = Column(Integer, primary_key=True, index=True)
    first_name = Column(String, nullable=False)
    last_name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False)
    # Nullable mientras se completan los CUIT de los clientes existentes.
    # Las altas y modificaciones lo exigen mediante los esquemas de Pydantic.
    cuit = Column(String(11), nullable=True)
    hashed_password = Column(String, nullable=False)
    phone = Column(String)
    perm_id = Column(Integer, ForeignKey("permissions.id"), nullable=False)
    entity_id = Column(Integer, ForeignKey("entities.id"), nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)

    entity = relationship("Entity", back_populates="clients")
    permission = relationship("Permission", back_populates="clients")
    balance = relationship("CustomersBalance", back_populates="client", uselist=True)  # ⇦ balance⇄client
    trxs = relationship("Trx", back_populates="client")                                  # ⇦ nuevo


class CustomersBalance(Base):
    __tablename__ = "customers_balance"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    balance_amount = Column(Float, nullable=False, default=0.0)
    fee_amount = Column(Float, nullable=False, default=0.0)
    balance_currency_id = Column(Integer, ForeignKey("currency.id"), nullable=False)
    last_update = Column(DateTime, nullable=False, default=datetime.utcnow)
    fee_percentage = Column(Float, nullable=False, default=0)
    enabled = Column(Boolean, nullable=False, default=True)

    client = relationship("Clients", back_populates="balance", lazy="joined")
    currency = relationship("Currency", back_populates="balances")
    fee_withdrawals = relationship("FeeWithdrawals", back_populates="customer_balance")


class FeeWithdrawals(Base):
    __tablename__ = "fee_withdrawals"

    id = Column(Integer, primary_key=True, index=True)
    customer_balance_id = Column(Integer, ForeignKey("customers_balance.id"), nullable=False)
    withdrawn_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    entity_id = Column(Integer, ForeignKey("entities.id"), nullable=False)
    currency_id = Column(Integer, ForeignKey("currency.id"), nullable=False)
    amount = Column(Float, nullable=False)
    date = Column(DateTime, nullable=False, default=datetime.utcnow)
    status = Column(String, nullable=False, default="consolidado")

    customer_balance = relationship("CustomersBalance", back_populates="fee_withdrawals")
    withdrawn_by_user = relationship("Users")
    entity = relationship("Entity")
    currency = relationship("Currency")


class Currency(Base):
    __tablename__ = "currency"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)

    balances = relationship("CustomersBalance", back_populates="currency")
    entity_cbus = relationship("EntityCBU", back_populates="currency")


class PaymentOrders(Base):
    __tablename__ = "payment_orders"
    __table_args__ = (
        CheckConstraint("amount > 0", name="payment_order_positive_amount"),
        CheckConstraint("executed_amount >= 0 AND executed_amount <= amount", name="payment_order_execution_amount"),
        CheckConstraint("status IN ('pendiente_aprobacion', 'parcialmente_ejecutada', 'ejecutada')", name="payment_order_status"),
    )

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    customer_balance_id = Column(Integer, ForeignKey("customers_balance.id"), nullable=False)
    entity_id = Column(Integer, ForeignKey("entities.id"), nullable=False, index=True)
    currency_id = Column(Integer, ForeignKey("currency.id"), nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    executed_amount = Column(Numeric(10, 2), nullable=False, default=0)
    status = Column(String, nullable=False, default="pendiente_aprobacion")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
