from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm import declarative_base
import os

# SQLALCHEMY_DATABASE_URL = "postgresql://vertexmaster:vertex1234$$@vertex-database-testing.cc1ao8osa9zo.us-east-1.rds.amazonaws.com:5432/cddatabase?sslmode=require"
DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(autoflush=False, autocommit=False, bind=engine)
Base = declarative_base()

def create_tables():
  """
  Creates all tables in the database based on the SQLAlchemy models.
  """
  try:
      print("Conecting to database...")
      Base.metadata.create_all(bind=engine)
      print("Tables created successfully!")
  except Exception as e:
      print(f"An error occurred while creating tables: {e}")

def get_db():
  db = SessionLocal()
  try: 
    yield db
  finally:
    db.close()