from datetime import datetime
from sqlalchemy import Column, DateTime, Integer, String, Float, ForeignKey
from sqlalchemy.orm import relationship, declarative_base

Base = declarative_base()

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
    cbus = relationship("EntityCBU", back_populates="entity", cascade="all, delete-orphan")


class EntityCBU(Base):
    __tablename__ = "entities_cbus"

    id = Column(Integer, primary_key=True)
    entity_id = Column(Integer, ForeignKey("entities.id"), nullable=False)
    cbu_id = Column(Integer, ForeignKey("cbus.id"), nullable=False)

    entity = relationship("Entity", back_populates="cbus")
    cbu = relationship("CBU")

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

    id = Column(Integer, primary_key=True, index=True)
    trx_id = Column(String, unique=True)
    emisor_cbu = Column(String, nullable=True)
    emisor_name = Column(String, nullable=False)
    emisor_cuit = Column(String, nullable=False)
    receptor_cbu = Column(String, nullable=False)
    entity_id = Column(Integer, ForeignKey("entities.id"))
    client_id = Column(Integer, ForeignKey("clients.id"))
    amount = Column(Float, nullable=False)
    date = Column(String, nullable=False)
    status = Column(String, nullable=False)
    account_id = Column(Integer, ForeignKey("customers_balance.id"), nullable=False)

    entity = relationship("Entity", back_populates="trxs")
    client = relationship("Clients", back_populates="trxs")
    account = relationship("CustomersBalance")


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
    hashed_password = Column(String, nullable=False)
    phone = Column(String)
    perm_id = Column(Integer, ForeignKey("permissions.id"), nullable=False)
    entity_id = Column(Integer, ForeignKey("entities.id"), nullable=False)

    entity = relationship("Entity", back_populates="clients")
    permission = relationship("Permission", back_populates="clients")
    balance = relationship("CustomersBalance", back_populates="client", uselist=False)  # ⇦ balance⇄client
    trxs = relationship("Trx", back_populates="client")                                  # ⇦ nuevo


class CustomersBalance(Base):
    __tablename__ = "customers_balance"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), unique=True, nullable=False)
    balance_amount = Column(Float, nullable=False, default=0.0)
    balance_currency_id = Column(Integer, ForeignKey("currency.id"), nullable=False)
    last_update = Column(DateTime, nullable=False, default=datetime.utcnow)

    client = relationship("Clients", back_populates="balance", lazy="joined")
    currency = relationship("Currency", back_populates="balances")


class Currency(Base):
    __tablename__ = "currency"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)

    balances = relationship("CustomersBalance", back_populates="currency")