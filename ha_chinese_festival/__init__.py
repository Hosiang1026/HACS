from __future__ import annotations

import logging
from pathlib import Path
import time
import uuid

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import (
    ALMANAC_KEYS,
    CONF_ANNIVERSARIES,
    CONF_BIRTHDAYS,
    CONF_INTENT_ENABLED,
    CONF_LEGAL,
    CONF_LICENSES,
    DEFAULT_INTENT_ENABLED,
    DOMAIN,
    NEXT_OBJECT_IDS,
    PLATFORMS,
)
from .coordinator import HolidayDailyCoordinator
from .festival_engine import (
    default_anniversaries,
    default_birthdays,
    default_licenses,
)
from .intent import async_setup_intents
from .services import async_setup_services, async_unload_services

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

_SEED_VERSION = 3
_ITEM_KEYS = (CONF_LICENSES, CONF_ANNIVERSARIES, CONF_BIRTHDAYS, CONF_LEGAL)

_EXPECTED = {
    "sensor_chinese_festival",
    "sensor_license_expiry",
    "sensor_day_type",
    "sensor_solar_date",
    "sensor_weekday",
    "sensor_astro",
    "sensor_lunar_date",
    "sensor_year_day",
    "sensor_festival_count",
    "sensor_license_count",
    "sensor_birthday_count",
    "sensor_anniversary_count",
    "sensor_love_days",
    "sensor_holiday_plan",
    "binary_sensor_is_holiday",
    "binary_sensor_is_repair",
    "date_chinese_festival_tap",
    "sensor_ai_fortune",
} | {f"sensor_{oid}" for oid in NEXT_OBJECT_IDS.values()} | {
    f"sensor_{k}" for k in ALMANAC_KEYS
}


def _async_fix_entity_ids(hass: HomeAssistant, entry: ConfigEntry) -> None:
    entity_reg = er.async_get(hass)
    prefix = f"{entry.entry_id}_"
    for ent in list(er.async_entries_for_config_entry(entity_reg, entry.entry_id)):
        if not ent.unique_id.startswith(prefix):
            continue
        rest = ent.unique_id[len(prefix) :]
        new_eid = None
        for domain in ("binary_sensor", "sensor", "date"):
            head = f"{domain}_"
            if rest.startswith(head):
                new_eid = f"{domain}.{rest[len(head) :]}"
                break
        if new_eid and ent.entity_id != new_eid:
            try:
                entity_reg.async_update_entity(ent.entity_id, new_entity_id=new_eid)
            except ValueError:
                pass


def _ensure_item_ids(options: dict) -> tuple[dict, bool]:
    changed = False
    for key in _ITEM_KEYS:
        items = options.get(key)
        if not isinstance(items, list):
            options[key] = []
            changed = True
            continue
        new_items = []
        for item in items:
            if not isinstance(item, dict):
                changed = True
                continue
            row = dict(item)
            if not row.get("id"):
                row["id"] = str(uuid.uuid4())
                changed = True
            new_items.append(row)
        options[key] = new_items
    return options, changed


def _async_cleanup_orphans(hass: HomeAssistant, entry: ConfigEntry) -> None:
    expected = {f"{entry.entry_id}_{x}" for x in _EXPECTED}
    entity_reg = er.async_get(hass)
    for ent in er.async_entries_for_config_entry(entity_reg, entry.entry_id):
        if ent.unique_id not in expected:
            entity_reg.async_remove(ent.entity_id)
    device_reg = dr.async_get(hass)
    keep = {entry.entry_id}
    for device in dr.async_entries_for_config_entry(device_reg, entry.entry_id):
        idents = {ident for domain, ident in device.identifiers if domain == DOMAIN}
        if idents and not idents.intersection(keep):
            device_reg.async_remove_device(device.id)


async def _async_register_lovelace(hass: HomeAssistant) -> None:
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get("lovelace_registered"):
        return
    www = Path(__file__).parent / "www"
    if not www.is_dir():
        return
    try:
        await hass.http.async_register_static_paths(
            [StaticPathConfig("/ha_chinese_festival_files", str(www), False)]
        )
        add_extra_js_url(
            hass,
            f"/ha_chinese_festival_files/chinese-festival-card.js?ver={int(time.time())}",
        )
        domain_data["lovelace_registered"] = True
    except Exception:
        _LOGGER.debug("lovelace card register skipped", exc_info=True)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    await _async_register_lovelace(hass)
    await async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})
    await _async_register_lovelace(hass)
    await async_setup_services(hass)
    options = dict(entry.options)
    changed = False
    if options.get("seed_version") != _SEED_VERSION:
        if not options.get(CONF_LICENSES):
            options[CONF_LICENSES] = await hass.async_add_executor_job(default_licenses)
            changed = True
        if not options.get(CONF_ANNIVERSARIES):
            options[CONF_ANNIVERSARIES] = await hass.async_add_executor_job(
                default_anniversaries
            )
            changed = True
        if not options.get(CONF_BIRTHDAYS):
            options[CONF_BIRTHDAYS] = await hass.async_add_executor_job(default_birthdays)
            changed = True
        if int(options.get("seed_version") or 0) < 3:
            options[CONF_LEGAL] = []
            changed = True
        options["seed_version"] = _SEED_VERSION
        changed = True
    options, id_changed = _ensure_item_ids(options)
    if changed or id_changed:
        hass.config_entries.async_update_entry(entry, options=options)
    coordinator = HolidayDailyCoordinator(hass, entry)
    await coordinator.async_setup()
    hass.data[DOMAIN][entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _async_fix_entity_ids(hass, entry)
    _async_cleanup_orphans(hass, entry)
    opts = {**entry.data, **entry.options}
    if bool(opts.get(CONF_INTENT_ENABLED, DEFAULT_INTENT_ENABLED)):
        await async_setup_intents(hass)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: HolidayDailyCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_shutdown()
        remain = [
            k
            for k in hass.data.get(DOMAIN, {})
            if k not in ("lovelace_registered", "_services_registered", "_intents_registered")
            and not str(k).startswith("_")
        ]
        if not remain:
            await async_unload_services(hass)
            hass.data.pop(DOMAIN, None)
    return unload_ok
