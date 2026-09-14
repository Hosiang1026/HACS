from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector
from homeassistant.util import dt as dt_util
from homeassistant.util import slugify

from .amap_fetcher import probe_amap_cars
from .api import (
    create_ssl_context,
    extract_account_name,
    fetch_vehicle_info,
    fetch_violation_info,
    parse_vehicles,
)
from .helpers import normalize_config_date
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_ACCOUNT_NAME,
    CONF_ACW_TC,
    CONF_ADDRESS_DISTANCE,
    CONF_ADDRESSAPI,
    CONF_ADDRESSAPI_KEY,
    CONF_AMAP_KEY,
    CONF_AMAP_LOGIN_AT,
    CONF_AMAP_PARAMDATA,
    CONF_AMAP_SESSIONID,
    CONF_AMAP_TID,
    CONF_COMMUTE_INTERVAL,
    CONF_COMMUTE_SPEED,
    CONF_COMMUTE_ZONE,
    CONF_ENABLE_12123,
    CONF_ENABLE_AMAP,
    CONF_EXPIRE_DAYS,
    CONF_FUEL_GRADE,
    CONF_FUEL_PRICE,
    CONF_FUEL_PRICE_ENTITY,
    CONF_INSURANCE_EXPIRY,
    CONF_JSESSIONID,
    CONF_LOGIN_AT,
    CONF_MAINT_DAYS,
    CONF_MAINT_KM,
    CONF_NAME,
    CONF_NOTIFY,
    CONF_ANNOUNCE,
    CONF_NOTIFY_ARRIVE,
    CONF_NOTIFY_ENABLE,
    CONF_NOTIFY_INSPECT,
    CONF_NOTIFY_INSURANCE,
    CONF_NOTIFY_LEAVE,
    CONF_NOTIFY_LICENSE,
    CONF_NOTIFY_MAINT,
    CONF_NOTIFY_VIOLATION,
    CONF_NOTIFY_YEARLY,
    CONF_ODOMETER,
    CONF_ODOMETER_ENTITY,
    CONF_OWNERS,
    CONF_PLATE,
    CONF_POLL_ACTIVE,
    CONF_POLL_EXCLUDE_ZONES,
    CONF_PRIVATE_KEY,
    CONF_PROVINCE_NAME,
    CONF_PURCHASE_DATE,
    CONF_INSPECT_EXPIRY,
    CONF_MAINT_DATE,
    CONF_MAINT_ODO,
    CONF_BATTERY_REPLACE_DATE,
    CONF_SF,
    CONF_TANK_CAPACITY,
    CONF_URL,
    CONF_VEHICLE_INDEX,
    DEFAULT_ADDRESS_DISTANCE,
    DEFAULT_COMMUTE_INTERVAL,
    DEFAULT_COMMUTE_SPEED,
    DEFAULT_EXPIRE_DAYS,
    DEFAULT_MAINT_DAYS,
    DEFAULT_MAINT_KM,
    DEFAULT_NOTIFY_INSPECT,
    DEFAULT_NOTIFY_INSURANCE,
    DEFAULT_NOTIFY_LICENSE,
    DEFAULT_NOTIFY_MAINT,
    DEFAULT_NOTIFY_VIOLATION,
    DEFAULT_NOTIFY_YEARLY,
    DEFAULT_POLL_ACTIVE,
    DEFAULT_PRICES,
    DEFAULT_TANK,
    DOMAIN,
    PROVINCE_CODE_MAPPING,
    PROVINCES,
    QR_CODE_API_URL,
    QR_CODE_QUERY_URL,
    QR_POLL_INTERVAL,
    QR_POLL_TIMEOUT,
    REQUEST_TIMEOUT,
    UNIT_CNY_PER_L,
    UNIT_DAY,
    UNIT_KM,
    UNIT_KMH,
    UNIT_L,
    UNIT_M,
    UNIT_MIN,
)

_LOGGER = logging.getLogger(__name__)

_PWD_SELECTOR = selector.TextSelector(
    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
)


class QrLoginError(Exception):
    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.key = key


def _amap_tid_used(hass: HomeAssistant, tid: str, exclude_entry_id: str | None = None) -> bool:
    tid = str(tid or "").strip()
    if not tid:
        return False
    for entry in hass.config_entries.async_entries(DOMAIN):
        if exclude_entry_id and entry.entry_id == exclude_entry_id:
            continue
        if str(entry.data.get(CONF_AMAP_TID) or "").strip() == tid:
            return True
    return False


def _12123_used(
    hass: HomeAssistant,
    sf: str,
    vehicle_index: int,
    exclude_entry_id: str | None = None,
) -> bool:
    sf = str(sf or "").strip()
    if not sf:
        return False
    try:
        idx = int(vehicle_index)
    except (TypeError, ValueError):
        idx = 1
    for entry in hass.config_entries.async_entries(DOMAIN):
        if exclude_entry_id and entry.entry_id == exclude_entry_id:
            continue
        if not entry.data.get(CONF_SF):
            continue
        if str(entry.data.get(CONF_SF)) != sf:
            continue
        try:
            cur = int(entry.data.get(CONF_VEHICLE_INDEX, 1))
        except (TypeError, ValueError):
            cur = 1
        if cur == idx:
            return True
    return False


def _optional_date_key(d: dict[str, Any], key: str) -> Any:
    if d.get(key):
        return vol.Optional(key, default=d[key])
    return vol.Optional(key)


