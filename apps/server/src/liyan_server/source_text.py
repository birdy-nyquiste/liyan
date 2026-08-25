"""Text accepted from users and extraction providers before PostgreSQL storage."""


def without_nul(value: str) -> str:
    """Remove NUL, which has no text meaning and PostgreSQL cannot store."""
    return value.replace("\x00", "")


def without_nul_in_mapping(value: dict[str, object]) -> dict[str, object]:
    """Remove NUL recursively from JSON-compatible provider metadata."""

    def clean(item: object) -> object:
        if isinstance(item, str):
            return without_nul(item)
        if isinstance(item, list):
            return [clean(child) for child in item]
        if isinstance(item, dict):
            return {without_nul(str(key)): clean(child) for key, child in item.items()}
        return item

    return {without_nul(key): clean(item) for key, item in value.items()}
