from .ErrorService import ErrorService
from .SuccessService import SuccessService
from fastapi import HTTPException
import os
import requests
import datetime
import jwt
from app.bank_codes import codes
from typing import Optional


class InterBankingService:
    def __init__(self):
        self.client = requests
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
        self.auth_headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "service": "http://localhost:8000/dummy-callback",
        }

    @staticmethod
    def _parse_json_response(response, service_name: str):
        if not response.content:
            raise HTTPException(
                status_code=502,
                detail=f"{service_name} returned an empty response. status_code={response.status_code}",
            )

        try:
            result = response.json()
        except ValueError as exc:
            raise HTTPException(
                status_code=502,
                detail=(
                    f"{service_name} returned a non-JSON response. "
                    f"status_code={response.status_code} body={response.text[:500]}"
                ),
            ) from exc

        if response.status_code >= 400:
            raise HTTPException(
                status_code=502,
                detail=f"{service_name} request failed. status_code={response.status_code} body={result}",
            )

        return result

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
            "Cookie": "JSESSIONID=588CA22D9BBCA573D8434D2AD597A7E0; incap_ses_7224_2935514=YgIqC6S/NkblSJPYMs5AZO04lmgAAAAAy1GPB8rcP6uHJzmXuw6M7w==; visid_incap_2935514=YMhpCTdhT3+dABCItC/te+w4lmgAAAAAQUIPAAAAAACSdf1G2IB40aoC6mXv7MpU; a911021363f92e0661f0698f562fc1d7=abdb1d2067e3edc11e05c707d6cd0e2e",
        }
        response = requests.request("POST", url, headers=headers, data=payload)
        result = self._parse_json_response(response, "Interbanking auth")
        bearer_token = self._get_bearer_token(result)
        if not bearer_token:
            raise HTTPException(
                status_code=502,
                detail=f"Interbanking auth response did not include access_token or id_token. body={result}",
            )

        os.environ["MS_INTER_BANKING_AT"] = bearer_token
        self.token = result
        return result


    async def get_movement(self, account_number, bank_number, date_since, date_until):
        """
        Obtains movements
        """
        await self._update_token()
        url = f"{self.ib_api_url}{account_number}/movements/anteriores?bank-number={bank_number}&customer-id={self.customer_id}"
        if date_since:
            url += f"&date-since={date_since}"
        if date_until:
            url += f"&date-until={date_until}"
        payload = {}
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._get_bearer_token(self.token)}",
            "client_id": self.client_id,
        }
        response = requests.get(url, headers=headers)

        result = self._parse_json_response(response, "Interbanking movements")
        return result


    async def get_historical_movement(
        self, account_number, bank_number, date_since, date_until
    ):
        """
        Obtains movements
        """
        await self._update_token()
        url = f"{self.ib_api_url}{account_number}/movements/ZUGHUS?bank-number={bank_number}&customer-id={self.customer_id}"
        if date_since:
            url += f"&date-since={date_since}"
        if date_until:
            url += f"&date-until={date_until}"
        payload = {}
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._get_bearer_token(self.token)}",
            "client_id": self.client_id,
        }
        response = requests.request("GET", url, headers=headers, data=payload)
        result = self._parse_json_response(response, "Interbanking historical movements")
        return result
    

    async def get_movements_for_all_accounts(
        self, date_since: Optional[str], date_until: Optional[str]
    ):
        """
        Obtains all movements for all Interbanking client accounts.
        """

        accounts_model = await self.get_accounts()

        accounts = accounts_model.get("accounts", [])

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


    async def get_accounts_balances(self):
        await self._update_token()
        url = f"{self.ib_balances_api_url}?customer-id={self.customer_id}"
        payload = {}
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._get_bearer_token(self.token)}",
            "client_id": self.client_id,
        }
        repsonse = requests.request("GET", url=url, headers=headers, data=payload)
        result = self._parse_json_response(repsonse, "Interbanking balances")
        accounts_list = result.get("accounts")
        if accounts_list is None:
            self.error.raise_not_found(accounts_list)

        parsed_accounts = []
        for b in accounts_list:
            parsed_result = {
                **b,
                "historial": b.get("historical_balances"),
                "bank_name": codes[b.get("bank_number")],
                "account_type": b.get("account_type"),
                "account_number": b.get("account_number"),
                "balance": b.get("balances").get("countable_balance"),
                "currency": b.get("currency"),
            }
            parsed_accounts.append(parsed_result)
        return self.success.response(parsed_accounts)


    async def get_accounts(self):
        await self._update_token()
        url = f"{self.ib_accounts_api_url}?customer-id={self.customer_id}"
        payload = {}
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._get_bearer_token(self.token)}",
            "client_id": self.client_id,
        }
        repsonse = requests.request("GET", url=url, headers=headers, data=payload)
        result = self._parse_json_response(repsonse, "Interbanking accounts")
        return result


    async def get_accounts_only(self):
        accounts_model = await self.get_accounts()
        accounts = accounts_model.get("accounts")
        if not accounts:
            self.error.raise_not_found(accounts)
        return accounts
