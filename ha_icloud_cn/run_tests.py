"""Silver-required self checks (no full Home Assistant install)."""
from __future__ import annotations

import importlib
import json
import logging
import sys
import tempfile
import types
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent


def _ensure(name: str) -> types.ModuleType:
    mod = sys.modules.get(name)
    if mod is None:
        mod = types.ModuleType(name)
        sys.modules[name] = mod
    if "." in name:
        parent_name, _, child = name.rpartition(".")
        parent = _ensure(parent_name)
        setattr(parent, child, mod)
        if not hasattr(parent, "__path__"):
            parent.__path__ = []  # type: ignore[attr-defined]
    return mod


def _stub() -> None:
    ha = _ensure("homeassistant")
    const = _ensure("homeassistant.const")
    ha.const = const
    const.Platform = type(
        "Platform",
        (),
        {
            "BUTTON": "button",
            "DEVICE_TRACKER": "device_tracker",
            "SENSOR": "sensor",
            "TEXT": "text",
        },
    )
    const.CONF_PASSWORD = "password"
    const.CONF_USERNAME = "username"
    const.PERCENTAGE = "%"

    core = _ensure("homeassistant.core")
    ha.core = core
    core.callback = lambda f: f
    core.CALLBACK_TYPE = object
    core.HomeAssistant = type("HomeAssistant", (), {})
    core.ServiceCall = type("ServiceCall", (), {})

    exceptions = _ensure("homeassistant.exceptions")
    ha.exceptions = exceptions
    for name in (
        "ConfigEntryAuthFailed",
        "ConfigEntryNotReady",
        "HomeAssistantError",
        "ServiceValidationError",
    ):
        setattr(exceptions, name, type(name, (Exception,), {}))

    config_entries = _ensure("homeassistant.config_entries")
    ha.config_entries = config_entries
    config_entries.ConfigEntry = type(
        "ConfigEntry",
        (),
        {"__class_getitem__": classmethod(lambda cls, _item: cls)},
    )
    config_entries.SOURCE_USER = "user"

    class _ConfigFlow:
        def __init_subclass__(cls, domain=None, **kwargs):
            super().__init_subclass__(**kwargs)
            cls.DOMAIN = domain

    config_entries.ConfigFlow = _ConfigFlow
    config_entries.ConfigFlowResult = dict
    config_entries.OptionsFlow = type("OptionsFlow", (), {})

    helpers = _ensure("homeassistant.helpers")
    ha.helpers = helpers
    cv = _ensure("homeassistant.helpers.config_validation")
    helpers.config_validation = cv
    cv.removed = lambda *a, **k: True
    cv.string = str
    selector = _ensure("homeassistant.helpers.selector")
    helpers.selector = selector
    selector.TextSelector = lambda *a, **k: object()
    selector.TextSelectorConfig = lambda *a, **k: object()
    selector.TextSelectorType = type("TextSelectorType", (), {"PASSWORD": "password"})
    selector.EntitySelector = lambda *a, **k: object()
    selector.EntitySelectorConfig = lambda *a, **k: object()
    selector.Selector = object
    selector.SelectSelector = lambda *a, **k: object()
    selector.SelectSelectorConfig = lambda *a, **k: object()
    selector.SelectSelectorMode = type("SelectSelectorMode", (), {"DROPDOWN": "dropdown", "LIST": "list"})
    selector.BooleanSelector = lambda *a, **k: object()
    selector.NumberSelector = lambda *a, **k: object()
    selector.NumberSelectorConfig = lambda *a, **k: object()
    selector.NumberSelectorMode = type("NumberSelectorMode", (), {"BOX": "box"})
    _ensure("homeassistant.helpers.storage").Store = type(
        "Store",
        (),
        {
            "__init__": lambda self, *a, **k: setattr(self, "path", "/tmp"),
            "path": "/tmp",
        },
    )
    _ensure("homeassistant.helpers.dispatcher").dispatcher_send = lambda *a, **k: None
    _ensure("homeassistant.helpers.dispatcher").async_dispatcher_connect = (
        lambda *a, **k: (lambda: None)
    )
    event = _ensure("homeassistant.helpers.event")
    event.async_track_point_in_utc_time = lambda *a, **k: (lambda: None)
    event.async_track_time_change = lambda *a, **k: (lambda: None)
    _ensure("homeassistant.helpers.device_registry")
    _ensure("homeassistant.helpers.entity_registry")
    _ensure("homeassistant.helpers.entity").EntityCategory = type(
        "EntityCategory", (), {"DIAGNOSTIC": "diagnostic"}
    )
    util = _ensure("homeassistant.util")
    ha.util = util
    util.slugify = lambda s: s
    async_util = _ensure("homeassistant.util.async_")
    async_util.run_callback_threadsafe = lambda *a, **k: MagicMock(
        result=lambda timeout=None: None
    )
    dt = _ensure("homeassistant.util.dt")
    util.dt = dt
    dt.now = lambda: datetime(2026, 3, 4, 8, 0, 0)
    dt.utcnow = lambda: datetime(2026, 3, 4, 0, 0, 0)
    dt.as_local = lambda value: value

    _ensure("voluptuous")
    vol = sys.modules["voluptuous"]
    vol.Schema = lambda *a, **k: object()
    vol.Required = lambda *a, **k: object()
    vol.Optional = lambda *a, **k: object()
    vol.All = lambda *a, **k: object()
    vol.Coerce = lambda *a, **k: object()
    vol.Range = lambda *a, **k: object()
    vol.In = lambda *a, **k: object()
    _ensure("requests")

    pyicloud = _ensure("pyicloud")
    pyicloud.PyiCloudService = type("PyiCloudService", (), {})
    pyicloud.__path__ = []  # type: ignore[attr-defined]
    exc = _ensure("pyicloud.exceptions")
    for name in (
        "PyiCloudException",
        "PyiCloudFailedLoginException",
        "PyiCloud2FARequiredException",
        "PyiCloud2SARequiredException",
        "PyiCloudAuthRequiredException",
        "PyiCloudNoDevicesException",
        "PyiCloudServiceNotActivatedException",
        "PyiCloudServiceUnavailable",
        "PyiCloudAPIResponseException",
    ):
        setattr(exc, name, type(name, (Exception,), {}))
    services = _ensure("pyicloud.services")
    services.__path__ = []  # type: ignore[attr-defined]
    findmy = _ensure("pyicloud.services.findmyiphone")
    findmy.AppleDevice = type("AppleDevice", (), {})
    _ensure("pyicloud.base")


