from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm import declarative_base

SQLALCHEMY_DATABASE_URL = 'postgresql://vertex:vertex2025@cddatabase.cc1ao8osa9zo.us-east-1.rds.amazonaws.com:5432/cddatabase'
engine = create_engine(SQLALCHEMY_DATABASE_URL)

SessionLocal = sessionmaker(autoflush=False, autocommit=False, bind=engine)
Base = declarative_base()

def create_tables():
    """
    Creates all tables in the database based on the SQLAlchemy models.
    """
    try:
        print("Creating tables in the database...")
        Base.metadata.create_all(bind=engine)
        print("Tables created successfully!")
    except Exception as e:
        print(f"An error occurred while creating tables: {e}")