from datetime import date

import pytest
from fastapi import HTTPException

from app.router import interbanking
from app.services.auth_service import require_super_user

SUPER = {"email": "super@example.com", "user_perm": "super", "account_type": "user"}


@pytest.mark.asyncio
@pytest.mark.parametrize("level", ["admin", "user"])
async def test_require_super_user_rejects_other_levels(level):
    with pytest.raises(HTTPException) as exc_info:
        await require_super_user({"user_perm": level, "account_type": "user"})
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_require_super_user_accepts_super():
    assert await require_super_user(SUPER) == SUPER


class FakeInterBanking:
    MOVEMENT_RESULT_LIMIT = 1000
    calls = []

    async def get_movement(self, **kwargs):
        type(self).calls.append(kwargs)
        return {
            "movements_detail": [
                {"debit_credit_type": "C", "amount": "1500.50", "customer_cuit": "20111111112"},
                {"debit_credit_type": "C", "amount": 499.5},
                {"debit_credit_type": "D", "amount": "-200"},
            ]
        }


@pytest.mark.asyncio
async def test_movements_filters_by_type_and_totals_all(monkeypatch):
    FakeInterBanking.calls = []
    monkeypatch.setattr(interbanking, "InterBankingService", FakeInterBanking)

    response = await interbanking.get_interbanking_movements(
        user=SUPER,
        account_number=" 0430509162 ",
        bank_number="015",
        date_since=date(2026, 11, 13),
        date_until=date(2026, 11, 18),
        movement_type="C",
    )

    result = response["result"]
    assert FakeInterBanking.calls == [
        {
            "account_number": "0430509162",
            "bank_number": "015",
            "date_since": "2026-11-13",
            "date_until": "2026-11-18",
        }
    ]
    assert len(result["movements"]) == 2
    assert result["truncated"] is False
    assert result["totals"] == {
        "count": 3,
        "credits_count": 2,
        "credits_amount": "2000.00",
        "debits_count": 1,
        "debits_amount": "200.00",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "since,until",
    [
        (date(2026, 11, 18), date(2026, 11, 13)),
        (date(2026, 10, 1), date(2026, 11, 18)),
    ],
)
async def test_movements_rejects_invalid_ranges(monkeypatch, since, until):
    monkeypatch.setattr(interbanking, "InterBankingService", FakeInterBanking)
    with pytest.raises(HTTPException) as exc_info:
        await interbanking.get_interbanking_movements(
            user=SUPER,
            account_number="1",
            bank_number="015",
            date_since=since,
            date_until=until,
            movement_type="all",
        )
    assert exc_info.value.status_code == 422
