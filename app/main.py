from fastapi import FastAPI
import models
from db.database import engine
from router import auth, users

app = FastAPI()
models.Base.metadata.create_all(bind=engine)
app.include_router(auth.router)