from fastapi import FastAPI
import models
from db.database import create_tables
from router import auth, transactions, users, entities

app = FastAPI()
create_tables()
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(transactions.router)
app.include_router(entities.router)
