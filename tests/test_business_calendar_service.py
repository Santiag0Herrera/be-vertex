import datetime
from unittest.mock import AsyncMock

import pytest

from app.services.BusinessCalendarService import BusinessCalendarService


@pytest.fixture
def calendar_service(monkeypatch):
    monkeypatch.delenv("ARGENTINA_BANK_HOLIDAYS", raising=False)
    service = BusinessCalendarService()
    service.get_holidays = AsyncMock(return_value=set())
    return service


@pytest.mark.asyncio
async def test_business_day_keeps_original_date(calendar_service):
    transaction_date = datetime.date(2026, 8, 7)  # Friday

    result = await calendar_service.get_settlement_date(transaction_date)

    assert result == transaction_date


@pytest.mark.asyncio
async def test_weekend_moves_to_monday(calendar_service):
    transaction_date = datetime.date(2026, 8, 8)  # Saturday

    result = await calendar_service.get_settlement_date(transaction_date)

    assert result == datetime.date(2026, 8, 10)


@pytest.mark.asyncio
async def test_weekend_followed_by_holiday_moves_to_tuesday(calendar_service):
    monday_holiday = datetime.date(2026, 8, 10)
    calendar_service.get_holidays = AsyncMock(return_value={monday_holiday})

    result = await calendar_service.get_settlement_date(datetime.date(2026, 8, 8))

    assert result == datetime.date(2026, 8, 11)


def test_extra_bank_holidays_are_loaded_from_environment(monkeypatch):
    monkeypatch.setenv(
        "ARGENTINA_BANK_HOLIDAYS",
        "2026-11-06, 2026-12-24",
    )

    service = BusinessCalendarService()

    assert service.extra_bank_holidays == {
        datetime.date(2026, 11, 6),
        datetime.date(2026, 12, 24),
    }
