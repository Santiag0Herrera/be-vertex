
# 🧬 Database Models Documentation

This document describes the SQLAlchemy ORM models used in the system.

---

## 👤 Users
Represents system users.

- **Table name:** `users`
- **Fields:**
  - `id`: Integer, Primary Key
  - `first_name`: String, not null
  - `last_name`: String, not null
  - `email`: String, unique, not null
  - `hashed_password`: String, not null
  - `phone`: String
  - `perm_id`: ForeignKey to `permissions.id`
  - `entity_id`: ForeignKey to `entities.id`
- **Relationships:**
  - `entity`: Linked to `Entity`
  - `permission`: Linked to `Permission`

---

## 🏢 Entity
Represents a business entity.

- **Table name:** `entities`
- **Fields:**
  - `id`: Integer, Primary Key
  - `name`: String, not null
  - `mail`: String, not null
  - `phone`: String
  - `products`: String
  - `status`: String
  - `cbu_id`: ForeignKey to `cbus.id`
- **Relationships:**
  - `users`: Linked to `Users`
  - `cbu`: Linked to `CBU`

---

## 🔐 Permission
Defines user access levels and hierarchies.

- **Table name:** `permissions`
- **Fields:**
  - `id`: Integer, Primary Key
  - `product`: ForeignKey to `products.id`
  - `level`: String, not null
  - `hierarchy`: Integer, not null
- **Relationships:**
  - `users`: Linked to `Users`
  - `product_rel`: Linked to `Product`
  - `endpoints`: Linked to `Endpoints`

---

## 📦 Product
Defines products or services available in the system.

- **Table name:** `products`
- **Fields:**
  - `id`: Integer, Primary Key
  - `name`: String, not null
  - `description`: String, not null
  - `img`: String, not null
  - `path`: String, not null
- **Relationships:**
  - `permissions`: Linked to `Permission`

---

## 💸 Trx
Represents a financial transaction.

- **Table name:** `trx`
- **Fields:**
  - `id`: Integer, Primary Key
  - `trx_id`: String, unique
  - `emisor_cbu`: String, nullable
  - `emisor_name`: String, not null
  - `emisor_cuit`: String, not null
  - `receptor_cbu`: String, not null
  - `entity_id`: ForeignKey to `entities.id`
  - `amount`: Float, not null
  - `date`: String, not null
  - `status`: String, not null

---

## 🏦 CBU
Represents a unique bank account identifier.

- **Table name:** `cbus`
- **Fields:**
  - `id`: Integer, Primary Key
  - `nro`: String, unique, not null
  - `banco`: String, not null
  - `alias`: String, not null
  - `cuit`: String, not null
- **Relationships:**
  - `entity`: Linked to `Entity` (one-to-one)

---

## 📍 Endpoints
Defines protected API endpoints and required permissions.

- **Table name:** `endpoints`
- **Fields:**
  - `id`: Integer, Primary Key
  - `path`: String, unique, not null
  - `perm_id`: ForeignKey to `permissions.id`
- **Relationships:**
  - `permission`: Linked to `Permission`
