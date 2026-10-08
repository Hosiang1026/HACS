"""Session storage helper tests."""
from __future__ import annotations

from pathlib import Path
from re import match

from ha_icloud_cn.session_storage import clear_session_files


def _base(username: str) -> str:
    return "".join(c for c in username if match(r"\w", c))


def test_clear_session_files_missing_dir(tmp_path: Path) -> None:
    clear_session_files(str(tmp_path / "missing"), "user@example.com")


def test_clear_session_files_removes_matches(tmp_path: Path) -> None:
    username = "user@example.com"
    base = _base(username)
    target = tmp_path / f"{base}.session"
    cookie = tmp_path / f"{base}.cookiejar"
    other = tmp_path / "other.session"
    target.write_text("x", encoding="utf-8")
    cookie.write_text("c", encoding="utf-8")
    other.write_text("y", encoding="utf-8")
    clear_session_files(str(tmp_path), username)
    assert not target.exists()
    assert not cookie.exists()
    assert other.exists()


def test_clear_session_files_invalid_username(tmp_path: Path) -> None:
    clear_session_files(str(tmp_path), "@@@")