def _stats_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    d = defaults or {}
    fields: dict[Any, Any] = {
        vol.Required(CONF_NAME, default=d.get(CONF_NAME, "我的车")): selector.TextSelector(),
        vol.Optional(CONF_PLATE, default=d.get(CONF_PLATE, "")): selector.TextSelector(),
    }
    buy_key = (
        vol.Required(CONF_PURCHASE_DATE, default=d[CONF_PURCHASE_DATE])
        if d.get(CONF_PURCHASE_DATE)
        else vol.Required(CONF_PURCHASE_DATE)
    )
    fields[buy_key] = selector.DateSelector()
    grade = str(d.get(CONF_FUEL_GRADE, "92"))
    try:
        grade_int = int(grade)
    except (TypeError, ValueError):
        grade_int = 92
    default_price = d.get(CONF_FUEL_PRICE)
    if default_price is None:
        default_price = DEFAULT_PRICES.get(grade_int, 7.50)
    try:
        default_price = float(default_price)
    except (TypeError, ValueError):
        default_price = float(DEFAULT_PRICES.get(grade_int, 7.50))
    if not 0.01 <= default_price <= 50:
        default_price = float(DEFAULT_PRICES.get(grade_int, 7.50))
    default_odo = d.get(CONF_ODOMETER, 0)
    fields.update(
        {
            vol.Required(CONF_FUEL_GRADE, default=grade): selector.SelectSelector(
                selector.SelectSelectorConfig(options=["92", "95", "98"], mode=selector.SelectSelectorMode.DROPDOWN)
            ),
            vol.Required(CONF_TANK_CAPACITY, default=d.get(CONF_TANK_CAPACITY, DEFAULT_TANK)): selector.NumberSelector(
                selector.NumberSelectorConfig(min=10, max=200, step=1, unit_of_measurement=UNIT_L, mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Required(CONF_MAINT_KM, default=d.get(CONF_MAINT_KM, DEFAULT_MAINT_KM)): selector.NumberSelector(
                selector.NumberSelectorConfig(min=1000, max=50000, step=500, unit_of_measurement=UNIT_KM, mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Required(CONF_MAINT_DAYS, default=d.get(CONF_MAINT_DAYS, DEFAULT_MAINT_DAYS)): selector.NumberSelector(
                selector.NumberSelectorConfig(min=30, max=730, step=1, unit_of_measurement=UNIT_DAY, mode=selector.NumberSelectorMode.BOX)
            ),
            _optional_date_key(d, CONF_INSURANCE_EXPIRY): selector.DateSelector(),
            _optional_date_key(d, CONF_INSPECT_EXPIRY): selector.DateSelector(),
            _optional_date_key(d, CONF_MAINT_DATE): selector.DateSelector(),
            _optional_date_key(d, CONF_BATTERY_REPLACE_DATE): selector.DateSelector(),
            vol.Optional(CONF_MAINT_ODO, default=float(d.get(CONF_MAINT_ODO, 0) or 0)): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=9999999, step=0.1, unit_of_measurement=UNIT_KM, mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Optional(CONF_ODOMETER, default=float(default_odo or 0)): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=9999999, step=0.1, unit_of_measurement=UNIT_KM, mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Required(CONF_FUEL_PRICE, default=float(default_price)): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0.01, max=50, step=0.01, unit_of_measurement=UNIT_CNY_PER_L, mode=selector.NumberSelectorMode.BOX)
            ),
        }
    )
    odo_key = (
        vol.Optional(CONF_ODOMETER_ENTITY, default=d[CONF_ODOMETER_ENTITY])
        if d.get(CONF_ODOMETER_ENTITY)
        else vol.Optional(CONF_ODOMETER_ENTITY)
    )
    price_key = (
        vol.Optional(CONF_FUEL_PRICE_ENTITY, default=d[CONF_FUEL_PRICE_ENTITY])
        if d.get(CONF_FUEL_PRICE_ENTITY)
        else vol.Optional(CONF_FUEL_PRICE_ENTITY)
    )
    fields[odo_key] = selector.EntitySelector(
        selector.EntitySelectorConfig(domain=["sensor", "input_number", "number"])
    )
    fields[price_key] = selector.EntitySelector(
        selector.EntitySelectorConfig(domain=["sensor"])
    )
    return vol.Schema(fields)


def _options_base(entry: config_entries.ConfigEntry) -> dict[str, Any]:
    return dict(entry.options)


def _finalize_options(
    entry: config_entries.ConfigEntry,
    patch: dict[str, Any],
    user_input: dict[str, Any] | None = None,
) -> dict[str, Any]:
    options = _options_base(entry)
    options.update(patch)
    if user_input is not None:
        options = _apply_optional_clears(options, user_input)
    return options


def _clean_stats(user_input: dict[str, Any]) -> dict[str, Any]:
    data: dict[str, Any] = {
        CONF_NAME: user_input[CONF_NAME],
        CONF_FUEL_GRADE: int(user_input[CONF_FUEL_GRADE]),
        CONF_TANK_CAPACITY: float(user_input[CONF_TANK_CAPACITY]),
        CONF_MAINT_KM: float(user_input[CONF_MAINT_KM]),
        CONF_MAINT_DAYS: int(user_input[CONF_MAINT_DAYS]),
    }
    purchase = normalize_config_date(user_input.get(CONF_PURCHASE_DATE))
    if purchase:
        data[CONF_PURCHASE_DATE] = purchase
    for key in (CONF_INSURANCE_EXPIRY, CONF_INSPECT_EXPIRY, CONF_MAINT_DATE, CONF_BATTERY_REPLACE_DATE):
        normalized = normalize_config_date(user_input.get(key))
        if normalized:
            data[key] = normalized
    if CONF_MAINT_ODO in user_input and user_input.get(CONF_MAINT_ODO) is not None:
        data[CONF_MAINT_ODO] = float(user_input[CONF_MAINT_ODO])
    if CONF_ODOMETER in user_input and user_input.get(CONF_ODOMETER) is not None:
        data[CONF_ODOMETER] = float(user_input[CONF_ODOMETER])
    data[CONF_FUEL_PRICE] = float(user_input[CONF_FUEL_PRICE])
    if CONF_ODOMETER_ENTITY in user_input:
        if user_input.get(CONF_ODOMETER_ENTITY):
            data[CONF_ODOMETER_ENTITY] = user_input[CONF_ODOMETER_ENTITY]
    if CONF_FUEL_PRICE_ENTITY in user_input:
        if user_input.get(CONF_FUEL_PRICE_ENTITY):
            data[CONF_FUEL_PRICE_ENTITY] = user_input[CONF_FUEL_PRICE_ENTITY]
    return data


def _plate_from_input(user_input: dict[str, Any]) -> str:
    return str(user_input.get(CONF_PLATE) or "").strip()


def _plate_from_amap_cars(cars: list[dict[str, Any]], tid: str) -> str:
    for car in cars:
        if str(car.get("tid") or "") == tid:
            return str(car.get("plateNum") or "").strip()
    return ""


def _apply_optional_clears(options: dict[str, Any], user_input: dict[str, Any]) -> dict[str, Any]:
    out = dict(options)
    for key in (
        CONF_ODOMETER_ENTITY,
        CONF_FUEL_PRICE_ENTITY,
        CONF_INSURANCE_EXPIRY,
        CONF_INSPECT_EXPIRY,
        CONF_MAINT_DATE,
        CONF_BATTERY_REPLACE_DATE,
    ):
        if key in user_input and not user_input.get(key):
            out.pop(key, None)
    if CONF_NOTIFY in user_input and not _notify_values(user_input.get(CONF_NOTIFY)):
        out.pop(CONF_NOTIFY, None)
    if CONF_ANNOUNCE in user_input and not _announce_values(user_input.get(CONF_ANNOUNCE)):
        out.pop(CONF_ANNOUNCE, None)
    return out


def _announce_values(raw: Any) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, str):
        return [raw]
    return [item for item in raw if isinstance(item, str) and item]


def _notify_values(raw: Any) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, dict):
        action = raw.get("action") or raw.get("service")
        return [action] if action else []
    out: list[str] = []
    for item in raw:
        if isinstance(item, str) and item:
            out.append(item)
        elif isinstance(item, dict):
            action = item.get("action") or item.get("service")
            if action:
                out.append(action)
    return out


def _notify_options(hass: HomeAssistant | None, current: Any = None) -> list[str]:
    names: set[str] = set(_notify_values(current))
    if hass:
        for name in hass.services.async_services().get("notify", {}):
            if name != "send_message":
                names.add(f"notify.{name}")
        names.update(hass.states.async_entity_ids("notify"))
    return sorted(names)


def _amap_car_options(cars: list[dict[str, Any]]) -> dict[str, str]:
    options: dict[str, str] = {}
    for car in cars:
        if not isinstance(car, dict):
            continue
        tid = str(car.get("tid") or "").strip()
        if not tid:
            continue
        label = str(car.get("plateNum") or car.get("vehicleName") or tid)
        options[tid] = label
    return options


def _clean_notify(user_input: dict[str, Any], include_12123: bool = True, include_amap: bool = False) -> dict[str, Any]:
    data: dict[str, Any] = {
        CONF_NOTIFY_YEARLY: bool(user_input.get(CONF_NOTIFY_YEARLY, DEFAULT_NOTIFY_YEARLY)),
        CONF_NOTIFY_MAINT: bool(user_input.get(CONF_NOTIFY_MAINT, DEFAULT_NOTIFY_MAINT)),
        CONF_NOTIFY_INSURANCE: bool(user_input.get(CONF_NOTIFY_INSURANCE, DEFAULT_NOTIFY_INSURANCE)),
        CONF_NOTIFY_INSPECT: bool(user_input.get(CONF_NOTIFY_INSPECT, DEFAULT_NOTIFY_INSPECT)),
        CONF_EXPIRE_DAYS: int(user_input.get(CONF_EXPIRE_DAYS, DEFAULT_EXPIRE_DAYS)),
    }
    if include_12123:
        data[CONF_NOTIFY_VIOLATION] = bool(user_input.get(CONF_NOTIFY_VIOLATION, DEFAULT_NOTIFY_VIOLATION))
        data[CONF_NOTIFY_LICENSE] = bool(user_input.get(CONF_NOTIFY_LICENSE, DEFAULT_NOTIFY_LICENSE))
    else:
        data[CONF_NOTIFY_VIOLATION] = False
        data[CONF_NOTIFY_LICENSE] = False
    if include_amap:
        data[CONF_NOTIFY_LEAVE] = bool(user_input.get(CONF_NOTIFY_LEAVE, False))
        data[CONF_NOTIFY_ARRIVE] = bool(user_input.get(CONF_NOTIFY_ARRIVE, False))
    if CONF_NOTIFY in user_input:
        notify = _notify_values(user_input.get(CONF_NOTIFY))
        if notify:
            data[CONF_NOTIFY] = notify
    if CONF_ANNOUNCE in user_input:
        announce = _announce_values(user_input.get(CONF_ANNOUNCE))
        if announce:
            data[CONF_ANNOUNCE] = announce
    return data


