"""The iCloud component."""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

import voluptuous as vol

_path = str(Path(__file__).resolve().parent)
if _path not in sys.path:
    sys.path.insert(0, _path)

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.storage import Store
from homeassistant.util import slugify

from .account import IcloudAccount
from .const import (
    CONF_MAX_INTERVAL,
    CONF_WITH_FAMILY,
    DEFAULT_MAX_INTERVAL,
    DEFAULT_WITH_FAMILY,
    DOMAIN,
    INTEGRATION_HUB_SUFFIX,
    INTEGRATION_MANUFACTURER,
    PLATFORMS,
    STORAGE_KEY,
    STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)

ATTRIBUTION = "Data provided by Apple iCloud"

ATTR_ACCOUNT_FETCH_INTERVAL = "account_fetch_interval"
ATTR_BATTERY = "battery"
ATTR_BATTERY_STATUS = "battery_status"
ATTR_DEVICE_NAME = "device_name"
ATTR_DEVICE_STATUS = "device_status"
ATTR_LOW_POWER_MODE = "low_power_mode"
ATTR_OWNER_NAME = "owner_fullname"

SERVICE_ICLOUD_PLAY_SOUND = "play_sound"
SERVICE_ICLOUD_DISPLAY_MESSAGE = "display_message"
SERVICE_ICLOUD_LOST_DEVICE = "lost_device"
SERVICE_ICLOUD_UPDATE = "update"
ATTR_ACCOUNT = "account"
ATTR_LOST_DEVICE_MESSAGE = "message"
ATTR_LOST_DEVICE_NUMBER = "number"
ATTR_LOST_DEVICE_SOUND = "sound"

SERVICE_SCHEMA = vol.Schema({vol.Optional(ATTR_ACCOUNT): cv.string})

SERVICE_SCHEMA_PLAY_SOUND = vol.Schema(
    {vol.Required(ATTR_ACCOUNT): cv.string, vol.Required(ATTR_DEVICE_NAME): cv.string}
)

SERVICE_SCHEMA_DISPLAY_MESSAGE = vol.Schema(
    {
        vol.Required(ATTR_ACCOUNT): cv.string,
        vol.Required(ATTR_DEVICE_NAME): cv.string,
        vol.Required(ATTR_LOST_DEVICE_MESSAGE): cv.string,
        vol.Optional(ATTR_LOST_DEVICE_SOUND): cv.boolean,
    }
)

SERVICE_SCHEMA_LOST_DEVICE = vol.Schema(
    {
        vol.Required(ATTR_ACCOUNT): cv.string,
        vol.Required(ATTR_DEVICE_NAME): cv.string,
        vol.Required(ATTR_LOST_DEVICE_NUMBER): cv.string,
        vol.Required(ATTR_LOST_DEVICE_MESSAGE): cv.string,
    }
)

CONFIG_SCHEMA = cv.removed(DOMAIN, raise_if_present=False)

HaIcloudCnConfigEntry = ConfigEntry[IcloudAccount]


def _iter_accounts(hass: HomeAssistant) -> list[IcloudAccount]:
    return [
        entry.runtime_data
        for entry in hass.config_entries.async_entries(DOMAIN)
        if getattr(entry, "runtime_data", None) is not None
    ]


