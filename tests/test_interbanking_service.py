import httpx
import pytest
from fastapi import HTTPException

from app.services.InterBankingService import InterBankingService
from app.router.transactions import _filter_entity_accounts


class TimeoutClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def request(self, method, url, **kwargs):
        request = httpx.Request(method, url)
        raise httpx.ReadTimeout("timeout", request=request)


@pytest.mark.asyncio
async def test_async_interbanking_timeout_returns_gateway_timeout(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", TimeoutClient)
    service = InterBankingService()

    with pytest.raises(HTTPException) as exc_info:
        await service._request("GET", "https://interbanking.example.test")

    assert exc_info.value.status_code == 504


@pytest.mark.asyncio
async def test_missing_interbanking_configuration_is_explicit():
    service = InterBankingService()

    with pytest.raises(HTTPException) as exc_info:
        await service._request("GET", None)

    assert exc_info.value.status_code == 503


def test_interbanking_accounts_are_filtered_by_entity_cbu():
    accounts = [
        {"account_number": "111", "account_cbu": "000-123"},
        {"account_number": "222", "account_cbu": "000-999"},
    ]

    assert _filter_entity_accounts(accounts, {"000123"}) == [accounts[0]]
