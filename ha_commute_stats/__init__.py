from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_HOME_ZONES,
    CONF_PEOPLE,
    CONF_PERSON,
    CONF_WORK_ENABLED,
    CONF_WORK_ZONES,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import HomeTimeCoordinator
from .work_coordinator import WorkTimeCoordinator

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

_WORK_ENTITIES = (
    ("sensor", "work_duration"),
    ("sensor", "work_time"),
    ("sensor", "over_time"),
    ("sensor", "work_state"),
    ("switch", "work"),
    ("number", "comp_time"),
    ("number", "month_salary"),
    ("datetime", "work_start_time"),
    ("datetime", "work_end_time"),
)


def _expected_unique_ids(entry: ConfigEntry) -> set[str]:
    eid = entry.entry_id
    expected = {
        f"{eid}_sensor_home_count",
        f"{eid}_sensor_comp_count",
        f"{eid}_sensor_waidi_count",
        f"{eid}_sensor_out_count",
    }
    for person in entry.options.get(CONF_PEOPLE) or []:
        tracker = person.get(CONF_PERSON)
        if not tracker:
            continue
        expected.add(f"{eid}_sensor_activity_{tracker}")
        if person.get(CONF_HOME_ZONES):
            expected.add(f"{eid}_sensor_home_duration_{tracker}")
            expected.add(f"{eid}_switch_home_{tracker}")
        if person.get(CONF_WORK_ENABLED) and person.get(CONF_WORK_ZONES):
            for domain, key in _WORK_ENTITIES:
                expected.add(f"{eid}_{tracker}_{domain}_{key}")
    return expected


def _async_cleanup_orphans(hass: HomeAssistant, entry: ConfigEntry) -> None:
    people = entry.options.get(CONF_PEOPLE) or []
    keep_devices = {entry.entry_id}
    for person in people:
        tracker = person.get(CONF_PERSON)
        if tracker:
            keep_devices.add(f"{entry.entry_id}_{tracker}")

    device_reg = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(device_reg, entry.entry_id):
        idents = {ident for domain, ident in device.identifiers if domain == DOMAIN}
        if idents and not idents.intersection(keep_devices):
            device_reg.async_remove_device(device.id)

    expected = _expected_unique_ids(entry)
    entity_reg = er.async_get(hass)
    for ent in er.async_entries_for_config_entry(entity_reg, entry.entry_id):
        if ent.unique_id not in expected:
            entity_reg.async_remove(ent.entity_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})
    home = HomeTimeCoordinator(hass, entry)
    await home.async_setup()
    work: dict[str, WorkTimeCoordinator] = {}
    for person in entry.options.get(CONF_PEOPLE) or []:
        if not person.get(CONF_WORK_ENABLED):
            continue
        if not person.get(CONF_PERSON) or not person.get(CONF_WORK_ZONES):
            continue
        coord = WorkTimeCoordinator(hass, entry, person)
        await coord.async_setup()
        work[person[CONF_PERSON]] = coord
    hass.data[DOMAIN][entry.entry_id] = {"home": home, "work": work}
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _async_cleanup_orphans(hass, entry)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        data = hass.data[DOMAIN].pop(entry.entry_id)
        home: HomeTimeCoordinator = data["home"]
        await home.async_shutdown()
        for coord in data.get("work", {}).values():
            await coord.async_shutdown()
        if not hass.data[DOMAIN]:
            hass.data.pop(DOMAIN)
    return unload_ok
