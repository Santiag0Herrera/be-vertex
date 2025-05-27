
# 📘 API Endpoint Documentation

This document provides an overview of the available API endpoints across different modules of the application. Each section lists endpoints defined in a specific module and describes their purpose and usage.

---

## 🔐 `auth.py`
Authentication and user token management endpoints.

- **POST /auth/register**  
  Registers a new user.

- **POST /auth/token**  
  Authenticates a user and returns a JWT token.

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

