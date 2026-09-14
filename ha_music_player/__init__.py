from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from .player import RuntimePlayer

from .const import CONF_MUSIC_PATH, DOMAIN, PLATFORMS
from .http import (
    ConfigView,
    StateView,
    CoverView,
    FileView,
    LibraryView,
    LyricView,
    PlayUrlView,
    ScanView,
)
from .library import MusicLibrary


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})
    if entry.unique_id != DOMAIN:
        hass.config_entries.async_update_entry(entry, unique_id=DOMAIN)
    conf = {**entry.data, **entry.options}
    library = MusicLibrary(hass, conf[CONF_MUSIC_PATH])
    await library.load()
    player = RuntimePlayer(hass, entry, library)
    hass.data[DOMAIN][entry.entry_id] = True
    hass.data[DOMAIN]["runtime"] = {"library": library, "player": player}

    if not hass.data[DOMAIN].get("views"):
        hass.http.register_view(LibraryView())
        hass.http.register_view(ConfigView())
        hass.http.register_view(ScanView())
        hass.http.register_view(FileView())
        hass.http.register_view(CoverView())
        hass.http.register_view(LyricView())
        hass.http.register_view(PlayUrlView())
        hass.data[DOMAIN]["views"] = True

    if not hass.data[DOMAIN].get("state_view"):
        hass.http.register_view(StateView())
        hass.data[DOMAIN]["state_view"] = True

    async def handle_scan(_call: ServiceCall) -> None:
        await hass.data[DOMAIN]["runtime"]["library"].async_scan()

    if hass.services.has_service(DOMAIN, "scan"):
        hass.services.async_remove(DOMAIN, "scan")
    hass.services.async_register(DOMAIN, "scan", handle_scan)
    entry.async_on_unload(entry.add_update_listener(_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if hass.services.has_service(DOMAIN, "scan"):
        hass.services.async_remove(DOMAIN, "scan")
    hass.data[DOMAIN].pop(entry.entry_id, None)
    hass.data[DOMAIN].pop("runtime", None)
    return ok
