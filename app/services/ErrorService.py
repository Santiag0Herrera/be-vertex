from fastapi import HTTPException

class ErrorService:
  @staticmethod
  def raise_not_found(entity: str = "Item"):
      """
      Raises an 404 http exception
      """
      raise HTTPException(status_code=404, detail=f"{entity} not found")

  @staticmethod
  def raise_conflict(message: str = "Conflict occurred"):
      """
      Raises an 409 http exception
      """
      raise HTTPException(status_code=409, detail=message)

  @staticmethod
  def raise_unauthorized(message: str = "Unauthorized"):
      """
      Raises an 401 http exception
      """
      raise HTTPException(status_code=401, detail=message)

  @staticmethod
  def raise_forbidden(message: str = "Forbidden"):
    """
    Raises an 403 http exception
    """
    raise HTTPException(status_code=403, detail=message)
  
  @staticmethod
  def raise_bad_request(message: str = "Bad request"):
    """
    Raises an 400 http exception
    """
    raise HTTPException(status_code=400, detail=message)
  
  @staticmethod
  def raise_if_none(value, entity="Item"):
    """
      Evaluates if a value is None and raises a 404 http exception
    """
    if value is None:
        ErrorService._raise_not_found(entity)