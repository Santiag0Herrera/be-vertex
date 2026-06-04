# app/jobs/validate_trx.py

import asyncio
import datetime
import hashlib
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
  customers_balance.fee_percentage AS fee_percentage,
  currency.name AS currency_name
FROM trx
LEFT JOIN customers_balance ON trx.account_id = customers_balance.id
LEFT JOIN currency ON customers_balance.balance_currency_id = currency.id
WHERE trx.status = 'pendiente';
"""


def normalize_account(value):
    return str(value or "").replace(" ", "").replace("-", "").strip()


def normalize_fingerprint_value(value):
    return str(value or "").strip().upper()


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


def normalize_movement_date(value):
    if not value:
        return ""
    return datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00")).date().isoformat()


def build_interbanking_fingerprint(movement, bank_number, account_number):
    stable_key = "|".join(
        [
            normalize_fingerprint_value(bank_number),
            normalize_fingerprint_value(account_number),
            normalize_fingerprint_value(movement.get("voucher_number")),
            normalize_fingerprint_value(movement.get("correlative_number")),
            normalize_fingerprint_value(movement.get("operation_code_bank")),
            normalize_fingerprint_value(movement.get("operation_code_ib")),
            normalize_fingerprint_value(movement.get("branch_office_activity")),
            normalize_fingerprint_value(movement.get("debit_credit_type")),
            normalize_movement_date(movement.get("movement_date")),
            str(normalize_amount(movement.get("amount"))),
            normalize_fingerprint_value(movement.get("customer_cuit")),
            normalize_account(movement.get("account_cbu")),
        ]
    )
    return hashlib.sha256(stable_key.encode("utf-8")).hexdigest()


def find_trx_by_fingerprint(document_fingerprint, current_trx_id):
    db = SessionLocal()
    try:
        return (
            db.execute(
                text(
                    """
                    SELECT trx_id, status
                    FROM trx
                    WHERE document_fingerprint = :document_fingerprint
                      AND trx_id != :current_trx_id
                    LIMIT 1
                    """
                ),
                {
                    "document_fingerprint": document_fingerprint,
                    "current_trx_id": current_trx_id,
                },
            )
            .mappings()
            .first()
        )
    except Exception:
        logger.exception(
            "[ERROR] failed_to_find_fingerprint document_fingerprint=%s",
            document_fingerprint,
        )
        raise
    finally:
        db.close()


def match_trx_with_ib(trx, ib_movements, bank_number, account_number):
    trx_amount = normalize_amount(trx["trx_amount"])
    trx_date = trx["trx_date"].date()
    duplicated_match = None

    for mov in ib_movements:
        mov_amount = normalize_amount(mov.get("amount"))
        mov_date = datetime.datetime.fromisoformat(
            mov.get("movement_date")
        ).date()
        mov_type = mov.get("debit_credit_type")

        amount_matches = abs(trx_amount) == abs(mov_amount)
        date_matches = trx_date == mov_date
        type_matches = mov_type == "C"

        if amount_matches or date_matches:
            logger.info(
                "[IB CANDIDATE] trx_amount=%s mov_amount=%s amount_match=%s trx_date=%s mov_date=%s date_match=%s type=%s",
                trx_amount,
                mov_amount,
                amount_matches,
                trx_date,
                mov_date,
                date_matches,
                mov_type,
            )

        if amount_matches and date_matches and type_matches:
            document_fingerprint = build_interbanking_fingerprint(
                mov,
                bank_number=bank_number,
                account_number=account_number,
            )
            duplicated_trx = find_trx_by_fingerprint(
                document_fingerprint=document_fingerprint,
                current_trx_id=trx["trx_id"],
            )
            matched_result = {
                "movement": mov,
                "document_fingerprint": document_fingerprint,
                "duplicated_trx": duplicated_trx,
            }

            if duplicated_trx:
                logger.info(
                    "[IB MATCH USED] trx_id=%s duplicate_of=%s fingerprint=%s voucher_number=%s customer_cuit=%s",
                    trx["trx_id"],
                    duplicated_trx.get("trx_id"),
                    document_fingerprint,
                    mov.get("voucher_number"),
                    mov.get("customer_cuit"),
                )
                if duplicated_match is None:
                    duplicated_match = matched_result
                continue

            return matched_result

    if duplicated_match:
        return duplicated_match

    return None


def update_trx_status(
    trx_id: str,
    new_status: str,
    customer_balance_id: int,
    trx_amount,
    fee_percentage,
    document_fingerprint=None,
):
    db = SessionLocal()
    fee_amount = calculate_fee_amount(trx_amount, fee_percentage)
    try:
        result = db.execute(
        text("""
          UPDATE trx
          SET 
              status = :status,
              document_fingerprint = :document_fingerprint,
              applied_fee_percentage = :applied_fee_percentage,
              fee_amount = :fee_amount
          WHERE trx_id = :trx_id
            AND status = 'pendiente'
        """),
        {
            "status": new_status,
            "trx_id": trx_id,
            "document_fingerprint": document_fingerprint,
            "applied_fee_percentage": fee_percentage or 0,
            "fee_amount": fee_amount,
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
        logger.exception("[ERROR] failed_to_update_transaction trx_id=%s", trx_id)
        raise
    finally:
        db.close()


def mark_trx_as_repeated(trx_id: str, document_fingerprint: str):
    db = SessionLocal()
    try:
        result = db.execute(
            text(
                """
                UPDATE trx
                SET
                    status = 'repetido',
                    document_fingerprint = :document_fingerprint,
                    applied_fee_percentage = 0,
                    fee_amount = 0
                WHERE trx_id = :trx_id
                  AND status = 'pendiente'
                """
            ),
            {
                "trx_id": trx_id,
                "document_fingerprint": document_fingerprint,
            },
        )

        if result.rowcount == 0:
            db.rollback()
            logger.warning(
                "[WARNING] repeated_trx_not_updated trx_id=%s reason=not_found_or_not_pending",
                trx_id,
            )
            return False

        db.commit()
        return True

    except Exception:
        db.rollback()
        logger.exception("[ERROR] failed_to_mark_repeated trx_id=%s", trx_id)
        raise
    finally:
        db.close()


def calculate_fee_amount(amount, fee_percentage):
    amount = normalize_amount(amount)
    fee_percentage = normalize_amount(fee_percentage or 0)
    return (amount * fee_percentage / Decimal("100")).quantize(Decimal("0.01"))


async def run() -> None:
    started_at = datetime.datetime.now()
    current_time = started_at.strftime("%Y-%m-%d %H:%M:%S")

    logger.info("")
    logger.info("======================================================================")
    logger.info("VALIDATE TRX JOB | %s", current_time)
    logger.info("======================================================================")

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
        logger.info("[JOB END] no_pending_transactions_found")
        return

    updated_trx_count = 0
    repeated_trx_count = 0
    checked_trx_count = 0
    skipped_trx_count = 0

    for acc in accounts:
        account_number = acc.get("account_number")
        account_cbu = acc.get("account_cbu")
        bank_number = acc.get("bank_number")
        bank_name = acc.get("bank_name")

        normalized_account_number = normalize_account(account_number)
        normalized_account_cbu = normalize_account(account_cbu)

        account_pending_trx = [
            trx
            for trx in pending_transactions
            if normalize_account(trx.get("trx_receptor_cbu"))
            in [normalized_account_cbu, normalized_account_number]
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
            trx_receptor_cbu = trx.get("trx_receptor_cbu")
            customer_balance_id = trx.get("customer_balance_id")

            logger.info(
                "[TRX] checking trx_id=%s amount=%s currency=%s date=%s receptor=%s account_number=%s account_cbu=%s",
                trx_id,
                trx_amount,
                trx_currency,
                trx_date,
                trx_receptor_cbu,
                account_number,
                account_cbu,
            )

            trx_date_since = (trx_date - datetime.timedelta(days=1)).isoformat()
            trx_date_until = (trx_date + datetime.timedelta(days=1)).isoformat()

            try:
                # buscar movimientos en interbanking con ese rango de fecha, monto y tipo de movimiento (credito/debito)
                ib_movements_result = await ib_service.get_movement(
                    account_number=account_number,
                    bank_number=bank_number,
                    date_since=trx_date_since,
                    date_until=trx_date_until,
                )

                movements = ib_movements_result.get("movements_detail", [])

                logger.info(
                    "[IB FETCH] trx_id=%s movements=%s range_start=%s range_end=%s",
                    trx_id,
                    len(movements),
                    trx_date_since,
                    trx_date_until,
                )

                matched_result = match_trx_with_ib(
                    trx,
                    movements,
                    bank_number=bank_number,
                    account_number=account_number,
                )

                if matched_result:
                    matched_movement = matched_result["movement"]
                    document_fingerprint = matched_result["document_fingerprint"]
                    duplicated_trx = matched_result["duplicated_trx"]

                    logger.info(
                        "[MATCH] trx_id=%s trx_amount=%s ib_amount=%s trx_date=%s ib_date=%s fingerprint=%s",
                        trx_id,
                        trx_amount,
                        matched_movement.get("amount"),
                        trx_date,
                        matched_movement.get("movement_date"),
                        document_fingerprint,
                    )

                    if duplicated_trx:
                        updated = mark_trx_as_repeated(
                            trx_id=trx_id,
                            document_fingerprint=document_fingerprint,
                        )

                        if updated:
                            repeated_trx_count += 1
                            logger.warning(
                                "[TRX UPDATED] trx_id=%s status=repetida duplicate_of=%s duplicate_status=%s",
                                trx_id,
                                duplicated_trx.get("trx_id"),
                                duplicated_trx.get("status"),
                            )
                        else:
                            skipped_trx_count += 1
                            logger.warning(
                                "[WARNING] repeated_update_skipped trx_id=%s",
                                trx_id,
                            )
                        continue

                    fee_percentage = trx.get("fee_percentage")

                    updated = update_trx_status(
                        trx_id=trx_id,
                        new_status="conciliado",
                        customer_balance_id=customer_balance_id,
                        trx_amount=trx_amount,
                        fee_percentage=fee_percentage,
                        document_fingerprint=document_fingerprint,
                    )


                    if updated:
                        updated_trx_count += 1
                        logger.info(
                            "[TRX UPDATED] trx_id=%s status=conciliado",
                            trx_id,
                        )
                        logger.info(
                            "[FEE APPLIED] trx_id=%s fee_percentage=%s fee_amount=%s",
                            trx_id,
                            fee_percentage or 0,
                            calculate_fee_amount(trx_amount, fee_percentage),
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
    duration = (finished_at - started_at).total_seconds()

    logger.info(
        "[JOB END] validate_trx checked=%s conciliated=%s repeated=%s skipped=%s still_pending=%s duration_seconds=%.2f",
        checked_trx_count,
        updated_trx_count,
        repeated_trx_count,
        skipped_trx_count,
        len(pending_transactions) - updated_trx_count - repeated_trx_count,
        duration,
    )


if __name__ == "__main__":
    asyncio.run(run())