def _get_account(hass: HomeAssistant, account_identifier: str) -> IcloudAccount:
    accounts = _iter_accounts(hass)
    if not accounts:
        raise ServiceValidationError("No iCloud accounts configured")
    for account in accounts:
        if account.username == account_identifier:
            return account
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.unique_id == account_identifier and entry.runtime_data is not None:
            return entry.runtime_data
    raise ServiceValidationError(
        f"No iCloud account with username or name {account_identifier}"
    )


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up the iCloud component and register services."""

    async def async_play_sound(service: ServiceCall) -> None:
        account_id = service.data[ATTR_ACCOUNT]
        device_name = slugify(service.data[ATTR_DEVICE_NAME].replace(" ", "", 99))
        icloud_account = _get_account(hass, account_id)
        await hass.async_add_executor_job(_run_play_sound, icloud_account, device_name)

    async def async_display_message(service: ServiceCall) -> None:
        account_id = service.data[ATTR_ACCOUNT]
        device_name = slugify(service.data[ATTR_DEVICE_NAME].replace(" ", "", 99))
        message = service.data[ATTR_LOST_DEVICE_MESSAGE]
        sound = service.data.get(ATTR_LOST_DEVICE_SOUND, False)
        icloud_account = _get_account(hass, account_id)
        await hass.async_add_executor_job(
            _run_display_message, icloud_account, device_name, message, sound
        )

    async def async_lost_device(service: ServiceCall) -> None:
        account_id = service.data[ATTR_ACCOUNT]
        device_name = slugify(service.data[ATTR_DEVICE_NAME].replace(" ", "", 99))
        number = service.data[ATTR_LOST_DEVICE_NUMBER]
        message = service.data[ATTR_LOST_DEVICE_MESSAGE]
        icloud_account = _get_account(hass, account_id)
        await hass.async_add_executor_job(
            _run_lost_device, icloud_account, device_name, number, message
        )

    async def async_update_account(service: ServiceCall) -> None:
        if (account_id := service.data.get(ATTR_ACCOUNT)) is None:
            accounts = _iter_accounts(hass)
            if not accounts:
                raise ServiceValidationError("No iCloud accounts configured")
            await hass.async_add_executor_job(_run_update_all, accounts)
        else:
            icloud_account = _get_account(hass, account_id)
            await icloud_account.async_keep_alive(force_locate=True)

    def _run_play_sound(account: IcloudAccount, device_name: str) -> None:
        for device in account.get_devices_with_name(device_name):
            device.play_sound()

    def _run_display_message(
        account: IcloudAccount, device_name: str, message: str, sound: bool
    ) -> None:
        for device in account.get_devices_with_name(device_name):
            device.display_message(message, sound)

    def _run_lost_device(
        account: IcloudAccount, device_name: str, number: str, message: str
    ) -> None:
        for device in account.get_devices_with_name(device_name):
            device.lost_device(number, message)

    def _run_update_all(accounts: list[IcloudAccount]) -> None:
        for account in accounts:
            account.keep_alive(force_locate=True)

    hass.services.async_register(
        DOMAIN,
        SERVICE_ICLOUD_PLAY_SOUND,
        async_play_sound,
        schema=SERVICE_SCHEMA_PLAY_SOUND,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_ICLOUD_DISPLAY_MESSAGE,
        async_display_message,
        schema=SERVICE_SCHEMA_DISPLAY_MESSAGE,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_ICLOUD_LOST_DEVICE,
        async_lost_device,
        schema=SERVICE_SCHEMA_LOST_DEVICE,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_ICLOUD_UPDATE,
        async_update_account,
        schema=SERVICE_SCHEMA,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: HaIcloudCnConfigEntry) -> bool:
    """Set up an iCloud account from a config entry."""
    username = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]
    with_family = entry.data.get(CONF_WITH_FAMILY, DEFAULT_WITH_FAMILY)
    max_interval = entry.options.get(
        CONF_MAX_INTERVAL, entry.data.get(CONF_MAX_INTERVAL, DEFAULT_MAX_INTERVAL)
    )

    if entry.unique_id is None:
        hass.config_entries.async_update_entry(entry, unique_id=username)

    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, f"{entry.unique_id or username}{INTEGRATION_HUB_SUFFIX}")},
        manufacturer=INTEGRATION_MANUFACTURER,
        name="ha_icloud_cn",
        model="ha_icloud_cn",
        entry_type=DeviceEntryType.SERVICE,
        configuration_url="https://www.icloud.com.cn/",
    )

    icloud_dir = Store[Any](hass, STORAGE_VERSION, STORAGE_KEY)

    account = IcloudAccount(
        hass,
        username,
        password,
        icloud_dir,
        with_family,
        max_interval,
        entry,
    )
    await hass.async_add_executor_job(account.setup)

    entry.runtime_data = account
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_reload_entry(hass: HomeAssistant, entry: HaIcloudCnConfigEntry) -> None:
    """Reload config entry."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: HaIcloudCnConfigEntry) -> bool:
    """Unload a config entry."""
    account = entry.runtime_data
    account._shutdown = True
    account._cancel_polling()
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await hass.async_add_executor_job(account.shutdown)
    else:
        account._shutdown = False
        if not account._reauth_in_progress():
            account._schedule_polling(account.fetch_interval)
    return unload_ok
