from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_change,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util
import voluptuous as vol

from .amap_coordinator import AmapGpsCoordinator
from .const import (
    CONF_AMAP_KEY,
    CONF_AMAP_PARAMDATA,
    CONF_AMAP_SESSIONID,
    CONF_AMAP_TID,
    CONF_JSESSIONID,
    CONF_MAINT_DATE,
    CONF_MAINT_ODO,
    CONF_VEHICLE_INDEX,
    DOMAIN,
    GET_KEEPALIVE_INTERVAL,
)
from .coordinator import CarStatsCoordinator
from .helpers import (
    cfg_12123,
    cfg_amap,
    cfg_fuel_price_entity,
    cfg_insurance_expiry,
    cfg_inspect_expiry,
    cfg_maint_date,
    cfg_maint_km,
    cfg_odometer,
    cfg_odometer_entity,
    cfg_purchase_date,
    cfg_battery_replace_date,
)
from .store import CarStatsStore

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.NUMBER, Platform.BUTTON, Platform.TEXT, Platform.DEVICE_TRACKER]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})
    if "store" not in hass.data[DOMAIN]:
        store = CarStatsStore(hass)
        await store.async_load()
        hass.data[DOMAIN]["store"] = store
    else:
        store = hass.data[DOMAIN]["store"]

    if not cfg_odometer_entity(entry):
        cfg_odo = cfg_odometer(entry)
        stored = float(store.get(entry.entry_id).get("odometer") or 0)
        if cfg_odo is not None and cfg_odo > 0 and stored <= 0:
            await store.set_odometer(entry.entry_id, cfg_odo)

    coordinator = CarStatsCoordinator(hass, entry, store)
    await coordinator.async_setup()
    coordinator.amap_coordinator = None
    if cfg_amap(entry):
        amap = AmapGpsCoordinator(hass, entry)
        amap.setup_owner_tracking()
        await amap.async_refresh()
        coordinator.amap_coordinator = amap
    hass.data[DOMAIN][entry.entry_id] = coordinator
    entry.async_on_unload(store.async_add_listener(coordinator.async_push))

    registry = er.async_get(hass)
    tracked: list[str] = []
    for eid in (cfg_odometer_entity(entry), cfg_fuel_price_entity(entry)):
        if not eid:
            continue
        ent = registry.async_get(eid)
        if ent and ent.config_entry_id == entry.entry_id:
            continue
        tracked.append(eid)

    async def _external_entity_updated(_) -> None:
        coordinator.push()

    if tracked:
        entry.async_on_unload(
            async_track_state_change_event(hass, tracked, _external_entity_updated)
        )

    unsub_daily = async_track_time_change(hass, coordinator.async_daily_notify, hour=0, minute=0, second=0)
    entry.async_on_unload(unsub_daily)
    unsub_yearly = async_track_time_change(
        hass, coordinator.async_check_yearly, hour=[0, 8, 12, 18], minute=0, second=0
    )
    entry.async_on_unload(unsub_yearly)
    if cfg_12123(entry):
        unsub_keep = async_track_time_interval(hass, coordinator.async_keepalive, GET_KEEPALIVE_INTERVAL)
        entry.async_on_unload(unsub_keep)
        entry.async_on_unload(coordinator.async_shutdown_session)
        hass.async_create_task(coordinator.async_keepalive())
    entry.async_on_unload(entry.add_update_listener(_on_entry_update))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _register_services(hass)
    return True


def _entry_data_changed(old: ConfigEntry, new: ConfigEntry) -> bool:
    if cfg_amap(old) != cfg_amap(new) or cfg_12123(old) != cfg_12123(new):
        return True
    if old.data.get(CONF_JSESSIONID) != new.data.get(CONF_JSESSIONID):
        return True
    if old.data.get(CONF_VEHICLE_INDEX) != new.data.get(CONF_VEHICLE_INDEX):
        return True
    for key in (CONF_AMAP_KEY, CONF_AMAP_SESSIONID, CONF_AMAP_PARAMDATA, CONF_AMAP_TID):
        if old.data.get(key) != new.data.get(key):
            return True
    return False


