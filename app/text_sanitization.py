def remove_nul_characters(value):
    """Remove characters PostgreSQL cannot store in text fields."""
    if not isinstance(value, str):
        return value
    return value.replace("\x00", "")
