"""ha_xiaomi_cloud integration."""
from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceEntryType

from .account import XiaomiAccount
from .DataUpdateCoordinator import XiaomiCloudDataUpdateCoordinator
from .const import (
    CONF_MAX_INTERVAL,
    CONF_DEVICE_ID,
    CONF_PASS_TOKEN,
    CONF_UPDATE_INTERVAL,
    CONF_USER_ID,
    DOMAIN,
    INTEGRATION_HUB_SUFFIX,
    INTEGRATION_MANUFACTURER,
    PLATFORMS,
    default_options,
)

ATTR_ACCOUNT = "account"
ATTR_DEVICE_NAME = "device_name"
ATTR_IMEI = "imei"
ATTR_LOST_DEVICE_MESSAGE = "message"
ATTR_LOST_DEVICE_NUMBER = "phone"
ATTR_TEXT = "text"

SERVICE_PLAY_SOUND = "play_sound"
SERVICE_FIND_DEVICE = "find_device"
SERVICE_LOST_DEVICE = "lost_device"
SERVICE_CLIPBOARD = "clipboard"
SERVICE_UPDATE = "update"

CONFIG_SCHEMA = cv.removed(DOMAIN, raise_if_present=False)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})

    username = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]

    if entry.unique_id is None:
        hass.config_entries.async_update_entry(entry, unique_id=username)

    defaults = default_options()
    update_interval = entry.options.get(
        CONF_MAX_INTERVAL,
        entry.options.get(
            CONF_UPDATE_INTERVAL,
            entry.data.get(CONF_UPDATE_INTERVAL, defaults[CONF_UPDATE_INTERVAL]),
        ),
    )
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, f"{entry.unique_id or username}{INTEGRATION_HUB_SUFFIX}")},
        manufacturer=INTEGRATION_MANUFACTURER,
        name="小米云服务",
        model="ha_xiaomi_cloud",
        entry_type=DeviceEntryType.SERVICE,
        configuration_url="https://i.mi.com/",
    )

    coordinator = XiaomiCloudDataUpdateCoordinator(
        hass,
        username,
        password,
        update_interval,
        pass_token=entry.data.get(CONF_PASS_TOKEN),
        user_id=entry.data.get(CONF_USER_ID),
        device_id=entry.data.get(CONF_DEVICE_ID),
    )

    account = XiaomiAccount(hass, entry, coordinator)
    await account.async_setup()

    if coordinator.token_updated:
        tokens = coordinator.export_tokens()
        hass.config_entries.async_update_entry(
            entry,
            data={
                **entry.data,
                CONF_PASS_TOKEN: tokens.get("pass_token"),
                CONF_USER_ID: tokens.get("user_id"),
                CONF_DEVICE_ID: tokens.get("device_id"),
            },
        )

    if not coordinator.last_update_success and not account.devices:
        from homeassistant.exceptions import ConfigEntryNotReady

        raise ConfigEntryNotReady("无法从小米云服务获取数据")

    hass.data[DOMAIN][entry.unique_id] = account
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _register_services(hass)
    return True


