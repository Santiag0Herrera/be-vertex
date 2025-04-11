from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from db.database import create_tables
from router import auth, transactions, users, entities, products, clients
from middlewares.PermissionMiddleware import PermissionMiddleware

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