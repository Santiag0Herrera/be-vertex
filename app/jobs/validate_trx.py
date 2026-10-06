# app/jobs/validate_trx.py

import asyncio
import datetime
import hashlib
import logging
import re
from collections import Counter, defaultdict
from contextlib import contextmanager
from decimal import Decimal

from dotenv import load_dotenv
from dateutil.relativedelta import relativedelta
from fastapi import HTTPException
from sqlalchemy import bindparam, text

from app.db.database import SessionLocal
from app.models import TransactionDocument, Trx
from app.services.BusinessCalendarService import BusinessCalendarService
from app.services.InterBankingService import InterBankingService
from app.bank_codes import codes

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger("validate_trx_job")

RECONCILIATION_ADVISORY_LOCK_ID = 0x564552544558

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
WHERE trx.status = 'pendiente'
  AND (:entity_id IS NULL OR trx.entity_id = :entity_id)
ORDER BY trx.creation_date ASC, trx.id ASC;
"""


STRONG_MOVEMENT_IDENTIFIER_FIELDS = (
    "voucher_number",
    "correlative_number",
)
EMPTY_MOVEMENT_IDENTIFIER_VALUES = {
    "",
    "-",
    "N/A",
    "NA",
    "NONE",
    "NULL",
    "S/D",
    "SIN DATOS",
}


def normalize_account(value):
    """Keep the legacy normalization used by persisted bank fingerprints."""
    return str(value or "").replace(" ", "").replace("-", "").strip()


def normalize_account_identifier(value):
    """Normalize identifiers used only for account lookup and comparison."""
    return re.sub(r"[^0-9A-Z]", "", str(value or "").strip().upper())


def account_identifier_aliases(value):
    """Return safe aliases for a CBU/account number.

    Interbanking has returned the same account both formatted and without its
    leading zero.  The zero-less alias is only used through the ambiguity-aware
    account index, so collisions remain blocked instead of picking an account.
    """
    normalized = normalize_account_identifier(value)
    if not normalized:
        return set()

    aliases = {normalized}
    if normalized.isdigit():
        aliases.add(normalized.lstrip("0") or "0")
    return aliases


def normalize_fingerprint_value(value):
    return str(value or "").strip().upper()


def account_identifiers(account):
    cbu = account.get("cbu")
    if isinstance(cbu, dict):
        cbu = cbu.get("nro") or cbu.get("number")

    identifiers = set()
    for value in (account.get("account_cbu"), cbu, account.get("account_number")):
        identifiers.update(account_identifier_aliases(value))
    return identifiers


def get_bank_name_from_cbu(cbu: str) -> str:
    bank_code = cbu[:3]
    return codes.get(bank_code, "Banco desconocido")


def get_pending_trx(entity_id=None):
    db = SessionLocal()

    try:
        return db.execute(text(SQL), {"entity_id": entity_id}).mappings().all()
    except Exception:
        logger.exception("[ERROR] failed_to_fetch_pending_transactions")
        raise
    finally:
        db.close()


def get_entity_account_identifiers(entity_id):
    if entity_id is None:
        return None

    db = SessionLocal()
    try:
        rows = db.execute(
            text(
                """
                SELECT cbus.nro
                FROM cbus
                INNER JOIN entities_cbus ON entities_cbus.cbu_id = cbus.id
                WHERE entities_cbus.entity_id = :entity_id
                """
            ),
            {"entity_id": entity_id},
        ).all()
        identifiers = set()
        for row in rows:
            identifiers.update(account_identifier_aliases(row[0]))
        return identifiers
    finally:
        db.close()


def filter_reconciliation_accounts(accounts, owned_account_identifiers=None):
    filtered_accounts = []
    for account in accounts:
        if not isinstance(account, dict):
            continue
        if not account.get("account_number") or not account.get("bank_number"):
            logger.warning(
                "[ACCOUNT SKIPPED] reason=missing_required_identifier keys=%s",
                sorted(account.keys()),
            )
            continue
        identifiers = account_identifier_aliases(account.get("account_number"))
        if owned_account_identifiers is not None and not (
            identifiers & owned_account_identifiers
        ):
            continue
        filtered_accounts.append(account)
    return filtered_accounts


def build_account_index(accounts):
    account_index = {}
    ambiguous_identifiers = set()
    for account in accounts:
        identity = (
            normalize_account_identifier(account.get("bank_number")),
            normalize_account_identifier(account.get("account_number")),
        )
        for identifier in account_identifiers(account):
            existing = account_index.get(identifier)
            if existing is not None:
                existing_identity = (
                    normalize_account_identifier(existing.get("bank_number")),
                    normalize_account_identifier(existing.get("account_number")),
                )
                if existing_identity != identity:
                    ambiguous_identifiers.add(identifier)
                    account_index.pop(identifier, None)
                    continue
            if identifier not in ambiguous_identifiers:
                account_index[identifier] = account
    return account_index, ambiguous_identifiers


def resolve_reconciliation_account(
    receptor,
    account_index,
    ambiguous_account_identifiers,
):
    """Resolve one destination without guessing across ambiguous accounts."""
    aliases = account_identifier_aliases(receptor)
    matches = {
        (
            normalize_account_identifier(account.get("bank_number")),
            normalize_account_identifier(account.get("account_number")),
        ): account
        for alias in aliases
        if (account := account_index.get(alias)) is not None
    }
    if len(matches) == 1:
        return next(iter(matches.values())), None
    if len(matches) > 1 or aliases & ambiguous_account_identifiers:
        return None, "ambiguous_destination_account"
    return None, "destination_account_not_available"


def get_used_fingerprints(entity_id=None):
    db = SessionLocal()
    try:
        rows = db.execute(
            text(
                """
                SELECT document_fingerprint, trx_id, status
                FROM trx
                WHERE document_fingerprint IS NOT NULL
                  AND status = 'conciliado'
                  AND (:entity_id IS NULL OR entity_id = :entity_id)
                """
            ),
            {"entity_id": entity_id},
        ).mappings()
        return {
            row["document_fingerprint"]: {
                "trx_id": row["trx_id"],
                "status": row["status"],
            }
            for row in rows
        }
    finally:
        db.close()


@contextmanager
def reconciliation_lock():
    """Serialize reconciliation across application workers when using PostgreSQL."""
    db = SessionLocal()
    is_postgresql = db.bind is not None and db.bind.dialect.name == "postgresql"
    acquired = not is_postgresql
    try:
        if is_postgresql:
            acquired = bool(
                db.execute(
                    text("SELECT pg_try_advisory_lock(:lock_id)"),
                    {"lock_id": RECONCILIATION_ADVISORY_LOCK_ID},
                ).scalar()
            )
        if not acquired:
            raise HTTPException(
                status_code=409,
                detail="The reconciliation job is already running.",
            )
        yield
    finally:
        if acquired and is_postgresql:
            try:
                db.execute(
                    text("SELECT pg_advisory_unlock(:lock_id)"),
                    {"lock_id": RECONCILIATION_ADVISORY_LOCK_ID},
                )
            except Exception:
                logger.exception("[ERROR] failed_to_release_reconciliation_lock")
        db.close()


def get_expiration_cutoff(reference_time=None):
    return (reference_time or datetime.datetime.now()) - relativedelta(months=1)


def expire_old_pending_trx(trx_ids, reference_time=None):
    """Expire eligible pending transactions after one full calendar month."""
    trx_ids = list(set(trx_ids))
    if not trx_ids:
        return 0

    cutoff = get_expiration_cutoff(reference_time)
    db = SessionLocal()
    try:
        statement = text(
            """
            UPDATE trx
            SET status = 'vencida'
            WHERE status = 'pendiente'
              AND date <= :cutoff
              AND trx_id IN :trx_ids
            """
        ).bindparams(bindparam("trx_ids", expanding=True))
        result = db.execute(
            statement,
            {
                "cutoff": cutoff,
                "trx_ids": trx_ids,
            },
        )
        db.commit()
        return result.rowcount
    except Exception:
        db.rollback()
        logger.exception("[ERROR] failed_to_expire_pending_transactions")
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


def has_strong_movement_identifier(movement):
    """Return whether Interbanking supplied a reference expected to be unique."""
    for field in STRONG_MOVEMENT_IDENTIFIER_FIELDS:
        value = normalize_fingerprint_value(movement.get(field))
        if value in EMPTY_MOVEMENT_IDENTIFIER_VALUES:
            continue
        if value.isdigit() and set(value) == {"0"}:
            continue
        return True
    return False


def build_fingerprint_slot(base_fingerprint, slot_number):
    """Build a stable identity for one of several indistinguishable movements.

    Slot one keeps the legacy fingerprint so existing reconciliations remain valid.
    The total number of slots is deliberately not persisted because Interbanking may
    return a partial result on a later request.
    """
    if slot_number < 1:
        raise ValueError("slot_number must be greater than zero")
    if slot_number == 1:
        return base_fingerprint
    return f"{base_fingerprint}:{slot_number}"


def build_credit_movement_index(movements):
    movement_index = defaultdict(list)
    for movement in movements:
        try:
            movement_type = movement.get("debit_credit_type")
            if movement_type != "C":
                continue
            key = (
                abs(normalize_amount(movement.get("amount"))),
                datetime.datetime.fromisoformat(
                    str(movement.get("movement_date")).replace("Z", "+00:00")
                ).date(),
            )
            movement_index[key].append(movement)
        except (AttributeError, TypeError, ValueError, ArithmeticError):
            logger.warning(
                "[IB MOVEMENT SKIPPED] reason=invalid_structure keys=%s",
                sorted(movement.keys()) if isinstance(movement, dict) else [],
            )
    return movement_index


def select_credit_movements(movement_index, amount, valid_dates):
    normalized_amount = abs(normalize_amount(amount))
    return [
        movement
        for movement_date in sorted(valid_dates)
        for movement in movement_index.get(
            (normalized_amount, movement_date),
            [],
        )
    ]


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
                      AND status = 'conciliado'
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


def match_trx_with_ib(
    trx,
    ib_movements,
    bank_number,
    account_number,
    valid_movement_dates=None,
    used_fingerprints=None,
):
    trx_amount = normalize_amount(trx["trx_amount"])
    trx_date = trx["trx_date"].date()
    valid_movement_dates = set(valid_movement_dates or [trx_date])
    duplicated_match = None
    matching_movements = []

    for mov in ib_movements:
        mov_amount = normalize_amount(mov.get("amount"))
        mov_date = datetime.datetime.fromisoformat(
            mov.get("movement_date")
        ).date()
        mov_type = mov.get("debit_credit_type")

        amount_matches = abs(trx_amount) == abs(mov_amount)
        date_matches = mov_date in valid_movement_dates
        type_matches = mov_type == "C"

        if amount_matches or date_matches:
            logger.debug(
                "[IB CANDIDATE] trx_amount=%s mov_amount=%s amount_match=%s valid_dates=%s mov_date=%s date_match=%s type=%s",
                trx_amount,
                mov_amount,
                amount_matches,
                sorted(valid_movement_dates),
                mov_date,
                date_matches,
                mov_type,
            )

        if amount_matches and date_matches and type_matches:
            base_fingerprint = build_interbanking_fingerprint(
                mov,
                bank_number=bank_number,
                account_number=account_number,
            )
            matching_movements.append(
                {
                    "movement": mov,
                    "base_fingerprint": base_fingerprint,
                    "has_strong_identifier": has_strong_movement_identifier(mov),
                }
            )

    ambiguous_totals = Counter(
        candidate["base_fingerprint"]
        for candidate in matching_movements
        if not candidate["has_strong_identifier"]
    )
    ambiguous_occurrences = defaultdict(int)
    seen_strong_fingerprints = set()

    for candidate in matching_movements:
        mov = candidate["movement"]
        base_fingerprint = candidate["base_fingerprint"]

        if candidate["has_strong_identifier"]:
            # Identical rows carrying the same bank reference are the same
            # movement repeated in the API response, not additional capacity.
            if base_fingerprint in seen_strong_fingerprints:
                continue
            seen_strong_fingerprints.add(base_fingerprint)
            slot_number = 1
            total_slots = 1
        else:
            ambiguous_occurrences[base_fingerprint] += 1
            slot_number = ambiguous_occurrences[base_fingerprint]
            total_slots = ambiguous_totals[base_fingerprint]

        document_fingerprint = build_fingerprint_slot(
            base_fingerprint,
            slot_number,
        )
        if used_fingerprints is None:
            duplicated_trx = find_trx_by_fingerprint(
                document_fingerprint=document_fingerprint,
                current_trx_id=trx["trx_id"],
            )
        else:
            duplicated_trx = used_fingerprints.get(document_fingerprint)
        matched_result = {
            "movement": mov,
            "document_fingerprint": document_fingerprint,
            "duplicated_trx": duplicated_trx,
            "fingerprint_slot": slot_number,
            "fingerprint_total_slots": total_slots,
        }

        if duplicated_trx:
            logger.info(
                "[IB MATCH USED] trx_id=%s duplicate_of=%s fingerprint=%s slot=%s/%s voucher_number=%s customer_cuit=%s",
                trx["trx_id"],
                duplicated_trx.get("trx_id"),
                document_fingerprint,
                slot_number,
                total_slots,
                mov.get("voucher_number"),
                mov.get("customer_cuit"),
            )
            # Keep the last occupied slot so an exhausted group is reported as
            # N/N instead of looking like it failed at its first occurrence.
            duplicated_match = matched_result
            continue

        logger.info(
            "[IB MATCH AVAILABLE] trx_id=%s fingerprint=%s slot=%s/%s",
            trx["trx_id"],
            document_fingerprint,
            slot_number,
            total_slots,
        )
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
    customer_amount = normalize_amount(trx_amount) - fee_amount
    try:
        result = db.execute(
        text("""
          UPDATE trx
          SET 
              status = :status,
              document_fingerprint = :document_fingerprint,
              applied_fee_percentage = :applied_fee_percentage,
              fee_amount = :fee_amount,
              reconciled_at = CASE
                  WHEN :status = 'conciliado'
                  THEN COALESCE(reconciled_at, CURRENT_TIMESTAMP)
                  ELSE reconciled_at
              END
          WHERE trx_id = :trx_id
            AND status = 'pendiente'
        """),
        {
            "status": new_status,
            "trx_id": trx_id,
            "document_fingerprint": document_fingerprint,
            "applied_fee_percentage": fee_percentage or 0,
            "fee_amount": float(fee_amount),
        },
        )

        if result.rowcount == 0:
            db.rollback()
            logger.warning(
                "[WARNING] trx_not_updated trx_id=%s reason=not_found_or_not_pending",
                trx_id,
            )
            return False

        if new_status == "conciliado":
            reconciled_transaction = (
                db.query(Trx).filter(Trx.trx_id == trx_id).one()
            )
            delete_after = reconciled_transaction.reconciled_at + relativedelta(
                months=2
            )
            (
                db.query(TransactionDocument)
                .filter(
                    TransactionDocument.trx_id == reconciled_transaction.id,
                    TransactionDocument.status == "active",
                    TransactionDocument.delete_after.is_(None),
                )
                .update(
                    {
                        TransactionDocument.delete_after: delete_after,
                        TransactionDocument.updated_at: datetime.datetime.now(
                            datetime.timezone.utc
                        ),
                    },
                    synchronize_session=False,
                )
            )

        balance_result = db.execute(
            text("""
                UPDATE customers_balance
                SET
                    balance_amount = balance_amount + :customer_amount,
                    fee_amount = fee_amount + :fee_amount,
                    last_update = CURRENT_TIMESTAMP
                WHERE id = :id
                  AND enabled = TRUE
            """),
            {
                "customer_amount": float(customer_amount),
                "fee_amount": float(fee_amount),
                "id": customer_balance_id,
            },
        )

        if balance_result.rowcount == 0:
            raise RuntimeError(
                f"Active customer balance {customer_balance_id} was not found"
            )

        db.commit()

        logger.info(
            "[BALANCE UPDATED] trx_id=%s balance_id=%s gross_amount=%s customer_amount=%s fee_amount=%s",
            trx_id,
            customer_balance_id,
            trx_amount,
            customer_amount,
            fee_amount,
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


def build_job_result(
    started_at,
    total_pending,
    checked=0,
    conciliated=0,
    repeated=0,
    expired=0,
    skipped=0,
    skipped_by_reason=None,
    movement_requests=0,
    movement_cache_hits=0,
):
    duration = (datetime.datetime.now() - started_at).total_seconds()
    return {
        "checked": checked,
        "conciliated": conciliated,
        "repeated": repeated,
        "expired": expired,
        "skipped": skipped,
        "skipped_by_reason": dict(skipped_by_reason or {}),
        "still_pending": max(
            0,
            total_pending - conciliated - repeated - expired,
        ),
        "movement_requests": movement_requests,
        "movement_cache_hits": movement_cache_hits,
        "duration_seconds": round(duration, 2),
    }


def log_job_result(result, outcome="completed"):
    logger.info(
        "[JOB END] validate_trx checked=%s conciliated=%s repeated=%s expired=%s skipped=%s still_pending=%s movement_requests=%s movement_cache_hits=%s duration_seconds=%.2f",
        result["checked"],
        result["conciliated"],
        result["repeated"],
        result["expired"],
        result["skipped"],
        result["still_pending"],
        result["movement_requests"],
        result["movement_cache_hits"],
        result["duration_seconds"],
        extra={
            "event": "reconciliation_completed",
            "outcome": outcome,
            "checked": result["checked"],
            "conciliated": result["conciliated"],
            "repeated": result["repeated"],
            "expired": result["expired"],
            "skipped": result["skipped"],
            "skipped_by_reason": result["skipped_by_reason"],
            "still_pending": result["still_pending"],
            "movement_requests": result["movement_requests"],
            "movement_cache_hits": result["movement_cache_hits"],
            "duration_seconds": result["duration_seconds"],
        },
    )


async def _run_reconciliation(entity_id=None) -> dict:
    started_at = datetime.datetime.now()
    current_time = started_at.strftime("%Y-%m-%d %H:%M:%S")

    logger.info("")
    logger.info("======================================================================")
    logger.info("VALIDATE TRX JOB | %s", current_time)
    logger.info("======================================================================")

    pending_transactions = get_pending_trx(entity_id=entity_id)
    total_pending = len(pending_transactions)

    logger.info(
        "[JOB INFO] entity_id=%s pending_transactions=%s",
        entity_id,
        total_pending,
    )

    if not pending_transactions:
        result = build_job_result(started_at, total_pending=0)
        log_job_result(result, outcome="no_pending_transactions")
        return result

    expiration_cutoff = get_expiration_cutoff(started_at)
    expired_trx_ids = {
        trx["trx_id"]
        for trx in pending_transactions
        if trx["trx_date"] <= expiration_cutoff
    }
    expired_trx_count = expire_old_pending_trx(
        expired_trx_ids,
        reference_time=started_at,
    )
    pending_transactions = [
        trx
        for trx in pending_transactions
        if trx["trx_id"] not in expired_trx_ids
    ]

    logger.info(
        "[EXPIRATION] expired=%s active_pending=%s external_requests_avoided=%s",
        expired_trx_count,
        len(pending_transactions),
        len(expired_trx_ids),
    )

    if not pending_transactions:
        result = build_job_result(
            started_at,
            total_pending=total_pending,
            expired=expired_trx_count,
        )
        log_job_result(result, outcome="all_pending_transactions_expired")
        return result

    ib_service = InterBankingService()
    business_calendar = BusinessCalendarService()

    try:
        accounts = await ib_service.get_reconciliation_accounts()
    except Exception:
        logger.exception("[ERROR] failed_to_fetch_interbanking_accounts")
        raise

    owned_account_identifiers = get_entity_account_identifiers(entity_id)
    accounts = filter_reconciliation_accounts(
        accounts,
        owned_account_identifiers=owned_account_identifiers,
    )
    if not accounts:
        raise HTTPException(
            status_code=422,
            detail="No Interbanking account is configured for this entity.",
        )

    account_index, ambiguous_account_identifiers = build_account_index(accounts)
    # Fingerprints identify external bank movements, so occupancy must remain
    # global even though pending receipts and accounts are entity-scoped.
    used_fingerprints = get_used_fingerprints()

    updated_trx_count = 0
    repeated_trx_count = 0
    checked_trx_count = 0
    skipped_trx_count = 0
    skipped_by_reason = Counter()
    reconciliation_groups = defaultdict(list)
    settlement_dates = {}

    for trx in pending_transactions:
        trx_id = trx["trx_id"]
        receptor = trx.get("trx_receptor_cbu")
        account, account_error = resolve_reconciliation_account(
            receptor,
            account_index,
            ambiguous_account_identifiers,
        )
        if account is None:
            skipped_trx_count += 1
            skipped_by_reason[account_error] += 1
            logger.warning(
                "[TRX SKIPPED] trx_id=%s reason=%s receptor=%s",
                trx_id,
                account_error,
                normalize_account_identifier(receptor),
                extra={
                    "event": "reconciliation_transaction_skipped",
                    "trx_id": trx_id,
                    "reason": account_error,
                    "receptor": normalize_account_identifier(receptor),
                },
            )
            continue

        trx_date = trx["trx_date"].date()
        try:
            if trx_date not in settlement_dates:
                settlement_dates[trx_date] = (
                    await business_calendar.get_settlement_date(trx_date)
                )
            settlement_date = settlement_dates[trx_date]
        except Exception:
            skipped_trx_count += 1
            skipped_by_reason["settlement_date_failed"] += 1
            logger.exception(
                "[TRX SKIPPED] trx_id=%s reason=settlement_date_failed",
                trx_id,
            )
            continue

        date_since = trx_date.isoformat()
        date_until = (settlement_date + datetime.timedelta(days=1)).isoformat()
        group_key = (
            normalize_account(account.get("bank_number")),
            normalize_account(account.get("account_number")),
            date_since,
            date_until,
        )
        reconciliation_groups[group_key].append(
            {
                "trx": trx,
                "account": account,
                "valid_movement_dates": {trx_date, settlement_date},
            }
        )

    movement_requests = 0
    movement_cache_hits = sum(
        max(0, len(entries) - 1)
        for entries in reconciliation_groups.values()
    )

    logger.info(
        "[BATCHING] groups=%s pending_grouped=%s movement_requests_avoided=%s",
        len(reconciliation_groups),
        sum(len(entries) for entries in reconciliation_groups.values()),
        movement_cache_hits,
    )

    for group_key, entries in reconciliation_groups.items():
        bank_number, account_number, date_since, date_until = group_key
        checked_trx_count += len(entries)
        movement_requests += 1

        try:
            ib_movements_result = await ib_service.get_movement(
                account_number=account_number,
                bank_number=bank_number,
                date_since=date_since,
                date_until=date_until,
            )
            movements = ib_movements_result["movements_detail"]
            if len(movements) >= ib_service.MOVEMENT_RESULT_LIMIT:
                raise RuntimeError(
                    "Interbanking movement result reached its safety limit; "
                    "the batch will remain pending to avoid reconciling truncated data"
                )
            movement_index = build_credit_movement_index(movements)
        except Exception:
            skipped_trx_count += len(entries)
            skipped_by_reason["movement_request_failed"] += len(entries)
            logger.exception(
                "[BATCH FAILED] account_number=%s bank_number=%s range_start=%s range_end=%s affected_transactions=%s",
                account_number,
                bank_number,
                date_since,
                date_until,
                len(entries),
            )
            continue

        logger.info(
            "[IB FETCH] account_number=%s bank_number=%s movements=%s range_start=%s range_end=%s reused_by=%s",
            account_number,
            bank_number,
            len(movements),
            date_since,
            date_until,
            len(entries),
        )

        for entry in entries:
            trx = entry["trx"]
            trx_id = trx["trx_id"]
            trx_date = trx["trx_date"].date()
            trx_amount = trx["trx_amount"]

            try:
                candidate_movements = select_credit_movements(
                    movement_index,
                    trx_amount,
                    entry["valid_movement_dates"],
                )
                matched_result = match_trx_with_ib(
                    trx,
                    candidate_movements,
                    bank_number=bank_number,
                    account_number=account_number,
                    valid_movement_dates=entry["valid_movement_dates"],
                    used_fingerprints=used_fingerprints,
                )

                if not matched_result:
                    logger.info(
                        "[NO MATCH] trx_id=%s amount=%s date=%s",
                        trx_id,
                        trx_amount,
                        trx_date,
                    )
                    continue

                matched_movement = matched_result["movement"]
                document_fingerprint = matched_result["document_fingerprint"]
                duplicated_trx = matched_result["duplicated_trx"]
                fingerprint_slot = matched_result["fingerprint_slot"]
                fingerprint_total_slots = matched_result[
                    "fingerprint_total_slots"
                ]

                logger.info(
                    "[MATCH] trx_id=%s trx_amount=%s ib_amount=%s trx_date=%s ib_date=%s fingerprint=%s slot=%s/%s",
                    trx_id,
                    trx_amount,
                    matched_movement.get("amount"),
                    trx_date,
                    matched_movement.get("movement_date"),
                    document_fingerprint,
                    fingerprint_slot,
                    fingerprint_total_slots,
                )

                if duplicated_trx:
                    updated = mark_trx_as_repeated(
                        trx_id=trx_id,
                        document_fingerprint=document_fingerprint,
                    )
                    if updated:
                        repeated_trx_count += 1
                        logger.warning(
                            "[TRX UPDATED] trx_id=%s status=repetida duplicate_of=%s duplicate_status=%s capacity_exhausted=%s/%s",
                            trx_id,
                            duplicated_trx.get("trx_id"),
                            duplicated_trx.get("status"),
                            fingerprint_total_slots,
                            fingerprint_total_slots,
                        )
                    else:
                        skipped_trx_count += 1
                        skipped_by_reason["repeated_status_update_failed"] += 1
                    continue

                fee_percentage = trx.get("fee_percentage")
                updated = update_trx_status(
                    trx_id=trx_id,
                    new_status="conciliado",
                    customer_balance_id=trx.get("customer_balance_id"),
                    trx_amount=trx_amount,
                    fee_percentage=fee_percentage,
                    document_fingerprint=document_fingerprint,
                )

                if updated:
                    updated_trx_count += 1
                    used_fingerprints[document_fingerprint] = {
                        "trx_id": trx_id,
                        "status": "conciliado",
                    }
                    logger.info(
                        "[TRX UPDATED] trx_id=%s status=conciliado fee_percentage=%s fee_amount=%s",
                        trx_id,
                        fee_percentage or 0,
                        calculate_fee_amount(trx_amount, fee_percentage),
                    )
                else:
                    skipped_trx_count += 1
                    skipped_by_reason["conciliation_status_update_failed"] += 1

            except Exception:
                skipped_trx_count += 1
                skipped_by_reason["transaction_validation_failed"] += 1
                logger.exception(
                    "[ERROR] trx_validation_failed trx_id=%s account_number=%s",
                    trx_id,
                    account_number,
                )

    result = build_job_result(
        started_at,
        total_pending=total_pending,
        checked=checked_trx_count,
        conciliated=updated_trx_count,
        repeated=repeated_trx_count,
        expired=expired_trx_count,
        skipped=skipped_trx_count,
        skipped_by_reason=skipped_by_reason,
        movement_requests=movement_requests,
        movement_cache_hits=movement_cache_hits,
    )

    log_job_result(result)
    return result


async def run(entity_id=None) -> dict:
    with reconciliation_lock():
        return await _run_reconciliation(entity_id=entity_id)


if __name__ == "__main__":
    asyncio.run(run())
