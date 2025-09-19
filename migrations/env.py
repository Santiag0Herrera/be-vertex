import os
import sys
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context

# --- RUTA DEL PROYECTO PARA IMPORTAR app.*
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

# Cargar metadata
from app.models import Base  # <-- tu declarative_base con todos los modelos

# Si usás variables de entorno (dev.env), podés usar python-dotenv si querés:
# from dotenv import load_dotenv
# load_dotenv("dev.env")

# Config Alembic
config = context.config
fileConfig(config.config_file_name)

# Setear la URL desde env var (no desde alembic.ini)
DATABASE_URL = os.getenv("SQLALCHEMY_DATABASE_URL")  # ej: postgresql://user:pass@host:5432/db
if DATABASE_URL:
    config.set_main_option("sqlalchemy.url", DATABASE_URL)

target_metadata = Base.metadata

def run_migrations_offline():
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,   # detecta cambios de tipo
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()