def _notify_schema(
    defaults: dict[str, Any] | None = None,
    hass: HomeAssistant | None = None,
    include_12123: bool = True,
    include_amap: bool = False,
) -> vol.Schema:
    d = defaults or {}
    legacy = bool(d.get(CONF_NOTIFY_ENABLE, False))

    def _flag(key: str, default: bool) -> bool:
        if key in d:
            return bool(d.get(key))
        return legacy or default

    fields: dict[Any, Any] = {}
    if include_12123:
        fields[vol.Required(CONF_NOTIFY_VIOLATION, default=_flag(CONF_NOTIFY_VIOLATION, DEFAULT_NOTIFY_VIOLATION))] = selector.BooleanSelector()
    fields[vol.Required(CONF_NOTIFY_YEARLY, default=_flag(CONF_NOTIFY_YEARLY, DEFAULT_NOTIFY_YEARLY))] = selector.BooleanSelector()
    fields[vol.Required(CONF_NOTIFY_MAINT, default=_flag(CONF_NOTIFY_MAINT, DEFAULT_NOTIFY_MAINT))] = selector.BooleanSelector()
    fields[vol.Required(CONF_NOTIFY_INSURANCE, default=_flag(CONF_NOTIFY_INSURANCE, DEFAULT_NOTIFY_INSURANCE))] = selector.BooleanSelector()
    fields[vol.Required(CONF_NOTIFY_INSPECT, default=_flag(CONF_NOTIFY_INSPECT, DEFAULT_NOTIFY_INSPECT))] = selector.BooleanSelector()
    if include_12123:
        fields[vol.Required(CONF_NOTIFY_LICENSE, default=_flag(CONF_NOTIFY_LICENSE, DEFAULT_NOTIFY_LICENSE))] = selector.BooleanSelector()
    if include_amap:
        fields[vol.Required(CONF_NOTIFY_LEAVE, default=bool(d.get(CONF_NOTIFY_LEAVE, False)))] = selector.BooleanSelector()
        fields[vol.Required(CONF_NOTIFY_ARRIVE, default=bool(d.get(CONF_NOTIFY_ARRIVE, False)))] = selector.BooleanSelector()
    fields[vol.Required(CONF_EXPIRE_DAYS, default=d.get(CONF_EXPIRE_DAYS, DEFAULT_EXPIRE_DAYS))] = selector.NumberSelector(
        selector.NumberSelectorConfig(min=1, max=180, step=1, unit_of_measurement=UNIT_DAY, mode=selector.NumberSelectorMode.BOX)
    )
    current_notify = _notify_values(d.get(CONF_NOTIFY))
    notify_key = (
        vol.Optional(CONF_NOTIFY, default=current_notify)
        if current_notify
        else vol.Optional(CONF_NOTIFY)
    )
    fields[notify_key] = selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=_notify_options(hass, current_notify),
            multiple=True,
            custom_value=True,
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )
    current_announce = _announce_values(d.get(CONF_ANNOUNCE))
    announce_key = (
        vol.Optional(CONF_ANNOUNCE, default=current_announce)
        if current_announce
        else vol.Optional(CONF_ANNOUNCE)
    )
    fields[announce_key] = selector.EntitySelector(
        selector.EntitySelectorConfig(domain=["media_player", "text", "input_text"], multiple=True)
    )
    return vol.Schema(fields)


class CarStatsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        super().__init__()
        self._vehicles: list[dict[str, Any]] = []
        self._stats_options: dict[str, Any] = {}
        self._selected_province: str | None = None
        self._selected_province_code: str | None = None
        self._session: aiohttp.ClientSession | None = None
        self._qrcode_digest: str | None = None
        self.token: str | None = None
        self._img_base64: str | None = None
        self.url: str | None = None
        self._access_token: str | None = None
        self._jsessionid: str | None = None
        self._acw_tc: str = ""
        self._keepalive_url: str | None = None
        self._account_name: str = ""
        self._vehicle_index: int = 1
        self._default_name: str = "我的车"
        self._enable_12123: bool = False
        self._enable_amap: bool = False
        self._amap_auth: dict[str, Any] = {}
        self._amap_cars: list[dict[str, Any]] = []
        self._amap_data: dict[str, Any] = {}
        self._amap_options: dict[str, Any] = {}
        self._qr_task: asyncio.Task | None = None
        self._last_qr_error: str | None = None

    def _reauth_entry(self):
        if hasattr(self, "_get_reauth_entry"):
            return self._get_reauth_entry()
        return self.hass.config_entries.async_get_entry(self.context["entry_id"])

    def _qr_msg(self, *, retry: bool = False) -> str:
        if self._img_base64:
            tip = (
                "点击下方提交重新获取二维码。"
                if retry
                else "请扫码；转圈表示等待确认，成功后自动继续。"
            )
            return (
                f"![12123登录二维码](data:image/png;base64,{self._img_base64})\n\n"
                "**请使用12123手机App扫描上方二维码。**\n\n"
                f"{tip}"
            )
        return "二维码未加载，请点击提交重试。"

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            self._enable_12123 = bool(user_input.get(CONF_ENABLE_12123))
            self._enable_amap = bool(user_input.get(CONF_ENABLE_AMAP))
            if self._enable_12123:
                return await self.async_step_province()
            if self._enable_amap:
                return await self.async_step_amap_auth()
            self._vehicle_index = 1
            self._default_name = "我的车"
            return await self.async_step_stats()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ENABLE_12123, default=False): selector.BooleanSelector(),
                    vol.Required(CONF_ENABLE_AMAP, default=False): selector.BooleanSelector(),
                }
            ),
        )

    async def _after_12123(self):
        if self._enable_amap:
            return await self.async_step_amap_auth()
        return await self.async_step_stats()

    async def async_step_amap_auth(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            key = str(user_input.get(CONF_AMAP_KEY) or "").strip()
            sid = str(user_input.get(CONF_AMAP_SESSIONID) or "").strip().rstrip(";")
            pdata = str(user_input.get(CONF_AMAP_PARAMDATA) or "").strip()
            if not key:
                errors[CONF_AMAP_KEY] = "required"
            elif not sid:
                errors[CONF_AMAP_SESSIONID] = "required"
            elif not pdata:
                errors[CONF_AMAP_PARAMDATA] = "required"
            else:
                try:
                    cars = await self.hass.async_add_executor_job(probe_amap_cars, key, sid, pdata)
                except Exception:
                    cars = []
                    errors["base"] = "amap_auth_failed"
                if not errors:
                    cars = [c for c in cars if isinstance(c, dict) and str(c.get("tid") or "").strip()]
                    if not cars:
                        errors["base"] = "amap_no_cars"
                    else:
                        self._amap_auth = {
                            CONF_AMAP_KEY: key,
                            CONF_AMAP_SESSIONID: sid,
                            CONF_AMAP_PARAMDATA: pdata,
                        }
                        self._amap_cars = cars
                        return await self.async_step_amap_car()
        defaults = self._amap_auth
        return self.async_show_form(
            step_id="amap_auth",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_AMAP_KEY, default=defaults.get(CONF_AMAP_KEY, "")): _PWD_SELECTOR,
                    vol.Required(CONF_AMAP_SESSIONID, default=defaults.get(CONF_AMAP_SESSIONID, "")): selector.TextSelector(),
                    vol.Required(CONF_AMAP_PARAMDATA, default=defaults.get(CONF_AMAP_PARAMDATA, "")): selector.TextSelector(
                        selector.TextSelectorConfig(multiline=True)
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_amap_car(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        options = _amap_car_options(self._amap_cars)
        if not options:
            return self.async_abort(reason="amap_no_cars")
        if user_input is not None:
            tid = str(user_input[CONF_AMAP_TID])
            owners = user_input.get(CONF_OWNERS) or []
            if isinstance(owners, str):
                owners = [owners] if owners.strip() else []
            owners = [str(o).strip() for o in owners if str(o).strip()]
            if not owners:
                errors[CONF_OWNERS] = "required"
            else:
                plate = _plate_from_amap_cars(self._amap_cars, tid)
                self._amap_data = {
                    CONF_AMAP_KEY: self._amap_auth[CONF_AMAP_KEY],
                    CONF_AMAP_SESSIONID: self._amap_auth[CONF_AMAP_SESSIONID],
                    CONF_AMAP_PARAMDATA: self._amap_auth[CONF_AMAP_PARAMDATA],
                    CONF_AMAP_TID: tid,
                    CONF_PLATE: plate,
                    CONF_AMAP_LOGIN_AT: dt_util.now().isoformat(),
                }
                self._amap_options = {
                    CONF_OWNERS: owners,
                    CONF_POLL_ACTIVE: int(user_input.get(CONF_POLL_ACTIVE, DEFAULT_POLL_ACTIVE)),
                }
                if plate and not self._enable_12123:
                    self._default_name = plate
                if _amap_tid_used(self.hass, tid):
                    errors["base"] = "amap_tid_configured"
                else:
                    return await self.async_step_stats()
        return self.async_show_form(
            step_id="amap_car",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_AMAP_TID, default=list(options)[0]): vol.In(options),
                    vol.Required(CONF_OWNERS): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="person", multiple=True)
                    ),
                    vol.Required(CONF_POLL_ACTIVE, default=DEFAULT_POLL_ACTIVE): selector.NumberSelector(
                        selector.NumberSelectorConfig(min=1, max=180, step=1, unit_of_measurement=UNIT_MIN, mode=selector.NumberSelectorMode.BOX)
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_province(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            self._selected_province = user_input["province"]
            self._selected_province_code = PROVINCE_CODE_MAPPING[self._selected_province]
            if not await self._async_fetch_qr(errors):
                return self._show_province_form(errors)
            return await self.async_step_next()
        return self._show_province_form(errors)

    def _show_province_form(self, errors: dict[str, str]):
        return self.async_show_form(
            step_id="province",
            data_schema=vol.Schema({vol.Required("province"): vol.In(PROVINCES)}),
            errors=errors,
        )

    async def _async_ensure_http(self, errors: dict[str, str]) -> bool:
        if self._session and not self._session.closed:
            return True
        try:
            ssl_context = await self.hass.async_add_executor_job(create_ssl_context)
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
                connector=aiohttp.TCPConnector(
                    ssl=ssl_context,
                    force_close=True,
                    enable_cleanup_closed=True,
                ),
            )
            return True
        except Exception:
            errors["base"] = "session_recreate_failed"
            return False

    async def _async_fetch_qr(self, errors: dict[str, str]) -> bool:
        if not await self._async_ensure_http(errors):
            return False
        self._qrcode_digest = None
        self.token = None
        self._img_base64 = None
        try:
            async with self._session.get(QR_CODE_API_URL) as response:
                if response.status != 200:
                    errors["base"] = "server_error"
                    await self._cleanup_session()
                    return False
                try:
                    response_data = await response.json()
                except aiohttp.ContentTypeError:
                    errors["base"] = "invalid_response"
                    await self._cleanup_session()
                    return False
                for cookie in response.cookies.values():
                    if cookie.key == "_qrcode_digest":
                        self._qrcode_digest = cookie.value
                        break
                if not self._qrcode_digest:
                    for cookie in self._session.cookie_jar:
                        if cookie.key == "_qrcode_digest":
                            self._qrcode_digest = cookie.value
                            break
                self.token = response_data.get("token")
                self._img_base64 = response_data.get("img")
                if not self._img_base64:
                    errors["base"] = "no_image_data"
                    await self._cleanup_session()
                    return False
                if not self._qrcode_digest or not self.token:
                    errors["base"] = "incomplete_auth"
                    self._img_base64 = None
                    self.token = None
                    self._qrcode_digest = None
                    await self._cleanup_session()
                    return False
                return True
        except (aiohttp.ClientError, TimeoutError) as err:
            _LOGGER.error("QR请求失败: %s", err)
            errors["base"] = "connection_error"
            await self._cleanup_session()
            return False
        except Exception as err:
            _LOGGER.error("QR未知错误: %s", err)
            errors["base"] = "unknown_error"
            await self._cleanup_session()
            return False

    async def _async_wait_qr_login(self) -> None:
        if not self._qrcode_digest or not self.token:
            raise QrLoginError("incomplete_auth")
        errors: dict[str, str] = {}
        if not await self._async_ensure_http(errors):
            raise QrLoginError(errors.get("base") or "session_recreate_failed")
        deadline = asyncio.get_running_loop().time() + QR_POLL_TIMEOUT
        headers = {
            "Content-Type": "application/json",
            "Cookie": f"_qrcode_digest={self._qrcode_digest}",
        }
        url = f"{QR_CODE_QUERY_URL}?token={self.token}"
        try:
            while asyncio.get_running_loop().time() < deadline:
                async with self._session.post(url, headers=headers) as response:
                    if response.status != 200:
                        raise QrLoginError("server_error")
                    try:
                        result = await response.json()
                    except aiohttp.ContentTypeError as err:
                        raise QrLoginError("invalid_response") from err
                    code = str(result.get("code") or "")
                    if code == "201":
                        await asyncio.sleep(QR_POLL_INTERVAL)
                        continue
                    if code != "200":
                        raise QrLoginError("unknown_error")
                    self.url = result.get("url")
                    if not self.url:
                        raise QrLoginError("no_redirect_url")
                    await self._async_finish_qr_auth()
                    return
            raise QrLoginError("scan_timeout")
        except QrLoginError:
            await self._cleanup_session()
            raise
        except asyncio.CancelledError:
            await self._cleanup_session()
            raise
        except (aiohttp.ClientError, TimeoutError, OSError) as err:
            _LOGGER.error("扫码轮询失败: %s", err)
            await self._cleanup_session()
            raise QrLoginError("connection_error") from err
        except Exception as err:
            _LOGGER.error("扫码轮询未知错误: %s", err)
            await self._cleanup_session()
            raise QrLoginError("unknown_error") from err

    async def _async_finish_qr_auth(self) -> None:
        assert self._session and self.url
        async with self._session.get(self.url, headers={"Cookie": "_122_gt_tag=1"}, allow_redirects=True) as second:
            if second.status != 200:
                raise QrLoginError("auth_failed")
            cookies = self._extract_auth_cookies(second)
            if not cookies.get("jsessionid") or not cookies.get("access_token"):
                raise QrLoginError("missing_cookies")
            account_name = f"{self._selected_province}账号"
            try:
                info = await fetch_violation_info(
                    self._session,
                    cookies["jsessionid"],
                    self._selected_province_code or "",
                )
                account_name = extract_account_name(info, account_name)
            except Exception:
                pass
            self._access_token = cookies["access_token"]
            self._jsessionid = cookies["jsessionid"]
            self._acw_tc = cookies.get("acw_tc") or ""
            self._keepalive_url = self.url
            self._account_name = account_name

    async def _async_qr_progress(self, step_id: str, done_step: str, retry_step: str):
        if self._qr_task is None:
            self._qr_task = self.hass.async_create_task(self._async_wait_qr_login())

        if not self._qr_task.done():
            return self.async_show_progress(
                step_id=step_id,
                progress_action="wait_scan",
                progress_task=self._qr_task,
                description_placeholders={"msg": self._qr_msg()},
            )

        try:
            await self._qr_task
        except QrLoginError as err:
            self._qr_task = None
            self._img_base64 = None
            self._qrcode_digest = None
            self.token = None
            self._last_qr_error = err.key
            return self.async_show_progress_done(next_step_id=retry_step)
        except asyncio.CancelledError:
            self._qr_task = None
            raise
        except Exception:
            self._qr_task = None
            self._img_base64 = None
            self._qrcode_digest = None
            self.token = None
            self._last_qr_error = "unknown_error"
            return self.async_show_progress_done(next_step_id=retry_step)

        self._qr_task = None
        return self.async_show_progress_done(next_step_id=done_step)

    async def async_step_next(self, user_input: dict[str, Any] | None = None):
        return await self._async_qr_progress("next", "vehicle", "next_retry")

    async def async_step_next_retry(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            self._jsessionid = None
            self._access_token = None
            self._acw_tc = ""
            self._keepalive_url = None
            self._img_base64 = None
            self._qrcode_digest = None
            self.token = None
            if not await self._async_fetch_qr(errors):
                return self._show_qr_form("next_retry", errors)
            return await self.async_step_next()
        if self._last_qr_error:
            errors = {"base": self._last_qr_error}
            self._last_qr_error = None
        return self._show_qr_form("next_retry", errors)

    def _extract_auth_cookies(self, response: aiohttp.ClientResponse) -> dict[str, str]:
        cookies = {"jsessionid": None, "access_token": None, "acw_tc": None}
        for redirect in response.history:
            for cookie in redirect.cookies.values():
                if cookie.key == "JSESSIONID-L":
                    cookies["jsessionid"] = cookie.value
                elif cookie.key == "accessToken":
                    cookies["access_token"] = cookie.value
                elif cookie.key == "acw_tc":
                    cookies["acw_tc"] = cookie.value
        for cookie in response.cookies.values():
            if cookie.key == "JSESSIONID-L" and not cookies["jsessionid"]:
                cookies["jsessionid"] = cookie.value
            elif cookie.key == "accessToken" and not cookies["access_token"]:
                cookies["access_token"] = cookie.value
            elif cookie.key == "acw_tc" and not cookies["acw_tc"]:
                cookies["acw_tc"] = cookie.value
        return cookies

    def _show_qr_form(self, step_id: str, errors: dict[str, str]):
        return self.async_show_form(
            step_id=step_id,
            description_placeholders={"msg": self._qr_msg(retry=bool(errors))},
            data_schema=vol.Schema({}),
            errors=errors,
        )

    async def async_step_vehicle(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            self._vehicle_index = int(user_input[CONF_VEHICLE_INDEX])
            if _12123_used(self.hass, self._selected_province_code or "", self._vehicle_index):
                errors["base"] = "vehicle_configured"
            else:
                plate = next(
                    (v["plate"] for v in self._vehicles if v["index"] == self._vehicle_index),
                    "我的车",
                )
                self._default_name = plate or "我的车"
                return await self._after_12123()
        if not self._vehicles and self._session and self._jsessionid and self._selected_province_code:
            raw = await fetch_vehicle_info(self._session, self._jsessionid, self._selected_province_code)
            self._vehicles = parse_vehicles(raw)
            await self._cleanup_session()
        if not self._vehicles:
            self._vehicles = [{"index": 1, "plate": "车辆1"}]
            errors["base"] = "no_vehicles"
        options = {str(v["index"]): v.get("plate") or f"车辆{v['index']}" for v in self._vehicles}
        return self.async_show_form(
            step_id="vehicle",
            data_schema=vol.Schema({vol.Required(CONF_VEHICLE_INDEX, default=list(options)[0]): vol.In(options)}),
            errors=errors,
        )

    async def async_step_stats(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            self._stats_options = _clean_stats(user_input)
            self._stats_plate = _plate_from_input(user_input)
            return await self.async_step_notify()
        defaults: dict[str, Any] = {CONF_NAME: self._default_name}
        plate = getattr(self, "_amap_data", {}).get(CONF_PLATE) or ""
        if plate:
            defaults[CONF_PLATE] = plate
        return self.async_show_form(
            step_id="stats",
            data_schema=_stats_schema(defaults),
        )

    async def async_step_notify(self, user_input: dict[str, Any] | None = None):
        include_12123 = self._enable_12123
        include_amap = self._enable_amap
        if user_input is not None:
            options = {
                **self._stats_options,
                **self._amap_options,
                **_clean_notify(user_input, include_12123=include_12123, include_amap=include_amap),
            }
            data: dict[str, Any] = {CONF_VEHICLE_INDEX: self._vehicle_index}
            if include_12123:
                plate_slug = slugify(self._default_name) or "car"
                unique = f"{self._selected_province_code}_{self._vehicle_index}_{plate_slug}"
                data.update(
                    {
                        CONF_ACCESS_TOKEN: self._access_token,
                        CONF_JSESSIONID: self._jsessionid,
                        CONF_ACW_TC: self._acw_tc,
                        CONF_SF: self._selected_province_code,
                        CONF_URL: self._keepalive_url,
                        CONF_ACCOUNT_NAME: self._account_name,
                        CONF_PROVINCE_NAME: self._selected_province,
                        CONF_LOGIN_AT: dt_util.now().isoformat(),
                    }
                )
            else:
                unique = f"local_{uuid.uuid4().hex}"
            if include_amap:
                data.update(self._amap_data)
                if not include_12123:
                    unique = f"amap_{self._amap_data[CONF_AMAP_TID]}"
                if _amap_tid_used(self.hass, self._amap_data[CONF_AMAP_TID]):
                    return self.async_abort(reason="amap_tid_configured")
            if include_12123 and _12123_used(
                self.hass, self._selected_province_code or "", self._vehicle_index
            ):
                return self.async_abort(reason="vehicle_configured")
            plate = getattr(self, "_stats_plate", "") or data.get(CONF_PLATE) or ""
            if plate:
                data[CONF_PLATE] = plate
            await self.async_set_unique_id(unique)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=options[CONF_NAME],
                data=data,
                options=options,
            )
        return self.async_show_form(
            step_id="notify",
            data_schema=_notify_schema({}, self.hass, include_12123=include_12123, include_amap=include_amap),
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]):
        entry = self._reauth_entry()
        if not entry or not entry.data.get(CONF_SF):
            return self.async_abort(reason="unknown_error")
        self._selected_province = entry.data.get(CONF_PROVINCE_NAME)
        self._selected_province_code = entry.data.get(CONF_SF)
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if not self._img_base64 and self._qr_task is None and not self._jsessionid:
            if not await self._async_fetch_qr(errors):
                return self._show_qr_form("reauth_confirm_retry", errors)
        return await self._async_qr_progress("reauth_confirm", "reauth_finish", "reauth_confirm_retry")

    async def async_step_reauth_confirm_retry(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            self._jsessionid = None
            self._access_token = None
            self._acw_tc = ""
            self._keepalive_url = None
            self._img_base64 = None
            self._qrcode_digest = None
            self.token = None
            if not await self._async_fetch_qr(errors):
                return self._show_qr_form("reauth_confirm_retry", errors)
            return await self.async_step_reauth_confirm()
        if self._last_qr_error:
            errors = {"base": self._last_qr_error}
            self._last_qr_error = None
        return self._show_qr_form("reauth_confirm_retry", errors)

    async def async_step_reauth_finish(self, user_input: dict[str, Any] | None = None):
        await self._cleanup_session()
        entry = self._reauth_entry()
        if not entry:
            return self.async_abort(reason="unknown_error")
        return self.async_update_reload_and_abort(
            entry,
            data={
                **entry.data,
                CONF_ACCESS_TOKEN: self._access_token,
                CONF_JSESSIONID: self._jsessionid,
                CONF_ACW_TC: self._acw_tc,
                CONF_URL: self._keepalive_url,
                CONF_LOGIN_AT: dt_util.now().isoformat(),
            },
        )

    async def _cleanup_session(self) -> None:
        if self._session:
            await self._session.close()
            self._session = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return CarStatsOptionsFlow()


class CarStatsOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        entry = self.config_entry
        has_12123 = bool(entry.data.get(CONF_SF))
        has_amap = bool(
            entry.data.get(CONF_AMAP_SESSIONID)
            and entry.data.get(CONF_AMAP_TID)
            and entry.data.get(CONF_AMAP_KEY)
            and entry.data.get(CONF_AMAP_PARAMDATA)
        )
        menu = ["stats", "notify"]
        if has_amap:
            menu.extend(["amap", "amap_session", "amap_unbind"])
        else:
            menu.append("amap_bind")
        if has_12123:
            menu.extend(["opt_12123", "unbind_12123"])
        else:
            menu.append("bind_12123")
        return self.async_show_menu(step_id="init", menu_options=menu)

    async def async_step_stats(self, user_input: dict[str, Any] | None = None):
        entry = self.config_entry
        if user_input is not None:
            options = _finalize_options(entry, _clean_stats(user_input), user_input)
            if not options.get(CONF_ODOMETER_ENTITY) and options.get(CONF_ODOMETER) is not None:
                store = self.hass.data.get(DOMAIN, {}).get("store")
                if store:
                    await store.set_odometer(entry.entry_id, float(options[CONF_ODOMETER]))
            data = {**entry.data, CONF_PLATE: _plate_from_input(user_input)}
            self.hass.config_entries.async_update_entry(entry, data=data)
            return self.async_create_entry(title=options[CONF_NAME], data=options)
        current = {**entry.data, **entry.options}
        if not current.get(CONF_ODOMETER_ENTITY):
            store = self.hass.data.get(DOMAIN, {}).get("store")
            if store:
                stored_odo = store.get(entry.entry_id).get("odometer") or 0
                if stored_odo:
                    current[CONF_ODOMETER] = stored_odo
        return self.async_show_form(step_id="stats", data_schema=_stats_schema(current))

    async def async_step_notify(self, user_input: dict[str, Any] | None = None):
        entry = self.config_entry
        has_12123 = bool(entry.data.get(CONF_SF))
        has_amap = bool(
            entry.data.get(CONF_AMAP_SESSIONID)
            and entry.data.get(CONF_AMAP_TID)
            and entry.data.get(CONF_AMAP_KEY)
            and entry.data.get(CONF_AMAP_PARAMDATA)
        )
        if user_input is not None:
            options = _finalize_options(
                entry,
                _clean_notify(user_input, include_12123=has_12123, include_amap=has_amap),
                user_input,
            )
            return self.async_create_entry(title="", data=options)
        current = {**entry.data, **entry.options}
        return self.async_show_form(
            step_id="notify",
            data_schema=_notify_schema(current, self.hass, include_12123=has_12123, include_amap=has_amap),
        )

    async def async_step_opt_12123(self, user_input: dict[str, Any] | None = None):
        return self.async_show_menu(
            step_id="opt_12123",
            menu_options=["opt_12123_index", "opt_12123_relogin", "opt_12123_logout"],
        )

    async def async_step_opt_12123_index(self, user_input: dict[str, Any] | None = None):
        entry = self.config_entry
        if user_input is not None:
            idx = int(user_input[CONF_VEHICLE_INDEX])
            if _12123_used(self.hass, entry.data.get(CONF_SF) or "", idx, exclude_entry_id=entry.entry_id):
                return self.async_show_form(
                    step_id="opt_12123_index",
                    data_schema=vol.Schema(
                        {
                            vol.Required(CONF_VEHICLE_INDEX, default=idx): selector.NumberSelector(
                                selector.NumberSelectorConfig(min=1, max=20, step=1, mode=selector.NumberSelectorMode.BOX)
                            )
                        }
                    ),
                    errors={"base": "vehicle_configured"},
                )
            data = {**entry.data, CONF_VEHICLE_INDEX: idx}
            self.hass.config_entries.async_update_entry(entry, data=data)
            return self.async_create_entry(title="", data=dict(entry.options))
        return self.async_show_form(
            step_id="opt_12123_index",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_VEHICLE_INDEX, default=int(entry.data.get(CONF_VEHICLE_INDEX, 1))): selector.NumberSelector(
                        selector.NumberSelectorConfig(min=1, max=20, step=1, mode=selector.NumberSelectorMode.BOX)
                    )
                }
            ),
        )

    async def async_step_opt_12123_relogin(self, user_input: dict[str, Any] | None = None):
        entry = self.config_entry
        if user_input is not None:
            coordinator = self.hass.data.get(DOMAIN, {}).get(entry.entry_id)
            if coordinator:
                coordinator.reset_reauth()
                coordinator.request_reauth()
            return self.async_create_entry(title="", data=dict(entry.options))
        return self.async_show_form(step_id="opt_12123_relogin", data_schema=vol.Schema({}))

    async def async_step_opt_12123_logout(self, user_input: dict[str, Any] | None = None):
        entry = self.config_entry
        if user_input is not None:
            coordinator = self.hass.data.get(DOMAIN, {}).get(entry.entry_id)
            if coordinator:
                await coordinator.async_logout_12123()
            return self.async_create_entry(title="", data=dict(entry.options))
        return self.async_show_form(step_id="opt_12123_logout", data_schema=vol.Schema({}))

    async def async_step_amap(self, user_input: dict[str, Any] | None = None):
        entry = self.config_entry
        current = {**entry.data, **entry.options}
        if user_input is not None:
            options = _options_base(entry)
            owners = user_input.get(CONF_OWNERS) or []
            if isinstance(owners, str):
                owners = [owners] if owners.strip() else []
            owners = [str(o).strip() for o in owners if str(o).strip()]
            if not owners:
                return self.async_show_form(
                    step_id="amap",
                    data_schema=self._amap_options_schema(current),
                    errors={CONF_OWNERS: "required"},
                )
            options[CONF_OWNERS] = owners
            options[CONF_POLL_ACTIVE] = int(user_input.get(CONF_POLL_ACTIVE, DEFAULT_POLL_ACTIVE))
            if user_input.get(CONF_POLL_EXCLUDE_ZONES):
                options[CONF_POLL_EXCLUDE_ZONES] = user_input[CONF_POLL_EXCLUDE_ZONES]
            else:
                options.pop(CONF_POLL_EXCLUDE_ZONES, None)
            options[CONF_ADDRESSAPI] = "gaode"
            if user_input.get(CONF_ADDRESSAPI_KEY):
                options[CONF_ADDRESSAPI_KEY] = user_input[CONF_ADDRESSAPI_KEY]
            else:
                options.pop(CONF_ADDRESSAPI_KEY, None)
            if user_input.get(CONF_PRIVATE_KEY):
                options[CONF_PRIVATE_KEY] = user_input[CONF_PRIVATE_KEY]
            else:
                options.pop(CONF_PRIVATE_KEY, None)
            options[CONF_ADDRESS_DISTANCE] = int(user_input.get(CONF_ADDRESS_DISTANCE, DEFAULT_ADDRESS_DISTANCE))
            options[CONF_COMMUTE_SPEED] = float(user_input.get(CONF_COMMUTE_SPEED, DEFAULT_COMMUTE_SPEED))
            options[CONF_COMMUTE_INTERVAL] = int(user_input.get(CONF_COMMUTE_INTERVAL, DEFAULT_COMMUTE_INTERVAL))
            if CONF_COMMUTE_ZONE in user_input:
                if user_input.get(CONF_COMMUTE_ZONE):
                    options[CONF_COMMUTE_ZONE] = user_input[CONF_COMMUTE_ZONE]
                else:
                    options.pop(CONF_COMMUTE_ZONE, None)
            data = {**entry.data}
            self.hass.config_entries.async_update_entry(entry, data=data, options=options)
            return self.async_create_entry(title="", data=options)
        return self.async_show_form(step_id="amap", data_schema=self._amap_options_schema(current))

    def _amap_options_schema(self, current: dict[str, Any]) -> vol.Schema:
        owners = current.get(CONF_OWNERS) or []
        fields: dict[Any, Any] = {
            vol.Required(CONF_OWNERS, default=owners): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="person", multiple=True)
            ),
            vol.Required(CONF_POLL_ACTIVE, default=current.get(CONF_POLL_ACTIVE, DEFAULT_POLL_ACTIVE)): selector.NumberSelector(
                selector.NumberSelectorConfig(min=1, max=180, step=1, unit_of_measurement=UNIT_MIN, mode=selector.NumberSelectorMode.BOX)
            ),
        }
        excl = current.get(CONF_POLL_EXCLUDE_ZONES)
        excl_key = vol.Optional(CONF_POLL_EXCLUDE_ZONES, default=excl) if excl else vol.Optional(CONF_POLL_EXCLUDE_ZONES)
        fields[excl_key] = selector.EntitySelector(selector.EntitySelectorConfig(domain="zone", multiple=True))
        key = current.get(CONF_ADDRESSAPI_KEY)
        key_f = vol.Optional(CONF_ADDRESSAPI_KEY, default=key) if key else vol.Optional(CONF_ADDRESSAPI_KEY)
        fields[key_f] = _PWD_SELECTOR
        pk = current.get(CONF_PRIVATE_KEY)
        pk_f = vol.Optional(CONF_PRIVATE_KEY, default=pk) if pk else vol.Optional(CONF_PRIVATE_KEY)
        fields[pk_f] = _PWD_SELECTOR
        fields[
            vol.Required(CONF_ADDRESS_DISTANCE, default=current.get(CONF_ADDRESS_DISTANCE, DEFAULT_ADDRESS_DISTANCE))
        ] = selector.NumberSelector(
            selector.NumberSelectorConfig(min=10, max=5000, step=10, unit_of_measurement=UNIT_M, mode=selector.NumberSelectorMode.BOX)
        )
        zone = current.get(CONF_COMMUTE_ZONE)
        zone_f = vol.Optional(CONF_COMMUTE_ZONE, default=zone) if zone else vol.Optional(CONF_COMMUTE_ZONE)
        fields[zone_f] = selector.EntitySelector(selector.EntitySelectorConfig(domain="zone", multiple=True))
        fields[
            vol.Required(CONF_COMMUTE_SPEED, default=current.get(CONF_COMMUTE_SPEED, DEFAULT_COMMUTE_SPEED))
        ] = selector.NumberSelector(
            selector.NumberSelectorConfig(min=1, max=200, step=1, unit_of_measurement=UNIT_KMH, mode=selector.NumberSelectorMode.BOX)
        )
        fields[
            vol.Required(CONF_COMMUTE_INTERVAL, default=current.get(CONF_COMMUTE_INTERVAL, DEFAULT_COMMUTE_INTERVAL))
        ] = selector.NumberSelector(
            selector.NumberSelectorConfig(min=1, max=120, step=1, unit_of_measurement=UNIT_MIN, mode=selector.NumberSelectorMode.BOX)
        )
        return vol.Schema(fields)

    async def async_step_amap_session(self, user_input: dict[str, Any] | None = None):
        entry = self.config_entry
        errors: dict[str, str] = {}
        if user_input is not None:
            key = str(user_input.get(CONF_AMAP_KEY) or "").strip()
            sid = str(user_input.get(CONF_AMAP_SESSIONID) or "").strip().rstrip(";")
            pdata = str(user_input.get(CONF_AMAP_PARAMDATA) or "").strip()
            if not key or not sid or not pdata:
                errors["base"] = "amap_auth_failed"
            else:
                try:
                    cars = await self.hass.async_add_executor_job(probe_amap_cars, key, sid, pdata)
                except Exception:
                    cars = []
                cars = [c for c in cars if isinstance(c, dict) and str(c.get("tid") or "").strip()]
                tids = {str(c.get("tid")) for c in cars}
                if not cars:
                    errors["base"] = "amap_auth_failed"
                elif str(entry.data.get(CONF_AMAP_TID) or "") not in tids:
                    errors["base"] = "amap_no_cars"
                else:
                    data = {
                        **entry.data,
                        CONF_AMAP_KEY: key,
                        CONF_AMAP_SESSIONID: sid,
                        CONF_AMAP_PARAMDATA: pdata,
                        CONF_AMAP_LOGIN_AT: dt_util.now().isoformat(),
                    }
                    self.hass.config_entries.async_update_entry(entry, data=data)
                    return self.async_create_entry(title="", data=dict(entry.options))
        return self.async_show_form(
            step_id="amap_session",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_AMAP_KEY, default=entry.data.get(CONF_AMAP_KEY, "")): _PWD_SELECTOR,
                    vol.Required(CONF_AMAP_SESSIONID, default=entry.data.get(CONF_AMAP_SESSIONID, "")): selector.TextSelector(),
                    vol.Required(CONF_AMAP_PARAMDATA, default=entry.data.get(CONF_AMAP_PARAMDATA, "")): selector.TextSelector(
                        selector.TextSelectorConfig(multiline=True)
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_amap_bind(self, user_input: dict[str, Any] | None = None):
        entry = self.config_entry
        errors: dict[str, str] = {}
        if user_input is not None:
            key = str(user_input.get(CONF_AMAP_KEY) or "").strip()
            sid = str(user_input.get(CONF_AMAP_SESSIONID) or "").strip().rstrip(";")
            pdata = str(user_input.get(CONF_AMAP_PARAMDATA) or "").strip()
            owners = user_input.get(CONF_OWNERS) or []
            if isinstance(owners, str):
                owners = [owners] if owners.strip() else []
            owners = [str(o).strip() for o in owners if str(o).strip()]
            if not key or not sid or not pdata:
                errors["base"] = "amap_auth_failed"
            elif not owners:
                errors[CONF_OWNERS] = "required"
            else:
                try:
                    cars = await self.hass.async_add_executor_job(probe_amap_cars, key, sid, pdata)
                except Exception:
                    cars = []
                if not cars:
                    errors["base"] = "amap_no_cars"
                else:
                    cars = [c for c in cars if isinstance(c, dict) and str(c.get("tid") or "").strip()]
                    if not cars:
                        errors["base"] = "amap_no_cars"
                    else:
                        self._bind_auth = {CONF_AMAP_KEY: key, CONF_AMAP_SESSIONID: sid, CONF_AMAP_PARAMDATA: pdata}
                        self._bind_owners = owners
                        self._bind_poll = int(user_input.get(CONF_POLL_ACTIVE, DEFAULT_POLL_ACTIVE))
                        self._bind_cars = cars
                        return await self.async_step_amap_bind_car()
        return self.async_show_form(
            step_id="amap_bind",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_AMAP_KEY): _PWD_SELECTOR,
                    vol.Required(CONF_AMAP_SESSIONID): selector.TextSelector(),
                    vol.Required(CONF_AMAP_PARAMDATA): selector.TextSelector(selector.TextSelectorConfig(multiline=True)),
                    vol.Required(CONF_OWNERS): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="person", multiple=True)
                    ),
                    vol.Required(CONF_POLL_ACTIVE, default=DEFAULT_POLL_ACTIVE): selector.NumberSelector(
                        selector.NumberSelectorConfig(min=1, max=180, step=1, unit_of_measurement=UNIT_MIN, mode=selector.NumberSelectorMode.BOX)
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_amap_bind_car(self, user_input: dict[str, Any] | None = None):
        entry = self.config_entry
        options_map = _amap_car_options(getattr(self, "_bind_cars", []))
        if not options_map:
            return self.async_abort(reason="amap_no_cars")
        if user_input is not None:
            tid = str(user_input[CONF_AMAP_TID])
            if _amap_tid_used(self.hass, tid, exclude_entry_id=entry.entry_id):
                return self.async_show_form(
                    step_id="amap_bind_car",
                    data_schema=vol.Schema({vol.Required(CONF_AMAP_TID, default=list(options_map)[0]): vol.In(options_map)}),
                    errors={"base": "amap_tid_configured"},
                )
            plate = _plate_from_amap_cars(getattr(self, "_bind_cars", []), tid) or entry.data.get(CONF_PLATE) or ""
            data = {
                **entry.data,
                CONF_AMAP_KEY: self._bind_auth[CONF_AMAP_KEY],
                CONF_AMAP_SESSIONID: self._bind_auth[CONF_AMAP_SESSIONID],
                CONF_AMAP_PARAMDATA: self._bind_auth[CONF_AMAP_PARAMDATA],
                CONF_AMAP_TID: tid,
                CONF_PLATE: plate,
                CONF_AMAP_LOGIN_AT: dt_util.now().isoformat(),
            }
            options = dict(entry.options)
            options[CONF_OWNERS] = self._bind_owners
            options[CONF_POLL_ACTIVE] = self._bind_poll
            self.hass.config_entries.async_update_entry(entry, data=data, options=options)
            return self.async_create_entry(title="", data=options)
        return self.async_show_form(
            step_id="amap_bind_car",
            data_schema=vol.Schema({vol.Required(CONF_AMAP_TID, default=list(options_map)[0]): vol.In(options_map)}),
        )

    async def async_step_amap_unbind(self, user_input: dict[str, Any] | None = None):
        entry = self.config_entry
        if user_input is not None:
            data = {
                k: v
                for k, v in entry.data.items()
                if k
                not in (
                    CONF_AMAP_KEY,
                    CONF_AMAP_SESSIONID,
                    CONF_AMAP_PARAMDATA,
                    CONF_AMAP_TID,
                    CONF_AMAP_LOGIN_AT,
                )
            }
            options = dict(entry.options)
            for key in (
                CONF_OWNERS,
                CONF_POLL_ACTIVE,
                CONF_POLL_EXCLUDE_ZONES,
                CONF_ADDRESSAPI,
                CONF_ADDRESSAPI_KEY,
                CONF_PRIVATE_KEY,
                CONF_ADDRESS_DISTANCE,
                CONF_COMMUTE_ZONE,
                CONF_COMMUTE_SPEED,
                CONF_COMMUTE_INTERVAL,
                CONF_NOTIFY_LEAVE,
                CONF_NOTIFY_ARRIVE,
            ):
                options.pop(key, None)
            self.hass.config_entries.async_update_entry(entry, data=data, options=options)
            from homeassistant.helpers.storage import Store

            try:
                await Store(self.hass, 1, f"{DOMAIN}_amap_{slugify(entry.entry_id)}").async_remove()
            except Exception:
                pass
            return self.async_create_entry(title="", data=options)
        return self.async_show_form(step_id="amap_unbind", data_schema=vol.Schema({}))

    async def async_step_unbind_12123(self, user_input: dict[str, Any] | None = None):
        entry = self.config_entry
        if user_input is not None:
            data = {
                k: v
                for k, v in entry.data.items()
                if k
                not in (
                    CONF_ACCESS_TOKEN,
                    CONF_JSESSIONID,
                    CONF_ACW_TC,
                    CONF_SF,
                    CONF_URL,
                    CONF_LOGIN_AT,
                    CONF_ACCOUNT_NAME,
                    CONF_PROVINCE_NAME,
                )
            }
            data[CONF_VEHICLE_INDEX] = 1
            options = dict(entry.options)
            options[CONF_NOTIFY_VIOLATION] = False
            options[CONF_NOTIFY_INSPECT] = False
            options[CONF_NOTIFY_LICENSE] = False
            store = self.hass.data.get(DOMAIN, {}).get("store")
            if store:
                prev = store.snapshot(entry.entry_id)
                await store.save_snapshot(
                    entry.entry_id,
                    {
                        "vehicle": {},
                        "license": {},
                        "violations": {"count": 0, "records": []},
                        "inputs": dict(prev.get("inputs") or {}),
                        "session": {"logged_in": False, "message": "已解绑12123", "error": None},
                        "next_ok": {},
                        "paused": False,
                        "jsessionid": None,
                        "vehicle_index": 1,
                    },
                )
            self.hass.config_entries.async_update_entry(entry, data=data)
            return self.async_create_entry(title="", data=options)
        return self.async_show_form(step_id="unbind_12123", data_schema=vol.Schema({}))

    async def async_step_bind_12123(self, user_input: dict[str, Any] | None = None):
        self._bind_vehicles: list[dict[str, Any]] = []
        self._bind_province: str | None = None
        self._bind_province_code: str | None = None
        self._bind_session: aiohttp.ClientSession | None = None
        self._bind_qrcode_digest: str | None = None
        self._bind_token: str | None = None
        self._bind_img: str | None = None
        self._bind_url: str | None = None
        self._bind_access_token: str | None = None
        self._bind_jsessionid: str | None = None
        self._bind_acw_tc: str = ""
        self._bind_keepalive_url: str | None = None
        self._bind_account_name: str = ""
        self._bind_vehicle_index: int = 1
        self._bind_qr_task: asyncio.Task | None = None
        self._bind_last_qr_error: str | None = None
        return await self.async_step_bind_province()

    async def async_step_bind_province(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            self._bind_province = user_input["province"]
            self._bind_province_code = PROVINCE_CODE_MAPPING[self._bind_province]
            if not await self._bind_fetch_qr(errors):
                return self.async_show_form(
                    step_id="bind_province",
                    data_schema=vol.Schema({vol.Required("province"): vol.In(PROVINCES)}),
                    errors=errors,
                )
            return await self.async_step_bind_next()
        return self.async_show_form(
            step_id="bind_province",
            data_schema=vol.Schema({vol.Required("province"): vol.In(PROVINCES)}),
            errors=errors,
        )

    def _bind_qr_msg(self, *, retry: bool = False) -> str:
        if self._bind_img:
            tip = "点击下方提交重新获取二维码。" if retry else "请扫码；转圈表示等待确认，成功后自动继续。"
            return (
                f"![12123登录二维码](data:image/png;base64,{self._bind_img})\n\n"
                "**请使用12123手机App扫描上方二维码。**\n\n"
                f"{tip}"
            )
        return "二维码未加载，请点击提交重试。"

    async def _bind_ensure_http(self, errors: dict[str, str]) -> bool:
        if self._bind_session and not self._bind_session.closed:
            return True
        try:
            ssl_context = await self.hass.async_add_executor_job(create_ssl_context)
            self._bind_session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
                connector=aiohttp.TCPConnector(ssl=ssl_context, force_close=True, enable_cleanup_closed=True),
            )
            return True
        except Exception:
            errors["base"] = "session_recreate_failed"
            return False

    async def _bind_cleanup(self) -> None:
        if self._bind_session:
            await self._bind_session.close()
            self._bind_session = None

    async def _bind_fetch_qr(self, errors: dict[str, str]) -> bool:
        if not await self._bind_ensure_http(errors):
            return False
        self._bind_qrcode_digest = None
        self._bind_token = None
        self._bind_img = None
        try:
            async with self._bind_session.get(QR_CODE_API_URL) as response:
                if response.status != 200:
                    errors["base"] = "server_error"
                    await self._bind_cleanup()
                    return False
                try:
                    response_data = await response.json()
                except aiohttp.ContentTypeError:
                    errors["base"] = "invalid_response"
                    await self._bind_cleanup()
                    return False
                for cookie in response.cookies.values():
                    if cookie.key == "_qrcode_digest":
                        self._bind_qrcode_digest = cookie.value
                        break
                if not self._bind_qrcode_digest:
                    for cookie in self._bind_session.cookie_jar:
                        if cookie.key == "_qrcode_digest":
                            self._bind_qrcode_digest = cookie.value
                            break
                self._bind_token = response_data.get("token")
                self._bind_img = response_data.get("img")
                if not self._bind_img or not self._bind_qrcode_digest or not self._bind_token:
                    errors["base"] = "incomplete_auth"
                    await self._bind_cleanup()
                    return False
                return True
        except Exception:
            errors["base"] = "connection_error"
            await self._bind_cleanup()
            return False

    async def _bind_wait_qr(self) -> None:
        if not self._bind_qrcode_digest or not self._bind_token:
            raise QrLoginError("incomplete_auth")
        errors: dict[str, str] = {}
        if not await self._bind_ensure_http(errors):
            raise QrLoginError(errors.get("base") or "session_recreate_failed")
        deadline = asyncio.get_running_loop().time() + QR_POLL_TIMEOUT
        headers = {"Content-Type": "application/json", "Cookie": f"_qrcode_digest={self._bind_qrcode_digest}"}
        url = f"{QR_CODE_QUERY_URL}?token={self._bind_token}"
        try:
            while asyncio.get_running_loop().time() < deadline:
                async with self._bind_session.post(url, headers=headers) as response:
                    if response.status != 200:
                        raise QrLoginError("server_error")
                    result = await response.json()
                    code = str(result.get("code") or "")
                    if code == "201":
                        await asyncio.sleep(QR_POLL_INTERVAL)
                        continue
                    if code != "200":
                        raise QrLoginError("unknown_error")
                    self._bind_url = result.get("url")
                    if not self._bind_url:
                        raise QrLoginError("no_redirect_url")
                    async with self._bind_session.get(
                        self._bind_url, headers={"Cookie": "_122_gt_tag=1"}, allow_redirects=True
                    ) as second:
                        if second.status != 200:
                            raise QrLoginError("auth_failed")
                        cookies = {"jsessionid": None, "access_token": None, "acw_tc": None}
                        for redirect in second.history:
                            for cookie in redirect.cookies.values():
                                if cookie.key == "JSESSIONID-L":
                                    cookies["jsessionid"] = cookie.value
                                elif cookie.key == "accessToken":
                                    cookies["access_token"] = cookie.value
                                elif cookie.key == "acw_tc":
                                    cookies["acw_tc"] = cookie.value
                        for cookie in second.cookies.values():
                            if cookie.key == "JSESSIONID-L" and not cookies["jsessionid"]:
                                cookies["jsessionid"] = cookie.value
                            elif cookie.key == "accessToken" and not cookies["access_token"]:
                                cookies["access_token"] = cookie.value
                            elif cookie.key == "acw_tc" and not cookies["acw_tc"]:
                                cookies["acw_tc"] = cookie.value
                        if not cookies.get("jsessionid") or not cookies.get("access_token"):
                            raise QrLoginError("missing_cookies")
                        account_name = f"{self._bind_province}账号"
                        try:
                            info = await fetch_violation_info(
                                self._bind_session, cookies["jsessionid"], self._bind_province_code or ""
                            )
                            account_name = extract_account_name(info, account_name)
                        except Exception:
                            pass
                        self._bind_access_token = cookies["access_token"]
                        self._bind_jsessionid = cookies["jsessionid"]
                        self._bind_acw_tc = cookies.get("acw_tc") or ""
                        self._bind_keepalive_url = self._bind_url
                        self._bind_account_name = account_name
                    return
            raise QrLoginError("scan_timeout")
        except QrLoginError:
            await self._bind_cleanup()
            raise
        except Exception as err:
            await self._bind_cleanup()
            raise QrLoginError("connection_error") from err

    async def async_step_bind_next(self, user_input: dict[str, Any] | None = None):
        if self._bind_qr_task is None:
            self._bind_qr_task = self.hass.async_create_task(self._bind_wait_qr())
        if not self._bind_qr_task.done():
            return self.async_show_progress(
                step_id="bind_next",
                progress_action="wait_scan",
                progress_task=self._bind_qr_task,
                description_placeholders={"msg": self._bind_qr_msg()},
            )
        try:
            await self._bind_qr_task
        except QrLoginError as err:
            self._bind_qr_task = None
            self._bind_img = None
            self._bind_last_qr_error = err.key
            return self.async_show_progress_done(next_step_id="bind_next_retry")
        except Exception:
            self._bind_qr_task = None
            self._bind_last_qr_error = "unknown_error"
            return self.async_show_progress_done(next_step_id="bind_next_retry")
        self._bind_qr_task = None
        return self.async_show_progress_done(next_step_id="bind_vehicle")

    async def async_step_bind_next_retry(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            self._bind_jsessionid = None
            self._bind_access_token = None
            self._bind_img = None
            if not await self._bind_fetch_qr(errors):
                return self.async_show_form(
                    step_id="bind_next_retry",
                    description_placeholders={"msg": self._bind_qr_msg(retry=True)},
                    data_schema=vol.Schema({}),
                    errors=errors,
                )
            return await self.async_step_bind_next()
        if self._bind_last_qr_error:
            errors = {"base": self._bind_last_qr_error}
            self._bind_last_qr_error = None
        return self.async_show_form(
            step_id="bind_next_retry",
            description_placeholders={"msg": self._bind_qr_msg(retry=bool(errors))},
            data_schema=vol.Schema({}),
            errors=errors,
        )

    async def async_step_bind_vehicle(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            self._bind_vehicle_index = int(user_input[CONF_VEHICLE_INDEX])
            entry = self.config_entry
            if _12123_used(self.hass, self._bind_province_code or "", self._bind_vehicle_index, exclude_entry_id=entry.entry_id):
                errors["base"] = "vehicle_configured"
            else:
                await self._bind_cleanup()
                data = {
                    **entry.data,
                    CONF_ACCESS_TOKEN: self._bind_access_token,
                    CONF_JSESSIONID: self._bind_jsessionid,
                    CONF_ACW_TC: self._bind_acw_tc,
                    CONF_SF: self._bind_province_code,
                    CONF_URL: self._bind_keepalive_url,
                    CONF_ACCOUNT_NAME: self._bind_account_name,
                    CONF_PROVINCE_NAME: self._bind_province,
                    CONF_VEHICLE_INDEX: self._bind_vehicle_index,
                    CONF_LOGIN_AT: dt_util.now().isoformat(),
                }
                options = dict(entry.options)
                self.hass.config_entries.async_update_entry(entry, data=data, options=options)
                return self.async_create_entry(title="", data=options)
        if not self._bind_vehicles and self._bind_session and self._bind_jsessionid and self._bind_province_code:
            raw = await fetch_vehicle_info(self._bind_session, self._bind_jsessionid, self._bind_province_code)
            self._bind_vehicles = parse_vehicles(raw)
            await self._bind_cleanup()
        if not self._bind_vehicles:
            self._bind_vehicles = [{"index": 1, "plate": "车辆1"}]
            errors["base"] = "no_vehicles"
        options = {str(v["index"]): v.get("plate") or f"车辆{v['index']}" for v in self._bind_vehicles}
        return self.async_show_form(
            step_id="bind_vehicle",
            data_schema=vol.Schema({vol.Required(CONF_VEHICLE_INDEX, default=list(options)[0]): vol.In(options)}),
            errors=errors,
        )
