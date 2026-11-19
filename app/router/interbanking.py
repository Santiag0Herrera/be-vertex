"""Read-only Interbanking console for super users.

Unlike the /trx Interbanking routes, these are not limited to the caller's
entity CBUs: a super user can list every account the Interbanking customer has
and query its movements directly, to diagnose reconciliation issues.
"""

import logging
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from starlette import status

from app.bank_codes import codes
from app.services.InterBankingService import InterBankingService
from app.services.SuccessService import SuccessService
from app.services.auth_service import require_super_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/interbanking", tags=["Interbanking"])

super_dependency = Annotated[dict, Depends(require_super_user)]

MAX_RANGE_DAYS = 31


def _normalize_account(value: object) -> str:
    return str(value or "").replace(" ", "").replace("-", "").strip()


def _amount(value: object) -> Decimal:
    try:
        return abs(Decimal(str(value)).quantize(Decimal("0.01")))
    except (InvalidOperation, ValueError):
        return Decimal("0.00")


@router.get("/accounts", status_code=status.HTTP_200_OK)
async def get_interbanking_accounts(user: super_dependency):
    ib_service = InterBankingService()
    accounts = await ib_service.get_reconciliation_accounts()

    balances_by_account = {}
    balances_available = True
    try:
        balances = (await ib_service.get_accounts_balances())["result"]
        balances_by_account = {
            (
                _normalize_account(balance.get("bank_number")),
                _normalize_account(balance.get("account_number")),
            ): balance
            for balance in balances
        }
    except HTTPException as exc:
        balances_available = False
        logger.warning(
            "interbanking_console_balances_unavailable status_code=%s",
            exc.status_code,
        )

    result = []
    for account in accounts:
        if not isinstance(account, dict):
            continue
        key = (
            _normalize_account(account.get("bank_number")),
            _normalize_account(account.get("account_number")),
        )
        balance = balances_by_account.get(key) or {}
        result.append(
            {
                **account,
                "bank_name": codes.get(
                    account.get("bank_number"), account.get("bank_number")
                ),
                "balance": balance.get("balance"),
                "balance_currency": balance.get("currency"),
            }
        )

    return SuccessService.response(
        {"accounts": result, "balances_available": balances_available}
    )


@router.get("/movements", status_code=status.HTTP_200_OK)
async def get_interbanking_movements(
    user: super_dependency,
    account_number: str = Query(..., min_length=1, max_length=40),
    bank_number: str = Query(..., min_length=1, max_length=10),
    date_since: date = Query(...),
    date_until: date = Query(...),
    movement_type: Literal["all", "C", "D"] = Query("all"),
):
    if date_since > date_until:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="La fecha desde no puede ser posterior a la fecha hasta.",
        )
    if (date_until - date_since).days + 1 > MAX_RANGE_DAYS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"El rango máximo es de {MAX_RANGE_DAYS} días.",
        )

    ib_service = InterBankingService()
    payload = await ib_service.get_movement(
        account_number=account_number.strip(),
        bank_number=bank_number.strip(),
        date_since=date_since.isoformat(),
        date_until=date_until.isoformat(),
    )
    all_movements = [m for m in payload["movements_detail"] if isinstance(m, dict)]

    credits = [m for m in all_movements if m.get("debit_credit_type") == "C"]
    debits = [m for m in all_movements if m.get("debit_credit_type") == "D"]
    if movement_type == "C":
        movements = credits
    elif movement_type == "D":
        movements = debits
    else:
        movements = all_movements

    logger.info(
        "interbanking_console_query user=%s bank_number=%s date_since=%s date_until=%s count=%s",
        user.get("email"),
        bank_number,
        date_since,
        date_until,
        len(all_movements),
    )

    return SuccessService.response(
        {
            "account_number": account_number,
            "bank_number": bank_number,
            "bank_name": codes.get(bank_number, bank_number),
            "date_since": date_since.isoformat(),
            "date_until": date_until.isoformat(),
            "limit": ib_service.MOVEMENT_RESULT_LIMIT,
            "truncated": len(payload["movements_detail"])
            >= ib_service.MOVEMENT_RESULT_LIMIT,
            "totals": {
                "count": len(all_movements),
                "credits_count": len(credits),
                "credits_amount": str(sum((_amount(m.get("amount")) for m in credits), Decimal("0.00"))),
                "debits_count": len(debits),
                "debits_amount": str(sum((_amount(m.get("amount")) for m in debits), Decimal("0.00"))),
            },
            "movements": movements,
        }
    )
