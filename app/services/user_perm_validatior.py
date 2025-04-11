from fastapi import HTTPException, status
from typing import Literal

def validate_user_minimum_hierarchy(user: dict, min_level: Literal["users", "client", "admin"]) -> bool:
  """
  OPTIONS:
    * users
    * client
    * admin
  """
  level_mapping = {"client": 0, "users": 1, "admin": 2}

  if user is None:
    raise HTTPException(
      status_code=status.HTTP_404_NOT_FOUND,
      detail="User not found"
    )

  user_hierarchy = user.get("hierarchy")
  if user_hierarchy is None:
    raise HTTPException(
      status_code=status.HTTP_403_FORBIDDEN,
      detail="Missing user hierarchy"
    )

  if user_hierarchy < level_mapping[min_level]:
    raise HTTPException(
      status_code=status.HTTP_403_FORBIDDEN,
      detail="Access denied. Insufficient permissions."
    )

  return True