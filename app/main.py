from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.db.database import create_tables
from app.router import auth, transactions, users, entities, products, clients, payments, balance
from app.middlewares.PermissionMiddleware import PermissionMiddleware
from dotenv import load_dotenv

load_dotenv(dotenv_path="dev.env")  # Esto carga las variables al entorno
app = FastAPI()

app.add_middleware(PermissionMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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