def _entry_options_need_reload(old: ConfigEntry, new: ConfigEntry) -> bool:
    def _flags(entry: ConfigEntry) -> tuple[bool, ...]:
        return (
            cfg_purchase_date(entry) is not None,
            cfg_battery_replace_date(entry) is not None,
            cfg_insurance_expiry(entry) is not None,
            cfg_inspect_expiry(entry) is not None,
            cfg_maint_date(entry) is not None,
        )

    return _flags(old) != _flags(new)


async def _on_entry_update(hass: HomeAssistant, entry: ConfigEntry) -> None:
    entry = hass.config_entries.async_get_entry(entry.entry_id) or entry
    coordinator: CarStatsCoordinator | None = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator is None:
        await hass.config_entries.async_reload(entry.entry_id)
        return
    old = coordinator.entry
    if _entry_data_changed(old, entry) or _entry_options_need_reload(old, entry):
        await hass.config_entries.async_reload(entry.entry_id)
        return
    coordinator.entry = entry
    amap = coordinator.amap_coordinator
    if amap:
        amap.apply_entry(entry)
    coordinator._load_snapshot()
    coordinator.push()
    if amap:
        await amap.async_request_refresh()


async def _reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await _on_entry_update(hass, entry)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        remaining = [k for k in hass.data.get(DOMAIN, {}) if k not in ("store", "services")]
        if not remaining and hass.data[DOMAIN].get("services"):
            for service in ("add_refuel", "add_expense", "add_maintenance", "set_odometer"):
                hass.services.async_remove(DOMAIN, service)
            hass.data[DOMAIN]["services"] = False
    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    store: CarStatsStore | None = hass.data.get(DOMAIN, {}).get("store")
    if not store:
        store = CarStatsStore(hass)
        await store.async_load()
        hass.data.setdefault(DOMAIN, {})["store"] = store
    await store.remove_entry(entry.entry_id)
    from homeassistant.helpers.storage import Store
    from homeassistant.util import slugify

    try:
        await Store(hass, 1, f"{DOMAIN}_amap_{slugify(entry.entry_id)}").async_remove()
    except Exception:
        pass


def _entry_id_from_call(hass: HomeAssistant, call: ServiceCall) -> str | None:
    device_ids = call.data.get("device_id")
    if device_ids:
        if isinstance(device_ids, list):
            device_ids = device_ids[0]
        device = dr.async_get(hass).async_get(device_ids)
        if device and device.config_entries:
            domain_data = hass.data.get(DOMAIN, {})
            for cid in device.config_entries:
                if cid in domain_data and cid not in ("store", "services"):
                    return cid
        return None
    if call.data.get("entry_id"):
        entry_id = call.data["entry_id"]
        if entry_id in hass.data.get(DOMAIN, {}):
            return entry_id
        return None
    entries = [k for k in hass.data.get(DOMAIN, {}) if k not in ("store", "services")]
    return entries[0] if len(entries) == 1 else None


def _require_entry(hass: HomeAssistant, call: ServiceCall) -> str:
    entry_id = _entry_id_from_call(hass, call)
    if not entry_id:
        raise ServiceValidationError("请指定 device_id 或 entry_id（多车时必填）")
    return entry_id


