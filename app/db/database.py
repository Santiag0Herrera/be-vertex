from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm import declarative_base
import os

DATABASE_URL = os.getenv("DATABASE_URL")

# engine = create_engine(DATABASE_URL)
engine = create_engine(
   DATABASE_URL, 
   pool_size=20, 
   max_overflow=40, 
   pool_timeout=60,
   pool_recycle=1800
)

SessionLocal = sessionmaker(autoflush=False, autocommit=False, bind=engine)
Base = declarative_base()

def create_tables():
  """
  Creates all tables in the database based on the SQLAlchemy models.
  """
  Base.metadata.create_all(bind=engine)

def get_db():
  db = SessionLocal()
  try: 
    yield db
  finally:
    db.close()