def _load_pkg() -> str:
    """Register package namespace without executing integration __init__.py."""
    name = "ha_icloud_cn"
    if name not in sys.modules:
        pkg = types.ModuleType(name)
        pkg.__path__ = [str(ROOT)]  # type: ignore[attr-defined]
        sys.modules[name] = pkg
    return name


def _import(module: str):
    import importlib.util

    pkg = _load_pkg()
    full = f"{pkg}.{module}"
    existing = sys.modules.get(full)
    if existing is not None and getattr(existing, "__file__", None):
        return existing
    path = ROOT / f"{module}.py"
    spec = importlib.util.spec_from_file_location(
        full,
        path,
        submodule_search_locations=[str(ROOT)],
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full] = mod
    spec.loader.exec_module(mod)
    return mod


def test_const_windows_and_defaults() -> None:
    const = _import("const")
    assert const.DEFAULT_MAX_INTERVAL == 10
    assert const.HOME_UPDATE_INTERVAL == 120
    assert const.LOW_BATTERY_THRESHOLD == 10
    assert const.HOME_EXIT_BUFFER_M == 500
    assert const.activity_entities([" a ", "", "b"]) == ["a", "b"]
    assert const.activity_entities("x") == []
    assert const.parse_windows("") == []
    assert const.parse_windows("bad") is None
    windows = const.parse_windows("07:00-09:00,17:00-20:00")
    assert windows is not None
    assert const.in_windows(8 * 60, windows)
    assert not const.in_windows(12 * 60, windows)
    overnight = const.parse_windows("20:00-00:00")
    assert overnight is not None
    assert const.in_windows(21 * 60, overnight)
    assert not const.in_windows(19 * 60, overnight)
    slots = const.windows_to_slots(windows)
    assert "07:00-08:00" in slots
    assert const.windows_text_to_slots("07:00-09:00")
    assert const.slots_to_windows_text(["07:00-08:00", "08:00-09:00"]) == "07:00-09:00"
    pairs = const.windows_text_to_pairs("07:00-09:00", 3)
    assert pairs[0] == ("07:00", "09:00")
    assert const.pairs_to_windows_text([("07:00", "09:00"), ("none", "none")]) == (
        "07:00-09:00"
    )
    assert const.opt_windows_text(["07:00-08:00"]) != ""
    assert const.opt_windows_text(None, "07:00-09:00") == "07:00-09:00"


def test_manifest_and_quality_scale() -> None:
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["config_flow"] is True
    assert manifest["iot_class"] == "cloud_polling"
    assert manifest["codeowners"]
    scale = (ROOT / "quality_scale.yaml").read_text(encoding="utf-8")
    assert "reauthentication-flow" in scale
    assert "test-coverage" in scale
    assert "runtime-data" in scale
    assert "config-flow-test-coverage" in scale


def test_session_storage() -> None:
    session_storage = _import("session_storage")
    with tempfile.TemporaryDirectory() as folder:
        cookie = Path(folder) / "userexamplecom.cookiejar"
        cookie.write_text("x", encoding="utf-8")
        session_storage.clear_session_files(folder, "user@example.com")
        assert not cookie.exists()
        with patch.object(session_storage._LOGGER, "warning"):
            session_storage.clear_session_files(folder, "@@@")


