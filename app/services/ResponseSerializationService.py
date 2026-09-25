class ResponseSerializationService:
  @staticmethod
  def client(client):
    if client is None:
      return None

    return {
      "id": client.id,
      "first_name": client.first_name,
      "last_name": client.last_name,
      "email": client.email,
      "cuit": client.cuit,
      "phone": client.phone,
      "perm_id": client.perm_id,
      "entity_id": client.entity_id,
      "enabled": client.enabled,
    }

  @staticmethod
  def currency(currency):
    if currency is None:
      return None

    return {
      "id": currency.id,
      "name": currency.name,
    }

  @classmethod
  def balance(cls, balance, total_loaded_amount=None):
    result = {
      "id": balance.id,
      "client_id": balance.client_id,
      "balance_amount": balance.balance_amount,
      "fee_amount": balance.fee_amount,
      "balance_currency_id": balance.balance_currency_id,
      "last_update": balance.last_update,
      "fee_percentage": balance.fee_percentage,
      "enabled": balance.enabled,
      "client": cls.client(balance.client),
      "currency": cls.currency(balance.currency),
    }
    if total_loaded_amount is not None:
      result["total_loaded_amount"] = total_loaded_amount
    return result

  @classmethod
  def transaction(cls, transaction):
    return {
      "document_fingerprint": transaction.document_fingerprint,
      "document_name": transaction.document_name,
      "id": transaction.id,
      "trx_id": transaction.trx_id,
      "emisor_cbu": transaction.emisor_cbu,
      "emisor_name": transaction.emisor_name,
      "emisor_cuit": transaction.emisor_cuit,
      "receptor_cbu": transaction.receptor_cbu,
      "entity_id": transaction.entity_id,
      "client_id": transaction.client_id,
      "amount": transaction.amount,
      "date": transaction.date,
      "received_date": transaction.received_date,
      "creation_date": transaction.creation_date,
      "status": transaction.status,
      "account_id": transaction.account_id,
      "applied_fee_percentage": transaction.applied_fee_percentage,
      "fee_amount": transaction.fee_amount,
      "account": cls.balance(transaction.account),
    }
