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


class ResponseSequenceClient:
    responses = []
    calls = 0

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def request(self, method, url, **kwargs):
        type(self).calls += 1
        status_code = type(self).responses.pop(0)
        request = httpx.Request(method, url)
        if status_code == 200:
            return httpx.Response(
                status_code,
                json={"accounts": []},
                request=request,
            )
        return httpx.Response(status_code, content=b"", request=request)


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


@pytest.mark.asyncio
async def test_interbanking_get_retries_transient_server_errors(monkeypatch):
    ResponseSequenceClient.responses = [500, 503, 200]
    ResponseSequenceClient.calls = 0
    monkeypatch.setattr(httpx, "AsyncClient", ResponseSequenceClient)
    service = InterBankingService()
    service.retry_attempts = 2
    service.retry_base_delay_seconds = 0

    response = await service._request("GET", "https://interbanking.example.test")

    assert response.status_code == 200
    assert ResponseSequenceClient.calls == 3


def test_interbanking_error_response_does_not_expose_body_to_client():
    response = httpx.Response(
        500,
        content=b'{"internal":"sensitive provider diagnostic"}',
        request=httpx.Request("GET", "https://interbanking.example.test"),
    )

    with pytest.raises(HTTPException) as exc_info:
        InterBankingService._parse_json_response(
            response,
            "Interbanking accounts",
        )

    assert exc_info.value.status_code == 502
    assert "status_code=500" in exc_info.value.detail
    assert "sensitive" not in exc_info.value.detail


@pytest.mark.asyncio
async def test_reconciliation_accounts_fall_back_to_balances(monkeypatch):
    service = InterBankingService()
    service.ib_balances_api_url = "https://interbanking.example.test/balances"

    async def unavailable_accounts():
        raise HTTPException(status_code=502, detail="accounts unavailable")

    async def balances_payload(url, service_name):
        assert url == service.ib_balances_api_url
        assert service_name == "Interbanking balances"
        return {
            "accounts": [
                {
                    "account_number": "123",
                    "bank_number": "015",
                    "account_cbu": "000123",
                }
            ]
        }

    monkeypatch.setattr(service, "get_accounts", unavailable_accounts)
    monkeypatch.setattr(service, "_get_accounts_payload", balances_payload)

    accounts = await service.get_reconciliation_accounts()

    assert accounts[0]["account_number"] == "123"


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
