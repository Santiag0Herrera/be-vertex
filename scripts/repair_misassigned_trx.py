"""Repair receipts reconciled before sender-CUIT matching existed.

Before the fix, a receipt could take any bank movement with the same amount and
date, so some receipts were reconciled against another person's transfer and
the real owners were marked 'repetido'. For every entity (or one, with
--entity-id) and a date window (default: current month up to today) this
script:

  1. Fetches the Interbanking movements of each account, in chunks, and reads
     the sender CUIT that Banelco transfers carry in voucher_number.
  2. Classifies receipts dated in the window:
       - revertir_conciliacion: 'conciliado' holding an identified movement
         whose CUIT is not the receipt's (or the receipt has no CUIT).
       - volver_a_pendiente:   every 'repetido'; the old rule was unreliable
         and the fixed job decides again.
       - revisar:              'conciliado' holding an unidentified movement
         while a movement with its own CUIT exists (report only, untouched).
  3. Simulates the fixed reconciliation over the corrected state and reports
     the expected outcome and the balance impact per client.

Default mode only reads (Interbanking + SELECTs) and prints a report, plus a
CSV with every affected receipt. With --apply it asks for confirmation, writes
a JSON backup, reverts in one transaction holding the reconciliation lock and
then runs the reconciliation of each affected entity.

Meant to run in the production server console, where the env is already set:

    python -m scripts.repair_misassigned_trx                    # simulation
    python -m scripts.repair_misassigned_trx --apply            # apply
    python -m scripts.repair_misassigned_trx --since 2026-11-01 --until 2026-11-17
"""

import argparse
import asyncio
import csv
import datetime
import json
import os
import sys
from collections import Counter, defaultdict
from decimal import Decimal

from dotenv import load_dotenv

FETCH_EXTRA_DAYS = 7
FETCH_CHUNK_DAYS = 4


def parse_args():
    today = datetime.date.today()
    parser = argparse.ArgumentParser()
    parser.add_argument("--entity-id", type=int, help="limit to one entity (default: all)")
    parser.add_argument("--since", default=today.replace(day=1).isoformat(), help="first receipt date, YYYY-MM-DD (default: first day of this month)")
    parser.add_argument("--until", default=today.isoformat(), help="last receipt date, inclusive (default: today)")
    parser.add_argument("--env-file", help="env file to load (default: .env, then dev.env); never overrides variables already set")
    parser.add_argument("--apply", action="store_true", help="revert and re-run reconciliation")
    parser.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    return parser.parse_args()


TRX_SELECT = """
SELECT t.id, t.trx_id, t.entity_id, t.date, t.creation_date, t.amount, t.status,
       t.emisor_name, t.emisor_cuit, t.receptor_cbu, t.document_fingerprint,
       t.fee_amount, t.account_id,
       cb.fee_percentage AS account_fee_percentage,
       cb.balance_amount AS account_balance_amount,
       TRIM(COALESCE(c.first_name, '') || ' ' || COALESCE(c.last_name, '')) AS client_name
FROM trx t
JOIN customers_balance cb ON cb.id = t.account_id
LEFT JOIN clients c ON c.id = cb.client_id
"""


def money(value):
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


def movement_key(movement):
    return json.dumps(movement, sort_keys=True, default=str)


