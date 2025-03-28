from sqlalchemy import Column, Integer, String, Float, ForeignKey
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


# Entity Model
class Entity(Base):
    __tablename__ = "entities"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    mail = Column(String, nullable=False)
    phone = Column(String)
    products = Column(String)
    status = Column(String)
    cbu_id = Column(Integer, ForeignKey("cbus.id"))

    users = relationship("Users", back_populates="entity")
    cbu = relationship("CBU", back_populates="entity")


# Permission Model
class Permission(Base):
    __tablename__ = "permissions"

    id = Column(Integer, primary_key=True, index=True)
    product = Column(Integer, ForeignKey("products.id"))
    level = Column(String, nullable=False)

    users = relationship("Users", back_populates="permission")
    product_rel = relationship("Product", back_populates="permissions")


# Product Model
class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    path = Column(String, nullable=False)

    permissions = relationship("Permission", back_populates="product_rel")


# Trx Model
class Trx(Base):
    __tablename__ = "trx"

    id = Column(Integer, primary_key=True, index=True)
    emisorCBU = Column(String, nullable=False)
    emisorName = Column(String, nullable=False)
    emisorCUIT = Column(String, nullable=False)
    receptorCBU = Column(String, nullable=False)
    entityId = Column(Integer, ForeignKey("entities.id"))
    amount = Column(Float, nullable=False)
    date = Column(String, nullable=False)


# CBU Model
class CBU(Base):
    __tablename__ = "cbus"

    id = Column(Integer, primary_key=True, index=True)
    nro = Column(String, unique=True, nullable=False)
    banco = Column(String, nullable=False)
    alias = Column(String, nullable=False)
    cuit = Column(String, nullable=False)

    entity = relationship("Entity", back_populates="cbu", uselist=False)
