"""Persisted iCloud session file helpers."""

import logging
import os
from re import match

_LOGGER = logging.getLogger(__name__)


def clear_session_files(storage_path: str, username: str) -> None:
    """Remove stale pyicloud cookie and session files for an account."""
    base = "".join(c for c in username if match(r"\w", c))
    if not base:
        _LOGGER.warning("Cannot clear session files: invalid username %s", username)
        return
    for suffix in (".cookiejar", ".session"):
        path = os.path.join(storage_path, base + suffix)
        if os.path.isfile(path):
            try:
                os.remove(path)
                _LOGGER.debug("Removed stale session file: %s", path)
            except OSError as err:
                _LOGGER.warning("Failed to remove session file %s: %s", path, err)
