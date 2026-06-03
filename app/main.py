from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.db.database import create_tables
from app.router import (
    auth,
    transactions,
    users,
    entities,
    products,
    clients,
    payments,
    balance,
    currency,
    extractor,
    textract,
    logs,
)
from app.middlewares.PermissionMiddleware import PermissionMiddleware
from dotenv import load_dotenv
import os

load_dotenv(dotenv_path="dev.env")  # Esto carga las variables al entorno
ENV = os.getenv("ENVIRONMENT", "dev")
app = FastAPI(
    docs_url="/docs" if ENV == "dev" else None,
    redoc_url="/redoc" if ENV == "dev" else None,
    openapi_url="/openapi.json" if ENV == "dev" else None,
)

app.add_middleware(PermissionMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("ALLOW_ORIGINS")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

create_tables()
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(transactions.router)
app.include_router(entities.router)
app.include_router(products.router)
app.include_router(clients.router)
app.include_router(payments.router)
app.include_router(balance.router)
app.include_router(currency.router)
app.include_router(extractor.router)
app.include_router(textract.router)
app.include_router(logs.router)