async def fetch_credits(ib, bank_number, account_number, since, until):
    """Fetch credits for [since, until] in chunks that stay under the API limit.

    Chunks overlap by one day because it is not documented whether date-until
    is inclusive. Identical rows seen in several chunks are merged by keeping
    the highest count any single response had, so overlaps never add capacity
    while genuinely repeated movements inside one response are preserved.
    """
    best_counts = Counter()
    first_seen = {}
    pending = []
    cursor = since
    while cursor <= until:
        chunk_end = min(cursor + datetime.timedelta(days=FETCH_CHUNK_DAYS - 1), until)
        pending.append((cursor, chunk_end))
        cursor = chunk_end + datetime.timedelta(days=1)

    while pending:
        start, end = pending.pop(0)
        result = await ib.get_movement(
            account_number=account_number,
            bank_number=bank_number,
            date_since=start.isoformat(),
            date_until=(end + datetime.timedelta(days=1)).isoformat(),
        )
        movements = result["movements_detail"]
        if len(movements) >= ib.MOVEMENT_RESULT_LIMIT and start == end:
            # The padded request also covers the next day. Ask for the day
            # alone, which only works if date-until is inclusive: an empty
            # answer means it is exclusive and the day cannot be split further.
            result = await ib.get_movement(
                account_number=account_number,
                bank_number=bank_number,
                date_since=start.isoformat(),
                date_until=start.isoformat(),
            )
            movements = result["movements_detail"]
            if not movements or len(movements) >= ib.MOVEMENT_RESULT_LIMIT:
                raise RuntimeError(
                    f"{bank_number}/{account_number}: Interbanking devuelve {ib.MOVEMENT_RESULT_LIMIT}+ "
                    f"movimientos para {start} (con el día siguiente) y {len(movements)} para el día solo"
                )
        if len(movements) >= ib.MOVEMENT_RESULT_LIMIT:
            middle = start + (end - start) // 2
            pending[:0] = [(start, middle), (middle + datetime.timedelta(days=1), end)]
            continue
        counts = Counter()
        for movement in movements:
            if movement.get("debit_credit_type") != "C":
                continue
            key = movement_key(movement)
            counts[key] += 1
            first_seen.setdefault(key, movement)
        for key, count in counts.items():
            best_counts[key] = max(best_counts[key], count)

    credits = []
    for key, count in best_counts.items():
        credits.extend(dict(first_seen[key]) for _ in range(count))
    credits.sort(key=lambda m: (str(m.get("movement_date")), str(m.get("correlative_number")), str(m.get("voucher_number"))))
    return credits


def slot_movements(vt, credits, bank_number, account_number):
    """Fingerprint every credit exactly like match_trx_with_ib does."""
    occurrences = defaultdict(int)
    seen_strong = set()
    by_fingerprint = {}
    for movement in credits:
        base = vt.build_interbanking_fingerprint(
            movement, bank_number=bank_number, account_number=account_number
        )
        if vt.has_strong_movement_identifier(movement):
            if base in seen_strong:
                continue
            seen_strong.add(base)
            fingerprint = base
        else:
            occurrences[base] += 1
            fingerprint = vt.build_fingerprint_slot(base, occurrences[base])
        by_fingerprint[fingerprint] = {
            "movement": movement,
            "sender_cuit": vt.movement_sender_cuit(movement),
        }
    return by_fingerprint


