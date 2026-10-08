from __future__ import annotations

TRANSIENT_AUTH_REASONS = frozenset({"NO_SESSION", "LOGIN_IN_PROGRESS"})
REAUTH_REASONS = frozenset(
    {
        "AUTH_EXPIRED",
        "NOT_LOGGED_IN",
        "INVALID_AUTH",
        "INVALID_CREDENTIALS",
        "CAPTCHA_REQUIRED",
    }
)
INVALID_AUTH_REASONS = frozenset({"INVALID_AUTH", "INVALID_CREDENTIALS"})


def should_offer_reauth(
    reason: str, need_reauth: bool, *, auth_required: bool = False
) -> bool:
    if reason in TRANSIENT_AUTH_REASONS:
        return False
    if need_reauth or auth_required:
        return True
    return reason in REAUTH_REASONS


def flag_true(value: object) -> bool:
    if value is True or value == 1:
        return True
    if isinstance(value, str) and value.strip().lower() in ("1", "true", "yes"):
        return True
    return False
