from .ErrorService import ErrorService
from .SuccessService import SuccessService
import os
import requests
import datetime
import jwt

class InterBankingService:
  req_user: dict

  def __init__(self, req_user):
    self.req_user = req_user
    self.client = requests
    self.raise_error = ErrorService()
    self.success = SuccessService()
    self.ib_auth_url = os.getenv("MS_INTER_BANKING_AUTH_URL")
    self.ib_api_url = os.getenv("MS_INTER_BANKING_API_URL")
    self.client_id = os.getenv("MS_INTER_BANKING_CLIENT_ID")
    self.client_secret = os.getenv("MS_INTER_BANKING_CLIENT_SECRET")
    self.token=os.getenv("MS_INTER_BANKING_AT")
    self.auth_headers = {
      'Content-Type': 'application/x-www-form-urlencoded',
      'Accept': 'application/json',
      'service': 'http://localhost:8000/dummy-callback'
    }
  
  @staticmethod
  def _is_token_expired(token: str) -> bool:
      if not token or token.count(".") != 2:
          return True
      try:
          decoded = jwt.decode(token, options={"verify_signature": False})
          exp = decoded.get("exp")
          now = int(datetime.datetime.now().timestamp())
          return exp is None or exp <= now
      except Exception:
          return True
  
  async def _authenticate(self):
    """
    Obtains Inter Banking authentication token for requests.
    """
    print("-- LLAMADA A LOGIN --")
    url = self.ib_auth_url
    payload = f"client_id={self.client_id}&client_secret={self.client_secret}&grant_type=client_credentials&="
    headers = {
      'Content-Type': 'application/x-www-form-urlencoded',
      'Accept': 'application/json',
      'service': 'http://localhost:8000/dummy-callback',
      'Cookie': 'JSESSIONID=588CA22D9BBCA573D8434D2AD597A7E0; incap_ses_7224_2935514=YgIqC6S/NkblSJPYMs5AZO04lmgAAAAAy1GPB8rcP6uHJzmXuw6M7w==; visid_incap_2935514=YMhpCTdhT3+dABCItC/te+w4lmgAAAAAQUIPAAAAAACSdf1G2IB40aoC6mXv7MpU; a911021363f92e0661f0698f562fc1d7=abdb1d2067e3edc11e05c707d6cd0e2e'
    }
    response = requests.request("POST", url, headers=headers, data=payload)
    result = response.json()
    os.environ["MS_INTER_BANKING_AT"] = result.get('id_token')
    self.token = result.get('id_token')
    return result
  
  async def get_movement(self, account_number, bank_number, customer_id):
    """
    Obtains movements
    """
    print("-- LLAMADA A MOVEMENTS --", self.token)
    if not self.token or self._is_token_expired(self.token):
      self.token = await self._authenticate()

    url = f"{self.ib_api_url}{account_number}/movements/anteriores?bank-number={bank_number}&customer-id={customer_id}"
    payload = {}
    headers = {
      'Accept': 'application/json',
      'Authorization': f"Bearer {self.token.get('access_token')}",
      'client_id': self.client_id,
      'Cookie': 'incap_ses_1847_2886020=Hnx2alJTEB9Gk3gFDd2hGUhAlmgAAAAAvNEZtoVCKk4GVn0Vi0MqtQ==; incap_ses_7224_2935514=YgIqC6S/NkblSJPYMs5AZO04lmgAAAAAy1GPB8rcP6uHJzmXuw6M7w==; visid_incap_2886020=KT8CerkxShOGpaZcV6Dt4kdAlmgAAAAAQUIPAAAAAADCdue2tOgBraNDBwzIQU29; visid_incap_2935514=YMhpCTdhT3+dABCItC/te+w4lmgAAAAAQUIPAAAAAACSdf1G2IB40aoC6mXv7MpU; 44280d419af4711b4c719da82037de73=99ecdab23f2c677e62b69717561ef196'
    }

    response = requests.request("GET", url, headers=headers, data=payload)
    result = response.json()
    return self.success.response(result)

  