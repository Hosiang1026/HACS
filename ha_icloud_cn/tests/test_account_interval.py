"""Account interval / availability unit tests."""
from __future__ import annotations

import logging
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from ha_icloud_cn.account import IcloudAccount
from ha_icloud_cn.const import (
    DEFAULT_MAX_INTERVAL,
    DEFAULT_OFFPEAK_INTERVAL,
    DEFAULT_PEAK_INTERVAL,
    DEVICE_LOCATION_LATITUDE,
    DEVICE_LOCATION_LONGITUDE,
)


def _account(**overrides) -> IcloudAccount:
    account = object.__new__(IcloudAccount)
    account.hass = MagicMock()
    account.hass.data = {}
    account._config_entry = MagicMock()
    account._config_entry.entry_id = "entry"
    account._config_entry.options = {}
    account._config_entry.data = {}
    account._username = "user@example.com"
    account._devices = {}
    account._max_interval = DEFAULT_MAX_INTERVAL
    account._peak_enabled = True
    account._offpeak_enabled = True
    account._peak_windows = [(7 * 60, 9 * 60), (17 * 60, 20 * 60)]
    account._offpeak_windows = [(20 * 60, 0)]
    account._peak_interval = DEFAULT_PEAK_INTERVAL
    account._offpeak_interval = DEFAULT_OFFPEAK_INTERVAL
    account._period_weekdays = True
    account._home_locate_mode = False
    account._all_in_zone = False
    account._online = True
    account._unavailable_logged = False
    account._shutdown = False
    account._reauth_requested = False
    account.api = MagicMock()
    for key, value in overrides.items():
        setattr(account, key, value)
    return account


def test_weekday_periods() -> None:
    account = _account()
    assert account._weekday_periods(0) is True
    assert account._weekday_periods(5) is False
    account._period_weekdays = False
    assert account._weekday_periods(5) is True


def test_period_interval_cap_peak() -> None:
    account = _account()
    fake_now = datetime(2026, 10, 2, 8, 0, 0)
    with patch("ha_icloud_cn.account.dt_now", return_value=fake_now):
        value, fixed = account._period_interval_cap()
    assert value == DEFAULT_PEAK_INTERVAL
    assert fixed is True


def test_period_interval_cap_offpeak() -> None:
    account = _account()
    fake_now = datetime(2026, 10, 2, 21, 0, 0)
    with patch("ha_icloud_cn.account.dt_now", return_value=fake_now):
        value, fixed = account._period_interval_cap()
    assert value == DEFAULT_OFFPEAK_INTERVAL
    assert fixed is True


def test_period_interval_cap_weekend_uses_max() -> None:
    account = _account()
    fake_now = datetime(2026, 10, 4, 8, 0, 0)
    with patch("ha_icloud_cn.account.dt_now", return_value=fake_now):
        value, fixed = account._period_interval_cap()
    assert value == DEFAULT_MAX_INTERVAL
    assert fixed is False


def test_period_interval_home_random() -> None:
    account = _account()
    account._all_devices_home_or_company = lambda: True  # type: ignore[method-assign]
    with patch("ha_icloud_cn.account.random.randint", return_value=42):
        assert account._period_interval() == 42
    assert account._home_locate_mode is True
    assert account._all_in_zone is True


def test_period_interval_away_uses_cap() -> None:
    account = _account()
    account._all_devices_home_or_company = lambda: False  # type: ignore[method-assign]
    fake_now = datetime(2026, 10, 2, 8, 0, 0)
    with patch("ha_icloud_cn.account.dt_now", return_value=fake_now):
        assert account._period_interval() == DEFAULT_PEAK_INTERVAL
    assert account._home_locate_mode is False


def test_low_battery_slowdown_fixed_60() -> None:
    account = _account()
    device = SimpleNamespace(battery_level=5)
    account._devices = {"1": device}
    account._device_at_home_or_company = lambda _device: False  # type: ignore[method-assign]
    assert account._apply_low_battery_slowdown(10) == 60


def test_low_battery_ignored_when_home_mode() -> None:
    account = _account(_home_locate_mode=True)
    device = SimpleNamespace(battery_level=5)
    account._devices = {"1": device}
    assert account._apply_low_battery_slowdown(15) == 15


def test_low_battery_ignored_when_at_home() -> None:
    account = _account()
    device = SimpleNamespace(battery_level=5)
    account._devices = {"1": device}
    account._device_at_home_or_company = lambda _device: True  # type: ignore[method-assign]
    assert account._apply_low_battery_slowdown(10) == 10


def test_mark_unavailable_logs_once() -> None:
    account = _account()
    records: list[str] = []

    class Handler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record.getMessage())

    handler = Handler()
    logger = logging.getLogger("ha_icloud_cn.account")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        account._mark_unavailable("timeout")
        account._mark_unavailable("again")
        account._mark_online()
        account._mark_online()
    finally:
        logger.removeHandler(handler)
    assert len([m for m in records if "unavailable" in m]) == 1
    assert len([m for m in records if "back online" in m]) == 1
    assert account.online is True


def test_coords_in_zones_with_buffer() -> None:
    account = _account()
    zones = [("zone.home", "Home", 31.0, 121.0, 100.0)]
    assert account._coords_in_zones(31.0, 121.0, zones, expanded=False) is True
    assert account._coords_in_zones(31.0035, 121.0, zones, expanded=True) is True


def test_all_devices_home_requires_zones_and_coords() -> None:
    account = _account()
    account._home_zones = lambda: []  # type: ignore[method-assign]
    account._company_zones = lambda: []  # type: ignore[method-assign]
    assert account._all_devices_home_or_company() is False

    account._home_zones = lambda: [  # type: ignore[method-assign]
        ("zone.home", "Home", 31.0, 121.0, 100.0)
    ]
    account._company_zones = lambda: []  # type: ignore[method-assign]
    device = SimpleNamespace(
        location={
            DEVICE_LOCATION_LATITUDE: 31.0,
            DEVICE_LOCATION_LONGITUDE: 121.0,
        }
    )
    account._devices = {"1": device}
    assert account._all_devices_home_or_company() is True