def _register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_UPDATE):
        return

    async def async_update_account(service: ServiceCall) -> None:
        account_id = service.data.get(ATTR_ACCOUNT)
        if account_id is None:
            for account in hass.data.get(DOMAIN, {}).values():
                await account.async_keep_alive(force_locate=True)
            return
        account = _get_account(hass, account_id)
        await account.async_keep_alive(force_locate=True)

    async def async_play_sound(service: ServiceCall) -> None:
        account = _get_account(hass, service.data[ATTR_ACCOUNT])
        imei = _resolve_imei(account, service.data)
        await account.async_play_sound(imei)

    async def async_find_device(service: ServiceCall) -> None:
        account = _get_account(hass, service.data[ATTR_ACCOUNT])
        imei = _resolve_imei(account, service.data)
        await account.async_find_device(imei)

    async def async_lost_device(service: ServiceCall) -> None:
        account = _get_account(hass, service.data[ATTR_ACCOUNT])
        imei = _resolve_imei(account, service.data)
        await account.async_lost_device(
            imei,
            service.data.get(ATTR_LOST_DEVICE_NUMBER, ""),
            service.data.get(ATTR_LOST_DEVICE_MESSAGE, ""),
            service.data.get("onlinenotify", True),
        )

    async def async_clipboard(service: ServiceCall) -> None:
        account = _get_account(hass, service.data[ATTR_ACCOUNT])
        await account.async_send_clipboard(service.data.get(ATTR_TEXT, ""))

    hass.services.async_register(
        DOMAIN,
        SERVICE_UPDATE,
        async_update_account,
        schema=vol.Schema({vol.Optional(ATTR_ACCOUNT): cv.string}),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_PLAY_SOUND,
        async_play_sound,
        schema=vol.All(
            vol.Schema(
                {
                    vol.Required(ATTR_ACCOUNT): cv.string,
                    vol.Optional(ATTR_IMEI): cv.string,
                    vol.Optional(ATTR_DEVICE_NAME): cv.string,
                }
            ),
            cv.has_at_least_one_key(ATTR_IMEI, ATTR_DEVICE_NAME),
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_FIND_DEVICE,
        async_find_device,
        schema=vol.All(
            vol.Schema(
                {
                    vol.Required(ATTR_ACCOUNT): cv.string,
                    vol.Optional(ATTR_IMEI): cv.string,
                    vol.Optional(ATTR_DEVICE_NAME): cv.string,
                }
            ),
            cv.has_at_least_one_key(ATTR_IMEI, ATTR_DEVICE_NAME),
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_LOST_DEVICE,
        async_lost_device,
        schema=vol.All(
            vol.Schema(
                {
                    vol.Required(ATTR_ACCOUNT): cv.string,
                    vol.Optional(ATTR_IMEI): cv.string,
                    vol.Optional(ATTR_DEVICE_NAME): cv.string,
                vol.Optional(ATTR_LOST_DEVICE_NUMBER): cv.string,
                vol.Optional(ATTR_LOST_DEVICE_MESSAGE): cv.string,
                vol.Optional("onlinenotify"): cv.boolean,
            }
            ),
            cv.has_at_least_one_key(ATTR_IMEI, ATTR_DEVICE_NAME),
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_CLIPBOARD,
        async_clipboard,
        schema=vol.Schema(
            {
                vol.Required(ATTR_ACCOUNT): cv.string,
                vol.Required(ATTR_TEXT): cv.string,
            }
        ),
    )


def _get_account(hass: HomeAssistant, account_identifier: str) -> XiaomiAccount:
    domain_data = hass.data.get(DOMAIN)
    if not domain_data:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="no_account_configured",
        )
    account = domain_data.get(account_identifier)
    if account is None:
        for item in domain_data.values():
            if item.username == account_identifier:
                account = item
                break
    if account is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="account_not_found",
            translation_placeholders={"account": account_identifier},
        )
    return account


def _resolve_imei(account: XiaomiAccount, data: dict) -> str:
    if imei := data.get(ATTR_IMEI):
        return imei
    device_name = data.get(ATTR_DEVICE_NAME)
    if device_name:
        for device in account.devices.values():
            if device.name == device_name or device.object_slug == device_name:
                return device.imei
    raise ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="device_required",
    )


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.unique_id, None)
        if not hass.data[DOMAIN]:
            hass.data.pop(DOMAIN)
            for service in (
                SERVICE_PLAY_SOUND,
                SERVICE_FIND_DEVICE,
                SERVICE_LOST_DEVICE,
                SERVICE_CLIPBOARD,
                SERVICE_UPDATE,
            ):
                if hass.services.has_service(DOMAIN, service):
                    hass.services.async_remove(DOMAIN, service)
    return unload_ok
