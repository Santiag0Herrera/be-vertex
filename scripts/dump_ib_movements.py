"""Dump Interbanking credit movements for one account.

Read-only diagnostic that only talks to Interbanking (no database access). It
answers whether Interbanking sends the sender's CUIT/CBU on each credit
movement, which the reconciliation needs to match receipts by sender.

Usage (from be-vertex/, with the MS_INTER_BANKING_* env vars loaded):

    python -m scripts.dump_ib_movements --receptor 0430509162 \
        --since 2026-11-13 --until 2026-11-18

If the receptor does not resolve to exactly one account, the available accounts
are printed and you can pass --bank-number and --account-number explicitly.

Output:
    ib_movements_<account>_<since>_<until>.csv   one row per credit movement,
                                                 with every field Interbanking returns
    a summary printed to stdout
"""

import argparse
import asyncio
import csv
import os
import re
from collections import Counter

from dotenv import load_dotenv

from app.services.InterBankingService import InterBankingService

EMPTY_VALUES = {"", "-", "N/A", "NA", "NONE", "NULL", "S/D", "SIN DATOS"}


def digits(value):
    return re.sub(r"\D", "", str(value or ""))


def aliases(value):
    normalized = re.sub(r"[^0-9A-Z]", "", str(value or "").strip().upper())
    if not normalized:
        return set()
    result = {normalized}
    if normalized.isdigit():
        result.add(normalized.lstrip("0") or "0")
    return result


def is_present(value):
    cleaned = str(value or "").strip().upper()
    if cleaned in EMPTY_VALUES:
        return False
    only_digits = digits(cleaned)
    return not (only_digits and set(only_digits) == {"0"})


def resolve_account(accounts, receptor):
    wanted = aliases(receptor)
    matches = {}
    for account in accounts:
        if not isinstance(account, dict):
            continue
        account_aliases = set()
        for value in account.values():
            if isinstance(value, (str, int)):
                account_aliases |= aliases(value)
        if wanted & account_aliases:
            key = (str(account.get("bank_number")), str(account.get("account_number")))
            matches[key] = account
    return list(matches.keys())


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--receptor", help="receptor_cbu as stored in trx")
    parser.add_argument("--bank-number")
    parser.add_argument("--account-number")
    parser.add_argument("--since", required=True, help="YYYY-MM-DD")
    parser.add_argument("--until", required=True, help="YYYY-MM-DD")
    parser.add_argument("--env-file", default="dev.env", help="env file with MS_INTER_BANKING_* (default: dev.env, like app/main.py)")
    args = parser.parse_args()

    # Same env file the API loads; already-exported variables take precedence.
    load_dotenv(dotenv_path=args.env_file)
    missing = [
        name
        for name in ("MS_INTER_BANKING_AUTH_URL", "MS_INTER_BANKING_API_URL", "MS_INTER_BANKING_CLIENT_ID", "MS_INTER_BANKING_CLIENT_SECRET", "MS_INTER_BANKING_CUSTOMER_ID")
        if not os.getenv(name)
    ]
    if missing:
        raise SystemExit(f"Faltan variables de Interbanking ({args.env_file}): {', '.join(missing)}")

    ib = InterBankingService()

    if args.bank_number and args.account_number:
        bank_number, account_number = args.bank_number, args.account_number
    elif args.receptor:
        accounts = await ib.get_reconciliation_accounts()
        matches = resolve_account(accounts, args.receptor)
        if len(matches) != 1:
            print(f"El receptor {args.receptor} coincide con {len(matches)} cuentas. Cuentas disponibles:")
            for account in accounts:
                if isinstance(account, dict):
                    print(f"  bank_number={account.get('bank_number')} account_number={account.get('account_number')}")
            raise SystemExit("Pasá --bank-number y --account-number explícitamente.")
        bank_number, account_number = matches[0]
    else:
        raise SystemExit("Pasá --receptor o --bank-number y --account-number.")

    result = await ib.get_movement(
        account_number=account_number,
        bank_number=bank_number,
        date_since=args.since,
        date_until=args.until,
    )
    all_movements = result["movements_detail"]
    credits = [m for m in all_movements if m.get("debit_credit_type") == "C"]

    keys = sorted({k for m in credits for k in m.keys()})
    out_path = f"ib_movements_{digits(account_number)}_{args.since}_{args.until}.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(keys)
        for mov in credits:
            writer.writerow([mov.get(k) for k in keys])

    stats = Counter()
    for mov in credits:
        has_cuit = is_present(mov.get("customer_cuit"))
        has_cbu = is_present(mov.get("account_cbu"))
        stats["cuit"] += has_cuit
        stats["cbu"] += has_cbu
        stats["cuit_or_cbu"] += has_cuit or has_cbu
        stats["voucher"] += is_present(mov.get("voucher_number")) or is_present(mov.get("correlative_number"))

    total = len(credits) or 1
    if len(all_movements) >= ib.MOVEMENT_RESULT_LIMIT:
        print(f"ATENCION: se alcanzó el límite de {ib.MOVEMENT_RESULT_LIMIT} movimientos, el resultado puede estar truncado.")
    print(f"Cuenta: bank_number={bank_number} account_number={account_number}")
    print(f"Movimientos totales: {len(all_movements)} | créditos: {len(credits)}")
    print(f"Créditos con customer_cuit:       {stats['cuit']} ({stats['cuit'] * 100 // total}%)")
    print(f"Créditos con account_cbu:         {stats['cbu']} ({stats['cbu'] * 100 // total}%)")
    print(f"Créditos con cuit o cbu:          {stats['cuit_or_cbu']} ({stats['cuit_or_cbu'] * 100 // total}%)")
    print(f"Créditos con voucher/correlativo: {stats['voucher']} ({stats['voucher'] * 100 // total}%)")
    print(f"Campos que devuelve Interbanking: {', '.join(keys)}")
    print(f"CSV: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
