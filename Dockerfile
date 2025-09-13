FROM python:3.11-slim

# Evita que Python genere .pyc y buffers
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Instalar system deps (psycopg2-bin más liviano que psycopg2)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Reqs primero (mejor caché)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiamos el código
COPY app ./app

# Expone el puerto del backend
EXPOSE 8000

# Por defecto usamos variables que vendrán de dev.env
CMD ["sh", "-c", "uvicorn app.main:app --host ${UVICORN_HOST:-0.0.0.0} --port ${UVICORN_PORT:-8000} --reload"]