async def main():
    args = parse_args()
    for env_file in [args.env_file] if args.env_file else [".env", "dev.env"]:
        load_dotenv(dotenv_path=env_file)
    if not os.getenv("DATABASE_URL"):
        raise SystemExit(
            "Falta DATABASE_URL: corré el script desde la carpeta del backend "
            "o pasá el archivo de variables con --env-file."
        )

    # Imported after loading the env: the DB engine reads DATABASE_URL at import.
    from sqlalchemy import text

    from app.db.database import SessionLocal
    from app.jobs import validate_trx as vt
    from app.services.BusinessCalendarService import BusinessCalendarService
    from app.services.InterBankingService import InterBankingService

    since = datetime.date.fromisoformat(args.since)
    until = datetime.date.fromisoformat(args.until)
    until_exclusive = until + datetime.timedelta(days=1)
    fetch_until = min(
        until + datetime.timedelta(days=FETCH_EXTRA_DAYS),
        datetime.date.today(),
    )
    expiration_cutoff = vt.get_expiration_cutoff(datetime.datetime.now())
    if datetime.datetime.combine(since, datetime.time()) <= expiration_cutoff:
        raise SystemExit(
            f"--since {since} es anterior al vencimiento de pendientes ({expiration_cutoff:%Y-%m-%d}). "
            "Las trx reabiertas se vencerían en vez de conciliarse; usá un rango más reciente."
        )

    # --- Entities and their Interbanking accounts ---------------------------
    db = SessionLocal()
    try:
        if args.entity_id is not None:
            entity_ids = [args.entity_id]
        else:
            entity_ids = [
                row[0]
                for row in db.execute(
                    text("SELECT DISTINCT entity_id FROM entities_cbus ORDER BY entity_id")
                ).all()
            ]
    finally:
        db.close()

    ib = InterBankingService()
    all_accounts = await ib.get_reconciliation_accounts()

    entity_indexes = {}
    accounts_to_fetch = {}
    for entity_id in entity_ids:
        accounts = vt.filter_reconciliation_accounts(
            all_accounts,
            owned_account_identifiers=vt.get_entity_account_identifiers(entity_id),
        )
        if not accounts:
            print(f"Entidad {entity_id}: sin cuentas de Interbanking, se omite.")
            continue
        entity_indexes[entity_id] = vt.build_account_index(accounts)
        for account in accounts:
            key = (
                vt.normalize_account(account.get("bank_number")),
                vt.normalize_account(account.get("account_number")),
            )
            accounts_to_fetch[key] = account

    movements_by_fingerprint = {}
    movement_index_by_account = {}
    failed_accounts = set()
    for bank_number, account_number in sorted(accounts_to_fetch):
        try:
            credits = await fetch_credits(ib, bank_number, account_number, since, fetch_until)
        except Exception as exc:
            failed_accounts.add((bank_number, account_number))
            print(f"Cuenta {bank_number}/{account_number}: ERROR al traer movimientos ({exc}). Sus trx no se tocan.")
            continue
        movements_by_fingerprint.update(slot_movements(vt, credits, bank_number, account_number))
        movement_index_by_account[(bank_number, account_number)] = vt.build_credit_movement_index(credits)
        print(f"Cuenta {bank_number}/{account_number}: {len(credits)} créditos {since}..{fetch_until}")

    # --- Database state ---------------------------------------------------
    db = SessionLocal()
    try:
        window_rows = db.execute(
            text(
                TRX_SELECT
                + """
                WHERE t.entity_id = ANY(:entity_ids)
                  AND t.date >= :since AND t.date < :until
                  AND t.status IN ('conciliado', 'repetido', 'pendiente')
                ORDER BY t.creation_date ASC, t.id ASC
                """
            ),
            {"entity_ids": list(entity_indexes), "since": since, "until": until_exclusive},
        ).mappings().all()
        used = {
            row["document_fingerprint"]: {"trx_id": row["trx_id"], "status": "conciliado"}
            for row in db.execute(
                text(
                    "SELECT document_fingerprint, trx_id FROM trx "
                    "WHERE status = 'conciliado' AND document_fingerprint IS NOT NULL"
                )
            ).mappings()
        }
    finally:
        db.close()

    trx_list = [dict(row) for row in window_rows]
    for trx in trx_list:
        trx.update(
            cuit=vt.normalize_cuit(trx["emisor_cuit"]),
            action="sin_cambios",
            movement_sender_cuit=None,
            expected=None,
            account_key=None,
        )
        index, ambiguous = entity_indexes[trx["entity_id"]]
        account, _ = vt.resolve_reconciliation_account(trx["receptor_cbu"], index, ambiguous)
        if account is not None:
            trx["account_key"] = (
                vt.normalize_account(account.get("bank_number")),
                vt.normalize_account(account.get("account_number")),
            )

    # --- Classification ---------------------------------------------------
    identified_amounts = defaultdict(set)
    for info in movements_by_fingerprint.values():
        if info["sender_cuit"]:
            identified_amounts[info["sender_cuit"]].add(money(info["movement"].get("amount")))

    for trx in trx_list:
        if trx["account_key"] is None or trx["account_key"] in failed_accounts:
            continue
        if trx["status"] == "repetido":
            trx["action"] = "volver_a_pendiente"
            continue
        if trx["status"] != "conciliado":
            continue
        info = movements_by_fingerprint.get(trx["document_fingerprint"])
        if info is None:
            continue
        trx["movement_sender_cuit"] = info["sender_cuit"]
        if info["sender_cuit"] and info["sender_cuit"] != trx["cuit"]:
            trx["action"] = "revertir_conciliacion"
        elif not info["sender_cuit"] and money(trx["amount"]) in identified_amounts.get(trx["cuit"], ()):
            trx["action"] = "revisar"

    reverted = [t for t in trx_list if t["action"] == "revertir_conciliacion"]
    reopened = [t for t in trx_list if t["action"] == "volver_a_pendiente"]

    # Coverage per account, so an empty report can be told apart from missing data.
    print()
    print("Cobertura por cuenta (trx en la ventana):")
    coverage = defaultdict(Counter)
    for trx in trx_list:
        key = trx["account_key"]
        label = "sin cuenta" if key is None else f"{key[0]}/{key[1]}" + (" (SIN MOVIMIENTOS)" if key in failed_accounts else "")
        coverage[label][trx["status"]] += 1
        if trx["status"] == "conciliado" and key is not None and key not in failed_accounts:
            found = trx["document_fingerprint"] in movements_by_fingerprint
            coverage[label]["conciliado_con_movimiento" if found else "conciliado_sin_movimiento_en_rango"] += 1
    for label, counts in sorted(coverage.items()):
        print(f"  {label}: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))

    # --- Simulation of the fixed job --------------------------------------
    for trx in reverted:
        used.pop(trx["document_fingerprint"], None)

    calendar = BusinessCalendarService()
    settlement_cache = {}
    pending_ctx = []
    for trx in trx_list:
        reopens = trx["status"] == "pendiente" or trx["action"] in ("revertir_conciliacion", "volver_a_pendiente")
        if not reopens or trx["account_key"] is None or trx["account_key"] in failed_accounts:
            continue
        trx_date = trx["date"].date()
        if trx_date not in settlement_cache:
            settlement_cache[trx_date] = await calendar.get_settlement_date(trx_date)
        pending_ctx.append((trx, {trx_date, settlement_cache[trx_date]}))

    resolved = set()
    for allow_unidentified in (False, True):
        for trx, valid_dates in pending_ctx:
            if trx["id"] in resolved:
                continue
            key = trx["account_key"]
            result = vt.match_trx_with_ib(
                {
                    "trx_id": trx["trx_id"],
                    "trx_amount": trx["amount"],
                    "trx_date": trx["date"],
                    "trx_emisor_cuit": trx["emisor_cuit"],
                },
                vt.select_credit_movements(movement_index_by_account[key], trx["amount"], valid_dates),
                bank_number=key[0],
                account_number=key[1],
                valid_movement_dates=valid_dates,
                used_fingerprints=used,
                allow_unidentified=allow_unidentified,
            )
            if result is None:
                if allow_unidentified:
                    trx["expected"] = "pendiente"
                continue
            resolved.add(trx["id"])
            if result["duplicated_trx"]:
                trx["expected"] = "repetido"
            else:
                trx["expected"] = f"conciliado ({result['matched_by']})"
                used[result["document_fingerprint"]] = {"trx_id": trx["trx_id"], "status": "conciliado"}

    # --- Report -----------------------------------------------------------
    balance = {}
    for trx in trx_list:
        acc = balance.setdefault(
            trx["account_id"],
            {
                "entity_id": trx["entity_id"],
                "client": trx["client_name"],
                "current": money(trx["account_balance_amount"]),
                "revert": Decimal("0"),
                "readd": Decimal("0"),
            },
        )
        if trx["action"] == "revertir_conciliacion":
            acc["revert"] += money(trx["amount"]) - money(trx["fee_amount"])
        # Only receipts this repair touches count; already-pending receipts the
        # job reconciles in the same run are what it would do anyway.
        if trx["action"] in ("revertir_conciliacion", "volver_a_pendiente") and (
            trx["expected"] or ""
        ).startswith("conciliado"):
            acc["readd"] += money(trx["amount"]) - vt.calculate_fee_amount(
                trx["amount"], trx["account_fee_percentage"]
            )

    def count(predicate, rows=trx_list):
        return sum(1 for t in rows if predicate(t))

    changed = reverted + reopened
    print()
    print(f"Ventana: {since} a {until} | entidades: {', '.join(map(str, entity_indexes)) or '-'}")
    print(f"Conciliadas con plata ajena (se revierten): {len(reverted)}")
    print(f"Repetidas que vuelven a pendiente:          {len(reopened)}")
    print(f"Conciliadas a revisar a mano (no se tocan): {count(lambda t: t['action'] == 'revisar')}")
    print()
    print("Resultado esperado de las trx corregidas:")
    for label in ("conciliado (sender_cuit)", "conciliado (amount_date)", "repetido", "pendiente"):
        print(f"  {label:26} {count(lambda t, l=label: t['expected'] == l, changed)}")
    print()
    print("Impacto en saldos:")
    for acc_id, acc in sorted(balance.items()):
        if not acc["revert"] and not acc["readd"]:
            continue
        low = acc["current"] - acc["revert"]
        final = low + acc["readd"]
        warn = "  <-- NEGATIVO" if final < 0 else ("  <-- negativo durante la corrección" if low < 0 else "")
        print(
            f"  entidad {acc['entity_id']} cuenta {acc_id} ({acc['client']}): actual {acc['current']:,} | "
            f"-{acc['revert']:,} | +{acc['readd']:,} | final {final:,} ({final - acc['current']:+,}){warn}"
        )
    print()
    print("Detalle de trx corregidas (id | entidad | fecha | monto | emisor | cuit | estado -> esperado | cuit del movimiento):")
    for trx in sorted(changed, key=lambda t: (t["entity_id"], t["date"])):
        print(
            f"  {trx['id']} | {trx['entity_id']} | {trx['date']:%Y-%m-%d %H:%M} | {money(trx['amount']):,} | "
            f"{trx['emisor_name']} | {trx['emisor_cuit']} | {trx['status']} -> {trx['expected']} | "
            f"{trx['movement_sender_cuit'] or '-'}"
        )
    for trx in sorted((t for t in trx_list if t["action"] == "revisar"), key=lambda t: t["id"]):
        print(f"  REVISAR {trx['id']} | {trx['entity_id']} | {money(trx['amount']):,} | {trx['emisor_name']} | {trx['emisor_cuit']}")

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    report_path = f"repair_report_{since}_{until}_{stamp}.csv"
    columns = [
        "id", "trx_id", "entity_id", "client_name", "date", "amount", "emisor_name", "emisor_cuit",
        "status", "action", "movement_sender_cuit", "expected", "document_fingerprint",
    ]
    with open(report_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for trx in sorted(trx_list, key=lambda t: (t["action"], t["entity_id"], t["date"])):
            if trx["action"] != "sin_cambios":
                writer.writerow(trx)
    print(f"\nCSV: {report_path}  (tiene datos personales, borralo al terminar)")

    if not args.apply:
        print("Simulación: no se escribió nada. Corré con --apply para aplicar.")
        return
    if not changed:
        print("No hay nada para corregir.")
        return
    if not args.yes:
        answer = input(
            f"\nSe van a revertir {len(reverted)} conciliaciones y reabrir {len(reopened)} repetidas, "
            "y luego se corre la conciliación de cada entidad afectada. Escribí APLICAR para continuar: "
        )
        if answer.strip() != "APLICAR":
            print("Cancelado, no se escribió nada.")
            return

    # --- Apply ------------------------------------------------------------
    backup_path = f"repair_backup_{since}_{until}_{stamp}.json"
    with open(backup_path, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "window": [str(since), str(until)],
                "reverted": reverted,
                "reopened": reopened,
                "balances_before": {str(k): str(v["current"]) for k, v in balance.items()},
            },
            fh,
            default=str,
            ensure_ascii=False,
            indent=2,
        )
    print(f"Backup: {backup_path}")

    db = SessionLocal()
    try:
        if db.bind.dialect.name == "postgresql":
            locked = db.execute(
                text("SELECT pg_try_advisory_xact_lock(:id)"),
                {"id": vt.RECONCILIATION_ADVISORY_LOCK_ID},
            ).scalar()
            if not locked:
                raise SystemExit("La conciliación está corriendo. Probá de nuevo en unos minutos.")

        now = datetime.datetime.now(datetime.timezone.utc)
        for trx in reverted:
            updated = db.execute(
                text(
                    """
                    UPDATE trx
                    SET status = 'pendiente', document_fingerprint = NULL,
                        reconciled_at = NULL, applied_fee_percentage = 0, fee_amount = 0
                    WHERE id = :id AND status = 'conciliado'
                      AND document_fingerprint = :fingerprint
                    """
                ),
                {"id": trx["id"], "fingerprint": trx["document_fingerprint"]},
            ).rowcount
            if updated != 1:
                raise RuntimeError(f"trx {trx['id']} cambió desde la simulación")
            fee = money(trx["fee_amount"])
            db.execute(
                text(
                    """
                    UPDATE customers_balance
                    SET balance_amount = balance_amount - :net,
                        fee_amount = fee_amount - :fee,
                        last_update = CURRENT_TIMESTAMP
                    WHERE id = :account_id
                    """
                ),
                {"net": float(money(trx["amount"]) - fee), "fee": float(fee), "account_id": trx["account_id"]},
            )
            db.execute(
                text(
                    """
                    UPDATE transaction_documents
                    SET delete_after = NULL, updated_at = :now
                    WHERE trx_id = :id AND status = 'active'
                    """
                ),
                {"id": trx["id"], "now": now},
            )

        for trx in reopened:
            updated = db.execute(
                text(
                    """
                    UPDATE trx SET status = 'pendiente', document_fingerprint = NULL
                    WHERE id = :id AND status = 'repetido'
                    """
                ),
                {"id": trx["id"]},
            ).rowcount
            if updated != 1:
                raise RuntimeError(f"trx {trx['id']} cambió desde la simulación")

        db.commit()
    except BaseException:
        db.rollback()
        print("Error: se hizo rollback, no se modificó nada.", file=sys.stderr)
        raise
    finally:
        db.close()

    print("Reversión aplicada.")
    for entity_id in sorted({t["entity_id"] for t in changed}):
        try:
            job_result = await vt.run(entity_id=entity_id)
            print(f"Conciliación entidad {entity_id}: {job_result}")
        except Exception as exc:
            # The reversion is committed; the scheduled job (running the fixed
            # logic) will pick the pending receipts up on its next run.
            print(f"Entidad {entity_id}: no se pudo correr la conciliación ahora ({exc}). La toma el job programado.")

    db = SessionLocal()
    try:
        final = {
            row["id"]: row["status"]
            for row in db.execute(
                text("SELECT id, status FROM trx WHERE id = ANY(:ids)"),
                {"ids": [t["id"] for t in changed]},
            ).mappings()
        }
    finally:
        db.close()

    mismatches = [
        (t["id"], (t["expected"] or "").split(" ")[0], final.get(t["id"]))
        for t in changed
        if final.get(t["id"]) != (t["expected"] or "").split(" ")[0]
    ]
    if mismatches:
        print("\nDiferencias contra la simulación (id, esperado, real):")
        for item in mismatches:
            print(f"  {item}")
    else:
        print("\nEl resultado coincide con la simulación.")


if __name__ == "__main__":
    asyncio.run(main())
