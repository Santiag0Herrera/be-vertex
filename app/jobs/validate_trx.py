# app/jobs/validate_trx.py

import asyncio
import datetime
import logging
from decimal import Decimal

from dotenv import load_dotenv
from sqlalchemy import text

from app.db.database import SessionLocal
from app.services.InterBankingService import InterBankingService
from app.bank_codes import codes

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger("validate_trx_job")

SQL = """
SELECT
  trx.trx_id AS trx_id,
  trx.emisor_cbu AS trx_emisor_cbu,
  trx.receptor_cbu AS trx_receptor_cbu,
  trx.amount AS trx_amount,
  trx.date AS trx_date,
  trx.status AS trx_status,
  customers_balance.id AS customer_balance_id,
  customers_balance.balance_amount AS customer_balance_amount,
  currency.name AS currency_name
FROM trx
LEFT JOIN customers_balance ON trx.account_id = customers_balance.id
LEFT JOIN currency ON customers_balance.balance_currency_id = currency.id
WHERE trx.status = 'pendiente';
"""


def get_bank_name_from_cbu(cbu: str) -> str:
    bank_code = cbu[:3]
    return codes.get(bank_code, "Banco desconocido")


def get_pending_trx():
    db = SessionLocal()

    try:
        return db.execute(text(SQL)).mappings().all()

    except Exception:
        logger.exception("[ERROR] failed_to_fetch_pending_transactions")
        raise

    finally:
        db.close()


def normalize_amount(value):
    return Decimal(str(value)).quantize(Decimal("0.01"))


def match_trx_with_ib(trx, ib_movements):
    trx_amount = normalize_amount(trx["trx_amount"])
    trx_date = trx["trx_date"].date()

    for mov in ib_movements:
        mov_amount = normalize_amount(mov.get("amount"))

        mov_date = datetime.datetime.fromisoformat(
            mov.get("movement_date")
        ).date()

        amount_matches = abs(trx_amount) == abs(mov_amount)
        date_matches = trx_date == mov_date

        if amount_matches and date_matches:
            return mov

    return None


def update_trx_status(
    trx_id: str,
    new_status: str,
    customer_balance_id: int,
    trx_amount,
):
    db = SessionLocal()

    try:
        result = db.execute(
            text("""
                UPDATE trx
                SET status = :status
                WHERE trx_id = :trx_id
                  AND status = 'pendiente'
            """),
            {
                "status": new_status,
                "trx_id": trx_id,
            },
        )

        if result.rowcount == 0:
            db.rollback()

            logger.warning(
                "[WARNING] trx_not_updated trx_id=%s reason=not_found_or_not_pending",
                trx_id,
            )

            return False

        db.execute(
            text("""
                UPDATE customers_balance
                SET balance_amount = balance_amount + :amount
                WHERE id = :id
            """),
            {
                "amount": trx_amount,
                "id": customer_balance_id,
            },
        )

        db.commit()

        logger.info(
            "[BALANCE UPDATED] trx_id=%s balance_id=%s amount=%s",
            trx_id,
            customer_balance_id,
            trx_amount,
        )

        return True

    except Exception:
        db.rollback()

        logger.exception(
            "[ERROR] failed_to_update_transaction trx_id=%s",
            trx_id,
        )

        raise

    finally:
        db.close()


async def run() -> None:
    started_at = datetime.datetime.now()
    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    header = f" VALIDATE TRX JOB | {current_time} "
    logger.info("=" * 120)
    logger.info(header.center(120, "="))
    logger.info("=" * 120)

    ib_service = InterBankingService()

    accounts_model = await ib_service.get_accounts()
    accounts = accounts_model.get("accounts", [])

    pending_transactions = get_pending_trx()

    logger.info(
        "[JOB INFO] ib_accounts=%s pending_transactions=%s",
        len(accounts),
        len(pending_transactions),
    )

    if not pending_transactions:
        logger.info(
            "[JOB END] no_pending_transactions_found"
        )
        return

    updated_trx_count = 0
    checked_trx_count = 0
    skipped_trx_count = 0

    for acc in accounts:
        account_number = acc.get("account_number")
        account_cbu = acc.get("account_cbu")
        bank_number = acc.get("bank_number")
        bank_name = acc.get("bank_name")

        account_pending_trx = [
            trx for trx in pending_transactions
            if trx.get("trx_receptor_cbu") == account_cbu
        ]

        logger.info(
            "[ACCOUNT] bank=%s account_number=%s cbu=%s pending_transactions=%s",
            bank_name,
            account_number,
            account_cbu,
            len(account_pending_trx),
        )

        if not account_pending_trx:
            continue

        for trx in account_pending_trx:
            checked_trx_count += 1

            trx_id = trx.get("trx_id")
            trx_date = trx.get("trx_date").date()
            trx_amount = trx.get("trx_amount")
            trx_currency = trx.get("currency_name")
            customer_balance_id = trx.get("customer_balance_id")

            logger.info(
                "[TRX] checking trx_id=%s amount=%s currency=%s date=%s",
                trx_id,
                trx_amount,
                trx_currency,
                trx_date,
            )

            trx_date_since = (
                trx_date - datetime.timedelta(days=1)
            ).isoformat()

            trx_date_until = (
                trx_date + datetime.timedelta(days=1)
            ).isoformat()

            try:
                ib_movements_result = await ib_service.get_movement(
                    account_number=account_number,
                    bank_number=bank_number,
                    date_since=trx_date_since,
                    date_until=trx_date_until,
                )

                movements = ib_movements_result.get(
                    "movements_detail",
                    [],
                )

                logger.info(
                    "[IB FETCH] trx_id=%s movements=%s range_start=%s range_end=%s",
                    trx_id,
                    len(movements),
                    trx_date_since,
                    trx_date_until,
                )

                matched_movement = match_trx_with_ib(
                    trx,
                    movements,
                )

                if matched_movement:
                    logger.info(
                        "[MATCH] trx_id=%s trx_amount=%s ib_amount=%s trx_date=%s ib_date=%s",
                        trx_id,
                        trx_amount,
                        matched_movement.get("amount"),
                        trx_date,
                        matched_movement.get("movement_date"),
                    )

                    updated = update_trx_status(
                        trx_id=trx_id,
                        new_status="conciliado",
                        customer_balance_id=customer_balance_id,
                        trx_amount=trx_amount,
                    )

                    if updated:
                        updated_trx_count += 1

                        logger.info(
                            "[TRX UPDATED] trx_id=%s status=conciliado",
                            trx_id,
                        )

                    else:
                        skipped_trx_count += 1

                        logger.warning(
                            "[WARNING] trx_update_skipped trx_id=%s",
                            trx_id,
                        )

                else:
                    logger.info(
                        "[NO MATCH] trx_id=%s amount=%s date=%s",
                        trx_id,
                        trx_amount,
                        trx_date,
                    )

            except Exception:
                skipped_trx_count += 1

                logger.exception(
                    "[ERROR] trx_validation_failed trx_id=%s account_number=%s",
                    trx_id,
                    account_number,
                )

    finished_at = datetime.datetime.now()

    duration = (
        finished_at - started_at
    ).total_seconds()

    logger.info(
        "[JOB END] validate_trx checked=%s conciliated=%s skipped=%s still_pending=%s duration_seconds=%.2f",
        checked_trx_count,
        updated_trx_count,
        skipped_trx_count,
        len(pending_transactions) - updated_trx_count,
        duration,
    )


if __name__ == "__main__":
    asyncio.run(run())