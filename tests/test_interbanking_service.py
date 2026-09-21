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


@pytest.mark.asyncio
async def test_get_movement_keeps_all_required_query_parameters(monkeypatch):
    captured_request = {}

    async def skip_token_refresh():
        return None

    async def capture_request(method, url, **kwargs):
        captured_request.update(method=method, url=url, kwargs=kwargs)
        return httpx.Response(
            200,
            json={"movements_detail": []},
            request=httpx.Request(method, url, params=kwargs.get("params")),
        )

    service = InterBankingService()
    service.ib_api_url = "https://interbanking.example.test/accounts/"
    service.customer_id = "CODIGO_ABONADO"
    service.client_id = "CLIENT_ID"
    service.token = "ACCESS_TOKEN"
    monkeypatch.setattr(service, "_update_token", skip_token_refresh)
    monkeypatch.setattr(service, "_request", capture_request)

    await service.get_movement(
        account_number="0430509162",
        bank_number="015",
        date_since="2026-09-18",
        date_until="2026-09-21",
    )

    request = httpx.Request(
        captured_request["method"],
        captured_request["url"],
        params=captured_request["kwargs"]["params"],
    )

    assert request.url.params["bank-number"] == "015"
    assert request.url.params["customer-id"] == "CODIGO_ABONADO"
    assert request.url.params["date-since"] == "2026-09-18"
    assert request.url.params["date-until"] == "2026-09-21"
    assert request.url.params["limit"] == "1000"
