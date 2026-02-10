# app/jobs/validate_trx.py
import asyncio
import datetime
from dotenv import load_dotenv
from sqlalchemy import text
from app.db.database import SessionLocal
from app.services.InterBankingService import InterBankingService
from app.bank_codes import codes
from app.models import Trx

load_dotenv()
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

def get_bank_name_from_cbu(cbu: str) -> str:
    bank_code = cbu[:3]
    return codes.get(bank_code, "Banco desconocido")

def get_pending_trx():
    db = SessionLocal()
    try:
        rows = db.execute(text(SQL)).mappings().all()
        if rows is not None:
          return rows
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

def match_trx_with_ib(trx, ib_movements):
    # CAMPOS A COMPARAR
    trx_amount = trx["trx_amount"]
    trx_date = trx["trx_date"].date()
    trx_emisor_cbu = trx["trx_emisor_cbu"]

    for mov in ib_movements:
        mov_amount = mov.get("amount")
        mov_date = datetime.datetime.fromisoformat(mov.get("movement_date")).date()
        mov_emisor_cbu = mov.get("depositor_code", None)

        # REGLAS DE MATCHEO
        if (
            trx_amount == mov_amount and
            trx_date == mov_date and
            (not trx_emisor_cbu or trx_emisor_cbu == mov_emisor_cbu)
        ):
            return mov  # HUBO MATCH
    return None  # NO HUBO MATCH

def update_trx_status(trx_id: str, new_status: str):
    db = SessionLocal()
    try:
        db.execute(
            text("UPDATE trx SET status = :status WHERE trx_id = :trx_id"),
            {"status": new_status, "trx_id": trx_id}
        )
        db.commit()
    except Exception as e:
        db.rollback()
    finally:
        db.close()

async def run() -> None:
    ib_service = InterBankingService()
    db = SessionLocal()
    accounts_model = await ib_service.get_accounts()
    # BUSCAMOS TODAS LAS CUENTAS DEL CLIENTE
    accounts = accounts_model.get('accounts')
    # BUSCAMOS TODAS LAS TRX PENDIENTES
    pending_transactions = get_pending_trx()
    # POR CADA CUENTA, BUSCAMOS LAS TRX QUE TENGAN EL MISMO CBU QUE DICHA CUENTA
    # ( de esta manera no buscamos las trx en Interbanking, cuyos cbu del receptor no correspondan a una cuenta del cliente )
    print("")
    print(f"==================================================  {datetime.datetime.now().strftime('%d/%m/%Y %H:%M')}  ===================================================")
    print(f"{len(pending_transactions)} {'transacciones' if len(pending_transactions) > 1 else 'transacción'} en estado pendiente")
    print("")
    print("Verificando transacciones...")
    print("")
    updated_trx_count = 0
    for acc in accounts:
      print(f"   - Analizando cuenta {acc.get('account_number')} del banco {acc.get('bank_name')}")
      trx_matched_count = 0
      for trx in pending_transactions:
          account_cbu = acc.get("account_cbu")
          trx_receptor_cbu = trx.get("trx_receptor_cbu")
          # COMPARAMOS CBU
          if account_cbu == trx_receptor_cbu:
              trx_matched_count += 1
              # BUSCAMOS LA TRX PENDIENTE DE VALIDAR
              date = trx.get("trx_date").date()
              trx_id = trx.get("trx_id")
              trx_date_since = (date - datetime.timedelta(days=1)).isoformat()
              trx_date_until = (date + datetime.timedelta(days=1)).isoformat()
              ib_movements_result = await ib_service.get_movement(
                  account_number=acc.get("account_number"),
                  bank_number=acc.get("bank_number"),
                  date_since=trx_date_since,
                  date_until=trx_date_until
              )
              # POR CADA MOVIMIENTO ENCONTRADO EN EL RANGO DE FECHA, PARA ESA CUENTA, NOS FIJAMOS SI EXISTE ALGUN MATCH
              is_match = match_trx_with_ib(trx, ib_movements_result["movements_detail"])
              if is_match:
                  update_trx_status(trx_id=trx_id, new_status="conciliado")
                  print("    |")
                  print(f"    |_ Trx {trx_id} pendiente --> conciliado")
                  updated_trx_count += 1
              else:
                  print("    |")
                  print(f"    |_ Trx {trx_id} continua pendiente")
      
      if trx_matched_count == 0:
        print("    |")
        print(f"    |_ No existen trx pendientes para la cuenta {acc.get('account_number')} del banco {acc.get('bank_name')}")
      print("")
      
    print(f"Se conciliaron {updated_trx_count} de {len(pending_transactions)} transacciones pendientes")
    print("========================================================================================================================")
    print("")

if __name__ == "__main__":
    asyncio.run(run())