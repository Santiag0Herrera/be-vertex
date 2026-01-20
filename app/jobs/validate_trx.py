# app/jobs/validate_trx.py

import datetime
from dotenv import load_dotenv
from sqlalchemy import text
load_dotenv()

from app.db.database import SessionLocal

SQL = """
SELECT
  trx.emisor_cbu as trx_emisor_cbu,
  receptor_cbu as trx_receptor_cbu,
  amount as trx_amount,
  date as trx_date,
  trx_id as trx_id,
  status as trx_status,
  customers_balance.id as customer_balance_id,
  balance_amount as customer_balance_amount,
  currency.name as currency_name
FROM trx
LEFT JOIN clients ON trx.client_id = clients.id
LEFT JOIN customers_balance on trx.account_id = customers_balance.id
LEFT JOIN currency ON balance_currency_id = currency.id
WHERE trx.status = 'pendiente';
"""

def run() -> None:
    db = SessionLocal()
    try:
        rows = db.execute(text(SQL)).fetchall()
        print(datetime.now())
        for row in rows:
            print(row)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

if __name__ == "__main__":
    run()