def _account_stub(**kwargs):
    account_mod = _import("account")
    account = object.__new__(account_mod.IcloudAccount)
    account._username = "user@example.com"
    account._online = True
    account._unavailable_logged = False
    account._shutdown = False
    account._reauth_requested = False
    account._home_locate_mode = False
    account._all_in_zone = False
    account._max_interval = 10
    account._peak_enabled = True
    account._offpeak_enabled = True
    account._peak_interval = 10
    account._offpeak_interval = 60
    account._period_weekdays = True
    account._peak_windows = [(7 * 60, 9 * 60), (17 * 60, 20 * 60)]
    account._offpeak_windows = [(20 * 60, 0)]
    account._devices = {}
    account.api = MagicMock()
    account.hass = MagicMock()
    account.hass.data = {}
    account._config_entry = MagicMock(entry_id="abc")
    for key, value in kwargs.items():
        setattr(account, key, value)
    return account, account_mod


def test_account_availability_logging() -> None:
    account, _ = _account_stub()
    records: list[str] = []

    class Handler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record.getMessage())

    handler = Handler()
    log = logging.getLogger("ha_icloud_cn.account")
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    try:
        account._mark_unavailable("timeout")
        account._mark_unavailable("again")
        account._mark_online()
        account._mark_online()
    finally:
        log.removeHandler(handler)
    assert len([m for m in records if "unavailable" in m]) == 1
    assert len([m for m in records if "back online" in m]) == 1
    assert account.online is True


def test_account_period_and_battery_rules() -> None:
    account, account_mod = _account_stub()
    account._all_devices_home_or_company = lambda: True
    value = account._period_interval()
    assert 10 <= value <= 120
    assert account._home_locate_mode is True
    assert account._apply_low_battery_slowdown(10) == 10

    account, _ = _account_stub()
    account._all_devices_home_or_company = lambda: False
    account._home_locate_mode = False
    with patch.object(
        account_mod, "dt_now", return_value=datetime(2026, 3, 4, 8, 0, 0)
    ):
        assert account._period_interval_cap() == (10, True)
        assert account._period_interval() == 10
    with patch.object(
        account_mod, "dt_now", return_value=datetime(2026, 3, 4, 21, 0, 0)
    ):
        assert account._period_interval_cap() == (60, True)
    with patch.object(
        account_mod, "dt_now", return_value=datetime(2026, 3, 4, 12, 0, 0)
    ):
        assert account._period_interval_cap() == (10, False)
    with patch.object(
        account_mod, "dt_now", return_value=datetime(2026, 3, 7, 8, 0, 0)
    ):
        assert account._period_interval_cap() == (10, False)

    device = MagicMock()
    device.battery_level = 5
    account._devices = {"1": device}
    account._device_at_home_or_company = lambda _d: False
    assert account._apply_low_battery_slowdown(10) == 60
    account._device_at_home_or_company = lambda _d: True
    assert account._apply_low_battery_slowdown(10) == 10


def test_config_flow_reauth_surface() -> None:
    flow_mod = _import("config_flow")
    assert flow_mod.IcloudFlowHandler.VERSION == 1
    assert callable(flow_mod.IcloudFlowHandler.async_step_reauth)
    assert callable(flow_mod.IcloudFlowHandler.async_step_reauth_confirm)
    assert callable(flow_mod.IcloudFlowHandler.async_step_user)
    assert callable(flow_mod.IcloudFlowHandler.async_step_verification_code)
    assert callable(flow_mod.IcloudFlowHandler.async_step_trusted_device)
    assert flow_mod.CONF_TRUSTED_DEVICE == "trusted_device"
    assert flow_mod.CONF_VERIFICATION_CODE == "verification_code"
    assert hasattr(flow_mod.IcloudOptionsFlowHandler, "async_step_locate")
    assert hasattr(flow_mod.IcloudOptionsFlowHandler, "async_step_amap")


def test_haversine_and_gcj() -> None:
    account_mod = _import("account")
    assert account_mod._haversine_m(39.9, 116.4, 39.9, 116.4) < 1
    assert account_mod._out_of_china(0.0, 0.0) is True
    assert account_mod._out_of_china(116.4, 39.9) is False
    lng, lat = account_mod._wgs84_to_gcj02(116.4, 39.9)
    assert abs(lng - 116.4) > 0.001 or abs(lat - 39.9) > 0.001


def main() -> int:
    if str(ROOT) in sys.path:
        sys.path.remove(str(ROOT))
    _stub()
    tests = (
        test_const_windows_and_defaults,
        test_manifest_and_quality_scale,
        test_session_storage,
        test_account_availability_logging,
        test_account_period_and_battery_rules,
        test_config_flow_reauth_surface,
        test_haversine_and_gcj,
    )
    failed = 0
    for func in tests:
        try:
            func()
            print(f"PASS {func.__name__}")
        except Exception as err:  # noqa: BLE001
            failed += 1
            print(f"FAIL {func.__name__}: {err}")
    return failed


if __name__ == "__main__":
    raise SystemExit(main())
