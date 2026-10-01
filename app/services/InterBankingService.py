import asyncio
import datetime
import logging
import os
from typing import Optional

import httpx
import jwt
from fastapi import HTTPException

from app.bank_codes import codes

from .ErrorService import ErrorService
from .SuccessService import SuccessService


logger = logging.getLogger(__name__)


class InterBankingService:
    RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}
    MOVEMENT_RESULT_LIMIT = 1000

    def __init__(self):
        self.error = ErrorService()
        self.success = SuccessService()
        self.ib_auth_url = os.getenv("MS_INTER_BANKING_AUTH_URL")
        self.ib_api_url = os.getenv("MS_INTER_BANKING_API_URL")
        self.ib_balances_api_url = os.getenv("MS_INTER_BANKING_API_BALANCES")
        self.ib_accounts_api_url = os.getenv("MS_INTER_BANKING_API_ACCOUNTS")
        self.client_id = os.getenv("MS_INTER_BANKING_CLIENT_ID")
        self.client_secret = os.getenv("MS_INTER_BANKING_CLIENT_SECRET")
        self.customer_id = os.getenv("MS_INTER_BANKING_CUSTOMER_ID")
        self.token = os.getenv("MS_INTER_BANKING_AT")
        try:
            self.timeout_seconds = max(
                1.0,
                float(os.getenv("MS_INTER_BANKING_TIMEOUT_SECONDS", "20")),
            )
        except ValueError:
            self.timeout_seconds = 20.0
        try:
            self.retry_attempts = max(
                0,
                int(os.getenv("MS_INTER_BANKING_RETRY_ATTEMPTS", "2")),
            )
        except ValueError:
            self.retry_attempts = 2
        try:
            self.retry_base_delay_seconds = max(
                0.0,
                float(os.getenv("MS_INTER_BANKING_RETRY_DELAY_SECONDS", "0.25")),
            )
        except ValueError:
            self.retry_base_delay_seconds = 0.25

    async def _request(self, method: str, url: Optional[str], **kwargs):
        if not url:
            raise HTTPException(
                status_code=503,
                detail="Interbanking is not configured.",
            )
        normalized_method = method.upper()
        max_attempts = 1 + (
            self.retry_attempts if normalized_method in {"GET", "HEAD"} else 0
        )
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                for attempt in range(1, max_attempts + 1):
                    response = await client.request(method, url, **kwargs)
                    should_retry = (
                        response.status_code in self.RETRYABLE_STATUS_CODES
                        and attempt < max_attempts
                    )
                    if not should_retry:
                        return response

                    delay = self.retry_base_delay_seconds * (2 ** (attempt - 1))
                    logger.warning(
                        "interbanking_request_retry method=%s status_code=%s attempt=%s max_attempts=%s delay_seconds=%s",
                        normalized_method,
                        response.status_code,
                        attempt,
                        max_attempts,
                        delay,
                    )
                    await asyncio.sleep(delay)
        except httpx.TimeoutException as exc:
            raise HTTPException(
                status_code=504,
                detail="Interbanking did not respond in time.",
            ) from exc
        except httpx.RequestError as exc:
            raise HTTPException(
                status_code=502,
                detail="Unable to connect to Interbanking.",
            ) from exc

    @staticmethod
    def _build_url(base_url: Optional[str], suffix: str = "") -> str:
        if not base_url:
            raise HTTPException(
                status_code=503,
                detail="Interbanking is not configured.",
            )
        return f"{base_url}{suffix}"

    @staticmethod
    def _parse_json_response(response, service_name: str):
        body_preview = response.text[:500] if response.content else "<empty>"

        if response.status_code >= 400:
            logger.error(
                "interbanking_response_error service=%s status_code=%s body=%s",
                service_name,
                response.status_code,
                body_preview,
            )
            raise HTTPException(
                status_code=502,
                detail=(
                    f"{service_name} request failed. "
                    f"status_code={response.status_code}"
                ),
            )

        if not response.content:
            logger.error(
                "interbanking_empty_response service=%s status_code=%s",
                service_name,
                response.status_code,
            )
            raise HTTPException(
                status_code=502,
                detail=f"{service_name} returned an empty successful response.",
            )

        try:
            result = response.json()
        except ValueError as exc:
            logger.error(
                "interbanking_non_json_response service=%s status_code=%s body=%s",
                service_name,
                response.status_code,
                body_preview,
            )
            raise HTTPException(
                status_code=502,
                detail=f"{service_name} returned an invalid response.",
            ) from exc

        if not isinstance(result, dict):
            logger.error(
                "interbanking_invalid_payload service=%s payload_type=%s",
                service_name,
                type(result).__name__,
            )
            raise HTTPException(
                status_code=502,
                detail=f"{service_name} returned an invalid response structure.",
            )

        return result

    @staticmethod
    def _require_list(payload: dict, field: str, service_name: str) -> list:
        value = payload.get(field)
        if not isinstance(value, list):
            logger.error(
                "interbanking_missing_list service=%s field=%s payload_keys=%s",
                service_name,
                field,
                sorted(payload.keys()),
            )
            raise HTTPException(
                status_code=502,
                detail=f"{service_name} returned an invalid response structure.",
            )
        return value

    @staticmethod
    def _get_bearer_token(token):
        if isinstance(token, dict):
            return token.get("access_token") or token.get("id_token")
        return token

    @staticmethod
    def _is_token_expired(token: str) -> bool:
        token = InterBankingService._get_bearer_token(token)
        if not token:
            return True
        try:
            decoded = jwt.decode(token, options={"verify_signature": False})
            exp = decoded.get("exp")
            now = int(datetime.datetime.now().timestamp())
            return exp is None or exp <= now
        except Exception:
            return True


    async def _update_token(self):
        """
        Obtains account balances
        """
        if not self.token or self._is_token_expired(self.token):
            self.token = await self._authenticate()


    async def _authenticate(self):
        """
        Obtains Inter Banking authentication token for requests.
        """
        url = self.ib_auth_url
        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "client_credentials",
        }
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "service": "http://localhost:8000/dummy-callback",
        }
        response = await self._request("POST", url, headers=headers, data=payload)
        result = self._parse_json_response(response, "Interbanking auth")
        bearer_token = self._get_bearer_token(result)
        if not bearer_token:
            raise HTTPException(
                status_code=502,
                detail="Interbanking authentication returned an invalid response.",
            )

        os.environ["MS_INTER_BANKING_AT"] = bearer_token
        self.token = result
        return result


    async def get_movement(self, account_number, bank_number, date_since, date_until):
        """
        Obtains movements
        """
        await self._update_token()
        url = self._build_url(
            self.ib_api_url,
            f"{account_number}/movements/anteriores",
        )
        params = {
            "bank-number": bank_number,
            "customer-id": self.customer_id,
            "limit": self.MOVEMENT_RESULT_LIMIT,
        }
        if date_since:
            params["date-since"] = date_since
        if date_until:
            params["date-until"] = date_until
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._get_bearer_token(self.token)}",
            "client_id": self.client_id,
        }
        response = await self._request("GET", url, headers=headers, params=params)

        result = self._parse_json_response(response, "Interbanking movements")
        self._require_list(result, "movements_detail", "Interbanking movements")
        return result


    async def get_historical_movement(
        self, account_number, bank_number, date_since, date_until
    ):
        """
        Obtains movements
        """
        await self._update_token()
        url = self._build_url(
            self.ib_api_url,
            f"{account_number}/movements/ZUGHUS?bank-number={bank_number}&customer-id={self.customer_id}",
        )
        if date_since:
            url += f"&date-since={date_since}"
        if date_until:
            url += f"&date-until={date_until}"
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._get_bearer_token(self.token)}",
            "client_id": self.client_id,
        }
        response = await self._request("GET", url, headers=headers)
        result = self._parse_json_response(response, "Interbanking historical movements")
        return result
    

    async def get_movements_for_all_accounts(
        self, date_since: Optional[str], date_until: Optional[str]
    ):
        """
        Obtains all movements for all Interbanking client accounts.
        """

        accounts = await self.get_accounts_only()

        accounts_with_movements = []

        for account in accounts:
            account_number = account.get("account_number")
            bank_number = account.get("bank_number")

            try:
                account_movements = await self.get_movement(
                    account_number=account_number,
                    bank_number=bank_number,
                    date_since=date_since,
                    date_until=date_until,
                )

                movements = account_movements.get("movements_detail", [])

                accounts_with_movements.append(
                    {
                        **account,
                        "movements": movements,
                        "movements_count": len(movements),
                        "error": None,
                    }
                )

            except Exception as e:
                accounts_with_movements.append(
                    {**account, "movements": [], "movements_count": 0, "error": str(e)}
                )

        return accounts_with_movements


    async def _get_accounts_payload(self, url, service_name):
        await self._update_token()
        url = self._build_url(url, f"?customer-id={self.customer_id}")
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._get_bearer_token(self.token)}",
            "client_id": self.client_id,
        }
        response = await self._request("GET", url, headers=headers)
        result = self._parse_json_response(response, service_name)
        self._require_list(result, "accounts", service_name)
        return result


    async def get_accounts_balances(self):
        result = await self._get_accounts_payload(
            self.ib_balances_api_url,
            "Interbanking balances",
        )
        accounts_list = result["accounts"]

        parsed_accounts = []
        for b in accounts_list:
            parsed_result = {
                **b,
                "historial": b.get("historical_balances"),
                "bank_name": codes.get(b.get("bank_number"), b.get("bank_number")),
                "account_type": b.get("account_type"),
                "account_number": b.get("account_number"),
                "balance": (b.get("balances") or {}).get("countable_balance"),
                "currency": b.get("currency"),
            }
            parsed_accounts.append(parsed_result)
        return self.success.response(parsed_accounts)


    async def get_accounts(self):
        return await self._get_accounts_payload(
            self.ib_accounts_api_url,
            "Interbanking accounts",
        )


    async def get_reconciliation_accounts(self):
        try:
            result = await self.get_accounts()
            source = "accounts"
        except HTTPException as primary_error:
            if primary_error.status_code not in {502, 503, 504}:
                raise
            logger.warning(
                "interbanking_accounts_fallback primary_status=%s fallback=balances",
                primary_error.status_code,
            )
            try:
                result = await self._get_accounts_payload(
                    self.ib_balances_api_url,
                    "Interbanking balances",
                )
                source = "balances"
            except HTTPException as fallback_error:
                logger.error(
                    "interbanking_accounts_unavailable primary_status=%s fallback_status=%s",
                    primary_error.status_code,
                    fallback_error.status_code,
                )
                raise HTTPException(
                    status_code=502,
                    detail="Interbanking account services are temporarily unavailable.",
                ) from fallback_error

        accounts = result["accounts"]
        logger.info(
            "interbanking_reconciliation_accounts source=%s count=%s",
            source,
            len(accounts),
        )
        return accounts


    async def get_accounts_only(self):
        accounts_model = await self.get_accounts()
        accounts = accounts_model["accounts"]
        if not accounts:
            self.error.raise_not_found(accounts)
        return accounts
