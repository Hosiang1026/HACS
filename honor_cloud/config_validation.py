from __future__ import annotations


def validate_credentials(
    base_url: str, username: str, password: str
) -> dict[str, str]:
    errors: dict[str, str] = {}
    if not base_url:
        errors["base"] = "base_url_required"
    elif not base_url.startswith(("http://", "https://")):
        errors["base"] = "invalid_url"
    elif not username:
        errors["base"] = "username_required"
    elif not password:
        errors["base"] = "password_required"
    return errors
