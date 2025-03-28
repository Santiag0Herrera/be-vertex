from fastapi import FastAPI
import models
from db.database import engine
from router import auth, transactions, users, entities

app = FastAPI()
models.Base.metadata.create_all(bind=engine)
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(transactions.router)
app.include_router(entities.router)
