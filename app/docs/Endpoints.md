
# 📘 API Endpoint Documentation

This document provides an overview of the available API endpoints across different modules of the application. Each section lists endpoints defined in a specific module and describes their purpose and usage.

---

## 🔐 `auth.py`
Authentication and user token management endpoints.

- **POST /auth/register**  
  Registers a new user.

- **POST /auth/token**  
  Authenticates an internal user by email or a client by CUIT and returns a JWT token.

- **GET /auth/me**  
  Returns the currently authenticated user's details.

---

## 👤 `users.py`
User management endpoints.

- **GET /users/**  
  Lists all users.

- **POST /users/**  
  Creates a new user.

- **GET /users/{user_id}**  
  Retrieves a specific user by ID.

- **PUT /users/{user_id}**  
  Updates user information.

- **DELETE /users/{user_id}**  
  Deletes a user.

---

## 🧾 `clients.py`
Client entity endpoints.

- **GET /clients/**  
  Lists all clients.

- **POST /clients/**  
  Creates a new client.

- **GET /clients/{client_id}**  
  Retrieves a specific client.

- **PUT /clients/{client_id}**  
  Updates client details.

- **DELETE /clients/{client_id}**  
  Removes a client.

---

## 🏢 `entities.py`
Entity (companies, banks, etc.) endpoints.

- **GET /entities/**  
  Retrieves all registered entities.

- **POST /entities/**  
  Adds a new entity.

- **GET /entities/{entity_id}**  
  Fetches a specific entity.

- **PUT /entities/{entity_id}**  
  Modifies an entity.

- **DELETE /entities/{entity_id}**  
  Deletes an entity.

---

## 📦 `products.py`
Product endpoints used for financial or service items.

- **GET /products/**  
  Lists all products.

- **POST /products/**  
  Adds a new product.

- **GET /products/{product_id}**  
  Retrieves product details.

- **PUT /products/{product_id}**  
  Updates product information.

- **DELETE /products/{product_id}**  
  Deletes a product.

---

## 💸 `transactions.py`
Bank transaction and payment endpoints.

- **GET /transactions/**  
  Lists all transactions.

- **POST /transactions/**  
  Uploads and registers a new transaction.

- **GET /transactions/{transaction_id}**  
  Retrieves a specific transaction.

- **PUT /transactions/{transaction_id}**  
  Updates transaction details.

- **DELETE /transactions/{transaction_id}**  
  Deletes a transaction.

- **GET /trx/all_by_client**
  Lists only the authenticated client's transactions.

---

## 💰 `balance.py`

- **GET /balance/all**
  Lists the balances for all clients belonging to an internal user's entity.

- **GET /balance/detail?account_id={id}**
  Returns balance details and movements for an internal user's entity.

- **GET /balance/client/all**
  Lists only the authenticated client's balances.

- **GET /balance/client/detail?account_id={id}**
  Returns a balance and its movements only when it belongs to the authenticated client.

## Órdenes de pago

Aplicar `migrations/20260908_payment_orders.sql` antes de desplegar sobre una base existente. Para una base nueva, utilizar los scripts de creación y datos iniciales actualizados. La migración copia permisos desde `/balance/client/all` y `/payments/create`; esas rutas deben estar registradas en `endpoints`.

- `POST /payment-orders/create`: exclusivo para clientes. Body: `{"customer_balance_id": 1, "amount": 500.00}`. La cuenta debe estar activa, pertenecer al cliente y tener saldo suficiente. La moneda se toma de la cuenta.
- `GET /payment-orders/all?page=0&recordsPerPage=10`: clientes ven sus órdenes; usuarios internos ven las de su entidad. Filtros opcionales: `status`, `customer_balance_id`. Devuelve `payment_orders`, `page`, `recordsPerPage`, `totalRecords` y `totalPages`. `recordsPerPage` admite de 1 a 100 registros.
- `GET /payment-orders/detail?order_id=1&page=0&recordsPerPage=10`: devuelve el detalle de la orden y pagina su historial `payments`, con el mismo alcance de acceso. Incluye `page`, `recordsPerPage`, `totalRecords` y `totalPages` correspondientes a los pagos. `recordsPerPage` admite de 1 a 100 registros.
- `POST /payment-orders/execute`: exclusivo para usuarios internos activos de la entidad. Body: `{"order_id": 1, "amount": 200.00}`. Omitir `amount` ejecuta todo el importe pendiente. `date` es opcional y por defecto usa la fecha actual UTC.

Las respuestas siguen `{"status": "ok", "result": ...}` e incluyen `amount`, `executed_amount`, `remaining_amount`, `status` e historial `payments` con el usuario ejecutor de cada pago.

Estados: `pendiente_aprobacion` → `parcialmente_ejecutada` → `ejecutada` (también puede ejecutarse totalmente desde pendiente). Ejecutar implica aprobar el importe ejecutado; no hay una aprobación separada.

Crear una orden no reserva ni descuenta saldo. Pueden coexistir solicitudes cuyo total exceda el saldo; cada ejecución vuelve a comprobar el saldo real. Los importes de órdenes admiten dos decimales. Un importe mayor al saldo o al remanente, o una orden ya ejecutada, devuelve 409.

Cada ejecución usa el servicio de pagos existente y crea un pago `consolidado` relacionado mediante `payments.payment_order_id`, visible en los movimientos habituales. Pago, descuento de saldo y actualización de la orden se confirman juntos; se bloquean la orden y la cuenta durante la ejecución en PostgreSQL. Los pagos directos conservan su respuesta y ahora también validan usuario, entidad, moneda y saldo, con actualización atómica.