def _register_services(hass: HomeAssistant) -> None:
    if hass.data[DOMAIN].get("services"):
        return
    hass.data[DOMAIN]["services"] = True

    async def _add_refuel(call: ServiceCall) -> None:
        entry_id = _require_entry(hass, call)
        coordinator: CarStatsCoordinator = hass.data[DOMAIN][entry_id]
        liters = float(call.data.get("liters") or 0)
        cost = float(call.data.get("cost") or 0)
        price = coordinator.current_price()
        if liters <= 0 and cost > 0 and price > 0:
            liters = round(cost / price, 2)
        if cost <= 0 and liters > 0 and price > 0:
            cost = round(liters * price, 2)
        if liters <= 0 and cost <= 0:
            raise ServiceValidationError("请填写升数或金额")
        update_odometer = call.data.get("odometer") is not None
        odo = float(call.data["odometer"]) if update_odometer else coordinator.current_odometer()
        full = bool(call.data.get("full", True))
        station = str(call.data.get("station") or "").strip()
        await coordinator.store.add_refuel(
            entry_id, odo, liters, cost, price, full, station, update_odometer=update_odometer and odo > 0
        )
        if update_odometer and odo > 0:
            coordinator.inputs["odometer"] = odo
            await coordinator.async_persist_snapshot()
        coordinator.push()

    async def _add_expense(call: ServiceCall) -> None:
        entry_id = _require_entry(hass, call)
        coordinator: CarStatsCoordinator = hass.data[DOMAIN][entry_id]
        await coordinator.store.add_expense(entry_id, call.data.get("type") or "other", float(call.data.get("amount") or 0))

    async def _add_maintenance(call: ServiceCall) -> None:
        entry_id = _require_entry(hass, call)
        coordinator: CarStatsCoordinator = hass.data[DOMAIN][entry_id]
        entry = coordinator.entry
        odo = float(call.data.get("odometer") or coordinator.current_odometer())
        await coordinator.store.add_maintenance(
            entry_id,
            odo,
            call.data.get("type") or "常规",
            float(call.data.get("cost") or 0),
            odo + cfg_maint_km(entry),
            None,
        )
        options = dict(entry.options)
        options[CONF_MAINT_DATE] = dt_util.now().date().isoformat()
        options[CONF_MAINT_ODO] = odo
        hass.config_entries.async_update_entry(entry, options=options)

    async def _set_odometer(call: ServiceCall) -> None:
        entry_id = _require_entry(hass, call)
        coordinator: CarStatsCoordinator = hass.data[DOMAIN][entry_id]
        if cfg_odometer_entity(coordinator.entry):
            raise ServiceValidationError("已配置外部里程实体，请修改该实体")
        odo = float(call.data["odometer"])
        coordinator.inputs["odometer"] = odo
        await coordinator.store.set_odometer(entry_id, odo)
        await coordinator.async_persist_snapshot()
        coordinator.push()

    hass.services.async_register(
        DOMAIN,
        "add_refuel",
        _add_refuel,
        schema=vol.Schema(
            {
                vol.Optional("device_id"): vol.Any(str, [str]),
                vol.Optional("entry_id"): str,
                vol.Optional("liters"): vol.Coerce(float),
                vol.Optional("cost"): vol.Coerce(float),
                vol.Optional("odometer"): vol.Coerce(float),
                vol.Optional("full"): bool,
                vol.Optional("station"): str,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        "add_expense",
        _add_expense,
        schema=vol.Schema(
            {
                vol.Optional("device_id"): vol.Any(str, [str]),
                vol.Optional("entry_id"): str,
                vol.Required("type"): str,
                vol.Required("amount"): vol.Coerce(float),
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        "add_maintenance",
        _add_maintenance,
        schema=vol.Schema(
            {
                vol.Optional("device_id"): vol.Any(str, [str]),
                vol.Optional("entry_id"): str,
                vol.Optional("odometer"): vol.Coerce(float),
                vol.Optional("type"): str,
                vol.Optional("cost"): vol.Coerce(float),
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        "set_odometer",
        _set_odometer,
        schema=vol.Schema(
            {
                vol.Optional("device_id"): vol.Any(str, [str]),
                vol.Optional("entry_id"): str,
                vol.Required("odometer"): vol.Coerce(float),
            }
        ),
    )
