"""Config flow to configure the iCloud integration."""
from __future__ import annotations

from collections.abc import Mapping
import logging
import os
import sys
from pathlib import Path
from typing import Any

_path = str(Path(__file__).resolve().parent)
if _path not in sys.path:
    sys.path.insert(0, _path)

from pyicloud import PyiCloudService
from pyicloud.exceptions import (
    PyiCloud2FARequiredException,
    PyiCloud2SARequiredException,
    PyiCloudAuthRequiredException,
    PyiCloudException,
    PyiCloudFailedLoginException,
    PyiCloudNoDevicesException,
    PyiCloudServiceNotActivatedException,
    PyiCloudServiceUnavailable,
)
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import SOURCE_USER, ConfigFlow, ConfigFlowResult
from homeassistant.core import callback
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers import selector
from homeassistant.helpers.storage import Store

from .const import (
    CONF_ACTIVITY_ENTITY,
    CONF_AMAP_KEY,
    CONF_COMMUTE_ENABLED,
    CONF_COMMUTE_ZONES,
    CONF_MAX_INTERVAL,
    CONF_OFFPEAK_ENABLED,
    CONF_OFFPEAK_INTERVAL,
    CONF_OFFPEAK_WINDOWS,
    CONF_PEAK_ENABLED,
    CONF_PEAK_INTERVAL,
    CONF_PEAK_WINDOWS,
    CONF_PERIOD_WEEKDAYS,
    CONF_WITH_FAMILY,
    DEFAULT_ACTIVITY_ENTITY,
    DEFAULT_COMMUTE_ENABLED,
    DEFAULT_COMMUTE_ZONES,
    DEFAULT_MAX_INTERVAL,
    DEFAULT_OFFPEAK_ENABLED,
    DEFAULT_OFFPEAK_INTERVAL,
    DEFAULT_OFFPEAK_WINDOWS,
    DEFAULT_PEAK_ENABLED,
    DEFAULT_PEAK_INTERVAL,
    DEFAULT_PEAK_WINDOWS,
    DEFAULT_PERIOD_WEEKDAYS,
    DEFAULT_WITH_FAMILY,
    DOMAIN,
    OFFPEAK_RANGE_COUNT,
    PEAK_RANGE_COUNT,
    STORAGE_KEY,
    STORAGE_VERSION,
    TIME_CHOICES,
    TIME_NONE,
    activity_entities,
    opt_windows_text,
    pairs_to_windows_text,
    windows_text_to_pairs,
)
from .session_storage import clear_session_files

CONF_TRUSTED_DEVICE = "trusted_device"
CONF_VERIFICATION_CODE = "verification_code"

_LOGGER = logging.getLogger(__name__)

_PASSWORD_SELECTOR = selector.TextSelector(
    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
)


class IcloudFlowHandler(ConfigFlow, domain=DOMAIN):
    """Handle a iCloud config flow."""

    VERSION = 1

    def __init__(self):
        """Initialize iCloud config flow."""
        self.api = None
        self._username = None
        self._password = None
        self._with_family = None
        self._max_interval = None

        self._trusted_device = None
        self._verification_code = None

        self._existing_entry_data = None
        self._description_placeholders = None

    def _storage_path(self) -> str:
        return Store(self.hass, STORAGE_VERSION, STORAGE_KEY).path

    def _clear_session_files(self) -> None:
        if self._username:
            clear_session_files(self._storage_path(), self._username)

    async def _async_release_api(self) -> None:
        api = self.api
        self.api = None
        if api is None or api._devices is None:
            return
        devices = api._devices
        devices.stop_event.set()
        monitor = devices._monitor
        if monitor is not None and monitor.is_alive():
            await self.hass.async_add_executor_job(monitor.join, 30)

    def _show_setup_form(self, user_input=None, errors=None, step_id="user"):
        """Show the setup form to the user."""

        if user_input is None:
            user_input = {}

        if step_id == "user":
            schema = {
                vol.Required(
                    CONF_USERNAME, default=user_input.get(CONF_USERNAME, "")
                ): str,
                vol.Required(
                    CONF_PASSWORD, default=user_input.get(CONF_PASSWORD, "")
                ): _PASSWORD_SELECTOR,
                vol.Optional(
                    CONF_WITH_FAMILY,
                    default=user_input.get(CONF_WITH_FAMILY, DEFAULT_WITH_FAMILY),
                ): bool,
                vol.Required(
                    CONF_MAX_INTERVAL,
                    default=user_input.get(CONF_MAX_INTERVAL, DEFAULT_MAX_INTERVAL),
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=180)),
            }
        else:
            schema = {
                vol.Required(
                    CONF_PASSWORD, default=user_input.get(CONF_PASSWORD, "")
                ): _PASSWORD_SELECTOR,
            }

        return self.async_show_form(
            step_id=step_id,
            data_schema=vol.Schema(schema),
            errors=errors or {},
            description_placeholders=self._description_placeholders,
        )

    async def _validate_and_create_entry(self, user_input, step_id):
        """Check if config is valid and create entry if so."""
        self._password = user_input[CONF_PASSWORD]

        extra_inputs = user_input

        # If an existing entry was found, meaning this is a password update attempt,
        # use those to get config values that aren't changing
        if self._existing_entry_data:
            extra_inputs = self._existing_entry_data

        self._username = extra_inputs[CONF_USERNAME]
        self._with_family = user_input.get(
            CONF_WITH_FAMILY, extra_inputs.get(CONF_WITH_FAMILY, DEFAULT_WITH_FAMILY)
        )
        self._max_interval = user_input.get(
            CONF_MAX_INTERVAL, extra_inputs.get(CONF_MAX_INTERVAL, DEFAULT_MAX_INTERVAL)
        )

        # Check if already configured
        if self.unique_id is None:
            await self.async_set_unique_id(self._username)
            self._abort_if_unique_id_configured()

        await self._async_release_api()
        try:
            self.api = await self._login()
        except PyiCloudFailedLoginException as error:
            _LOGGER.error("Error logging into iCloud service: %s", error)
            await self._async_release_api()
            self._clear_session_files()
            errors = {CONF_PASSWORD: "invalid_auth"}
            return self._show_setup_form(user_input, errors, step_id)

        if self.api.requires_2fa:
            return await self.async_step_verification_code()

        if self.api.requires_2sa:
            return await self.async_step_trusted_device()

        try:
            devices = await self.hass.async_add_executor_job(
                getattr, self.api, "devices"
            )
            if not devices:
                raise PyiCloudNoDevicesException()
        except (
            PyiCloudFailedLoginException,
            PyiCloud2FARequiredException,
            PyiCloud2SARequiredException,
            PyiCloudAuthRequiredException,
        ) as error:
            _LOGGER.error("Error logging into iCloud service: %s", error)
            await self._async_release_api()
            self._clear_session_files()
            errors = {CONF_PASSWORD: "invalid_auth"}
            return self._show_setup_form(user_input, errors, step_id)
        except (
            PyiCloudServiceNotActivatedException,
            PyiCloudNoDevicesException,
            PyiCloudServiceUnavailable,
        ):
            _LOGGER.error("No device found in the iCloud account: %s", self._username)
            await self._async_release_api()
            self._clear_session_files()
            return self.async_abort(reason="no_device")

        data = {
            CONF_USERNAME: self._username,
            CONF_PASSWORD: self._password,
            CONF_WITH_FAMILY: self._with_family,
            CONF_MAX_INTERVAL: self._max_interval,
        }

        await self._async_release_api()

        # If this is a password update attempt, update the entry instead of creating one
        if self.source == SOURCE_USER:
            return self.async_create_entry(title=self._username, data=data)

        return self.async_update_reload_and_abort(
            self._get_reauth_entry(),
            data=data,
        )

    async def async_step_user(self, user_input=None):
        """Handle a flow initiated by the user."""
        errors = {}

        icloud_dir = Store(self.hass, STORAGE_VERSION, STORAGE_KEY)

        await self.hass.async_add_executor_job(
            lambda: os.makedirs(icloud_dir.path, exist_ok=True)
        )

        if user_input is None:
            return self._show_setup_form(user_input, errors)

        return await self._validate_and_create_entry(user_input, "user")

    async def _login(self):
        return await self.hass.async_add_executor_job(
            lambda: PyiCloudService(
                self._username,
                self._password,
                Store(self.hass, STORAGE_VERSION, STORAGE_KEY).path,
                with_family=self._with_family,
                china_mainland=True,
            )
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        await self.async_set_unique_id(self.context["unique_id"])
        self._get_reauth_entry()
        self._existing_entry_data = {**entry_data}
        self._description_placeholders = {"username": entry_data[CONF_USERNAME]}
        self._username = entry_data[CONF_USERNAME]
        self._password = entry_data[CONF_PASSWORD]
        self._with_family = entry_data.get(CONF_WITH_FAMILY, DEFAULT_WITH_FAMILY)
        self._max_interval = entry_data.get(CONF_MAX_INTERVAL, DEFAULT_MAX_INTERVAL)
        await self._async_release_api()
        self._clear_session_files()
        try:
            self.api = await self._login()
        except PyiCloudFailedLoginException:
            await self._async_release_api()
            self._clear_session_files()
            return await self.async_step_reauth_confirm(
                errors={CONF_PASSWORD: "invalid_auth"}
            )
        if self.api.requires_2fa:
            return await self.async_step_verification_code()
        if self.api.requires_2sa:
            return await self.async_step_trusted_device()
        return await self._validate_and_create_entry(
            {CONF_PASSWORD: self._password}, "reauth_confirm"
        )

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None, errors=None
    ) -> ConfigFlowResult:
        """Update password for a config entry that can't authenticate."""
        if user_input is None:
            return self._show_setup_form(step_id="reauth_confirm", errors=errors)

        return await self._validate_and_create_entry(user_input, "reauth_confirm")

    async def async_step_trusted_device(self, user_input=None, errors=None):
        """We need a trusted device."""
        if errors is None:
            errors = {}

        if self.api is None:
            self._clear_session_files()
            errors = {CONF_PASSWORD: "invalid_auth"}
            if self.source == SOURCE_USER:
                return self._show_setup_form(
                    {
                        CONF_USERNAME: self._username,
                        CONF_PASSWORD: self._password or "",
                        CONF_WITH_FAMILY: self._with_family,
                        CONF_MAX_INTERVAL: self._max_interval,
                    },
                    errors,
                    "user",
                )
            return await self.async_step_reauth_confirm(errors=errors)

        trusted_devices = (
            await self.hass.async_add_executor_job(
                getattr, self.api, "trusted_devices"
            )
            or []
        )
        if not trusted_devices:
            await self._async_release_api()
            self._clear_session_files()
            return self.async_abort(reason="no_device")

        trusted_devices_for_form = {}
        for i, device in enumerate(trusted_devices):
            trusted_devices_for_form[i] = device.get(
                "deviceName", f"SMS to {device.get('phoneNumber')}"
            )

        if user_input is None:
            return await self._show_trusted_device_form(
                trusted_devices_for_form, user_input, errors
            )

        self._trusted_device = trusted_devices[int(user_input[CONF_TRUSTED_DEVICE])]

        if not await self.hass.async_add_executor_job(
            self.api.send_verification_code, self._trusted_device
        ):
            _LOGGER.error("Failed to send verification code")
            self._trusted_device = None
            errors[CONF_TRUSTED_DEVICE] = "send_verification_code"

            return await self._show_trusted_device_form(
                trusted_devices_for_form, user_input, errors
            )

        return await self.async_step_verification_code()

    async def _show_trusted_device_form(
        self, trusted_devices, user_input=None, errors=None
    ):
        """Show the trusted_device form to the user."""

        return self.async_show_form(
            step_id=CONF_TRUSTED_DEVICE,
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_TRUSTED_DEVICE): vol.All(
                        vol.Coerce(int), vol.In(trusted_devices)
                    )
                }
            ),
            errors=errors or {},
        )

    async def async_step_verification_code(self, user_input=None, errors=None):
        """Ask the verification code to the user."""
        if errors is None:
            errors = {}

        if self.api is None:
            self._clear_session_files()
            errors = {CONF_PASSWORD: "invalid_auth"}
            if self.source == SOURCE_USER:
                return self._show_setup_form(
                    {
                        CONF_USERNAME: self._username,
                        CONF_PASSWORD: self._password or "",
                        CONF_WITH_FAMILY: self._with_family,
                        CONF_MAX_INTERVAL: self._max_interval,
                    },
                    errors,
                    "user",
                )
            return await self.async_step_reauth_confirm(errors=errors)

        if user_input is None:
            return await self._show_verification_code_form(user_input, errors)

        self._verification_code = user_input[CONF_VERIFICATION_CODE]

        try:
            if self.api.requires_2fa:
                if not await self.hass.async_add_executor_job(
                    self.api.validate_2fa_code, self._verification_code
                ):
                    raise PyiCloudException("The code you entered is not valid.")
            else:
                if self._trusted_device is None:
                    return await self.async_step_trusted_device(None, errors)
                if not await self.hass.async_add_executor_job(
                    self.api.validate_verification_code,
                    self._trusted_device,
                    self._verification_code,
                ):
                    raise PyiCloudException("The code you entered is not valid.")
        except PyiCloudException as error:
            # Reset to the initial 2FA state to allow the user to retry
            _LOGGER.error("Failed to verify verification code: %s", error)
            self._trusted_device = None
            self._verification_code = None
            errors["base"] = "validate_verification_code"

            if self.api is not None and self.api.requires_2fa:
                try:
                    await self._async_release_api()
                    self._clear_session_files()
                    self.api = await self._login()
                    if self.api.requires_2fa:
                        return await self.async_step_verification_code(None, errors)
                    if self.api.requires_2sa:
                        return await self.async_step_trusted_device(None, errors)
                    step_id = "user" if self.source == SOURCE_USER else "reauth_confirm"
                    return await self._validate_and_create_entry(
                        {
                            CONF_USERNAME: self._username,
                            CONF_PASSWORD: self._password,
                            CONF_WITH_FAMILY: self._with_family,
                            CONF_MAX_INTERVAL: self._max_interval,
                        },
                        step_id,
                    )
                except PyiCloudFailedLoginException as error_login:
                    _LOGGER.error("Error logging into iCloud service: %s", error_login)
                    await self._async_release_api()
                    self._clear_session_files()
                    errors = {CONF_PASSWORD: "invalid_auth"}
                    if self.source == SOURCE_USER:
                        return self._show_setup_form(
                            {
                                CONF_USERNAME: self._username,
                                CONF_PASSWORD: self._password,
                                CONF_WITH_FAMILY: self._with_family,
                                CONF_MAX_INTERVAL: self._max_interval,
                            },
                            errors,
                            "user",
                        )
                    return await self.async_step_reauth_confirm(errors=errors)

            try:
                await self._async_release_api()
                self._clear_session_files()
                self.api = await self._login()
                if self.api.requires_2fa:
                    return await self.async_step_verification_code(None, errors)
                if self.api.requires_2sa:
                    return await self.async_step_trusted_device(None, errors)
                step_id = "user" if self.source == SOURCE_USER else "reauth_confirm"
                return await self._validate_and_create_entry(
                    {
                        CONF_USERNAME: self._username,
                        CONF_PASSWORD: self._password,
                        CONF_WITH_FAMILY: self._with_family,
                        CONF_MAX_INTERVAL: self._max_interval,
                    },
                    step_id,
                )
            except PyiCloudFailedLoginException as error_login:
                _LOGGER.error("Error logging into iCloud service: %s", error_login)
                await self._async_release_api()
                self._clear_session_files()
                errors = {CONF_PASSWORD: "invalid_auth"}
                if self.source == SOURCE_USER:
                    return self._show_setup_form(
                        {
                            CONF_USERNAME: self._username,
                            CONF_PASSWORD: self._password,
                            CONF_WITH_FAMILY: self._with_family,
                            CONF_MAX_INTERVAL: self._max_interval,
                        },
                        errors,
                        "user",
                    )
                return await self.async_step_reauth_confirm(errors=errors)

        step_id = "user" if self.source == SOURCE_USER else "reauth_confirm"
        return await self._validate_and_create_entry(
            {
                CONF_USERNAME: self._username,
                CONF_PASSWORD: self._password,
                CONF_WITH_FAMILY: self._with_family,
                CONF_MAX_INTERVAL: self._max_interval,
            },
            step_id,
        )

    async def _show_verification_code_form(self, user_input=None, errors=None):
        """Show the verification_code form to the user."""

        return self.async_show_form(
            step_id=CONF_VERIFICATION_CODE,
            data_schema=vol.Schema({vol.Required(CONF_VERIFICATION_CODE): str}),
            errors=errors or {},
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Get the options flow for this handler."""
        return IcloudOptionsFlowHandler()


def _select_field(name: str, current: str) -> dict[str, Any]:
    current = current or TIME_NONE
    values = list(TIME_CHOICES)
    if current not in values and current != TIME_NONE:
        values = [current] + values
    return {
        "name": name,
        "required": True,
        "default": current,
        "selector": {
            "select": {
                "options": [{"value": TIME_NONE, "label": "—"}]
                + [{"value": value, "label": value} for value in values],
                "mode": "dropdown",
                "multiple": False,
            }
        },
    }


class _TimeRangeGrid(selector.Selector):
    selector_type = "text"
    CONFIG_SCHEMA = vol.Schema({})

    def __init__(self, start_name: str, end_name: str, start: str, end: str) -> None:
        self.config: dict[str, Any] = {}
        self._start_name = start_name
        self._end_name = end_name
        self._start = start or TIME_NONE
        self._end = end or TIME_NONE

    def __call__(self, data: Any) -> Any:
        return data

    def serialize(self) -> dict[str, Any]:
        return {
            "type": "grid",
            "flatten": True,
            "column_min_width": "130px",
            "schema": [
                _select_field(self._start_name, self._start),
                _select_field(self._end_name, self._end),
            ],
        }


class _ValueHold(selector.Selector):
    selector_type = "text"
    CONFIG_SCHEMA = vol.Schema({})

    def __init__(self) -> None:
        self.config: dict[str, Any] = {}

    def __call__(self, data: Any) -> Any:
        return data

    def serialize(self) -> dict[str, Any]:
        return {"type": "grid", "flatten": True, "schema": []}


def _flat_pairs(user_input: dict[str, Any], prefix: str, count: int, fallback):
    pairs = []
    for index in range(1, count + 1):
        start_key = f"{prefix}_start_{index}"
        end_key = f"{prefix}_end_{index}"
        block = user_input.pop(f"{prefix}_{index}", None)
        if isinstance(block, dict):
            pairs.append(
                (
                    block.get("start", block.get(start_key, fallback[index - 1][0])),
                    block.get("end", block.get(end_key, fallback[index - 1][1])),
                )
            )
            continue
        pairs.append(
            (
                user_input.pop(start_key, fallback[index - 1][0]),
                user_input.pop(end_key, fallback[index - 1][1]),
            )
        )
    return pairs


def _store_flat_pairs(user_input: dict[str, Any], prefix: str, pairs) -> None:
    for index, (start, end) in enumerate(pairs, start=1):
        user_input[f"{prefix}_start_{index}"] = start
        user_input[f"{prefix}_end_{index}"] = end


class IcloudOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle iCloud options."""

    def _opt(self, key, default, user_input: dict[str, Any] | None = None):
        entry = self.config_entry
        if user_input is not None and key in user_input:
            return user_input[key]
        return entry.options.get(key, entry.data.get(key, default))

    def _merge_options(self, updates: dict[str, Any]) -> dict[str, Any]:
        return {**self.config_entry.options, **updates}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="init",
            menu_options=["locate", "amap"],
        )

    async def async_step_locate(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self.config_entry

        saved_peak = windows_text_to_pairs(
            opt_windows_text(
                entry.options.get(
                    CONF_PEAK_WINDOWS,
                    entry.data.get(CONF_PEAK_WINDOWS, DEFAULT_PEAK_WINDOWS),
                ),
                DEFAULT_PEAK_WINDOWS,
            ),
            PEAK_RANGE_COUNT,
        )
        saved_offpeak = windows_text_to_pairs(
            opt_windows_text(
                entry.options.get(
                    CONF_OFFPEAK_WINDOWS,
                    entry.data.get(CONF_OFFPEAK_WINDOWS, DEFAULT_OFFPEAK_WINDOWS),
                ),
                DEFAULT_OFFPEAK_WINDOWS,
            ),
            OFFPEAK_RANGE_COUNT,
        )

        if user_input is not None:
            user_input[CONF_PEAK_ENABLED] = bool(
                user_input.get(CONF_PEAK_ENABLED, False)
            )
            user_input[CONF_OFFPEAK_ENABLED] = bool(
                user_input.get(CONF_OFFPEAK_ENABLED, False)
            )
            user_input[CONF_PERIOD_WEEKDAYS] = bool(
                user_input.get(CONF_PERIOD_WEEKDAYS, False)
            )
            peak_pairs = _flat_pairs(user_input, "peak", PEAK_RANGE_COUNT, saved_peak)
            offpeak_pairs = _flat_pairs(
                user_input, "offpeak", OFFPEAK_RANGE_COUNT, saved_offpeak
            )
            peak_text = pairs_to_windows_text(peak_pairs)
            offpeak_text = pairs_to_windows_text(offpeak_pairs)
            if peak_text is None or (user_input[CONF_PEAK_ENABLED] and not peak_text):
                errors["peak_start_1"] = "invalid_windows"
            if offpeak_text is None or (
                user_input[CONF_OFFPEAK_ENABLED] and not offpeak_text
            ):
                errors["offpeak_start_1"] = "invalid_windows"
            if not errors:
                user_input[CONF_PEAK_WINDOWS] = peak_text or ""
                user_input[CONF_OFFPEAK_WINDOWS] = offpeak_text or ""
                return self.async_create_entry(
                    title="", data=self._merge_options(user_input)
                )
            _store_flat_pairs(user_input, "peak", peak_pairs)
            _store_flat_pairs(user_input, "offpeak", offpeak_pairs)

        peak_pairs = (
            [
                (
                    self._opt(f"peak_start_{index}", TIME_NONE, user_input),
                    self._opt(f"peak_end_{index}", TIME_NONE, user_input),
                )
                for index in range(1, PEAK_RANGE_COUNT + 1)
            ]
            if user_input is not None and "peak_start_1" in user_input
            else saved_peak
        )
        offpeak_pairs = (
            [
                (
                    self._opt(f"offpeak_start_{index}", TIME_NONE, user_input),
                    self._opt(f"offpeak_end_{index}", TIME_NONE, user_input),
                )
                for index in range(1, OFFPEAK_RANGE_COUNT + 1)
            ]
            if user_input is not None and "offpeak_start_1" in user_input
            else saved_offpeak
        )

        schema: dict[Any, Any] = {
            vol.Required(
                CONF_MAX_INTERVAL,
                default=self._opt(CONF_MAX_INTERVAL, DEFAULT_MAX_INTERVAL, user_input),
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=180)),
            vol.Required(
                CONF_PERIOD_WEEKDAYS,
                default=self._opt(
                    CONF_PERIOD_WEEKDAYS, DEFAULT_PERIOD_WEEKDAYS, user_input
                ),
            ): bool,
            vol.Required(
                CONF_PEAK_ENABLED,
                default=self._opt(CONF_PEAK_ENABLED, DEFAULT_PEAK_ENABLED, user_input),
            ): bool,
        }
        for index, (start, end) in enumerate(peak_pairs, start=1):
            schema[
                vol.Required(f"peak_start_{index}", default=start or TIME_NONE)
            ] = _TimeRangeGrid(
                f"peak_start_{index}", f"peak_end_{index}", start, end
            )
            schema[vol.Required(f"peak_end_{index}", default=end or TIME_NONE)] = (
                _ValueHold()
            )
        schema[
            vol.Required(
                CONF_PEAK_INTERVAL,
                default=self._opt(CONF_PEAK_INTERVAL, DEFAULT_PEAK_INTERVAL, user_input),
            )
        ] = vol.All(vol.Coerce(int), vol.Range(min=1, max=180))
        schema[
            vol.Required(
                CONF_OFFPEAK_ENABLED,
                default=self._opt(
                    CONF_OFFPEAK_ENABLED, DEFAULT_OFFPEAK_ENABLED, user_input
                ),
            )
        ] = bool
        for index, (start, end) in enumerate(offpeak_pairs, start=1):
            schema[
                vol.Required(f"offpeak_start_{index}", default=start or TIME_NONE)
            ] = _TimeRangeGrid(
                f"offpeak_start_{index}", f"offpeak_end_{index}", start, end
            )
            schema[vol.Required(f"offpeak_end_{index}", default=end or TIME_NONE)] = (
                _ValueHold()
            )
        schema[
            vol.Required(
                CONF_OFFPEAK_INTERVAL,
                default=self._opt(
                    CONF_OFFPEAK_INTERVAL, DEFAULT_OFFPEAK_INTERVAL, user_input
                ),
            )
        ] = vol.All(vol.Coerce(int), vol.Range(min=1, max=180))

        suggested = {**entry.data, **entry.options}
        if user_input is not None:
            suggested.update(user_input)
        return self.async_show_form(
            step_id="locate",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(schema), suggested
            ),
            errors=errors,
        )

    async def async_step_amap(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self.config_entry

        if user_input is not None:
            user_input[CONF_COMMUTE_ENABLED] = bool(
                user_input.get(CONF_COMMUTE_ENABLED, False)
            )
            zones = user_input.get(CONF_COMMUTE_ZONES) or []
            if isinstance(zones, str):
                zones = [zones]
            user_input[CONF_COMMUTE_ZONES] = [
                zone
                for zone in zones
                if str(zone or "").strip() and self.hass.states.get(zone) is not None
            ]
            submitted_key = str(user_input.get(CONF_AMAP_KEY) or "").strip()
            user_input[CONF_AMAP_KEY] = submitted_key or str(
                entry.options.get(CONF_AMAP_KEY, entry.data.get(CONF_AMAP_KEY, ""))
                or ""
            ).strip()
            user_input[CONF_ACTIVITY_ENTITY] = [
                entity_id
                for entity_id in activity_entities(user_input.get(CONF_ACTIVITY_ENTITY))
                if self.hass.states.get(entity_id) is not None
            ]
            if user_input[CONF_COMMUTE_ENABLED]:
                if not user_input[CONF_AMAP_KEY]:
                    errors[CONF_AMAP_KEY] = "commute_key"
                if not user_input[CONF_COMMUTE_ZONES]:
                    errors[CONF_COMMUTE_ZONES] = "commute_zones"
            if not errors:
                return self.async_create_entry(
                    title="", data=self._merge_options(user_input)
                )

        commute_zones = self._opt(CONF_COMMUTE_ZONES, DEFAULT_COMMUTE_ZONES, user_input)
        if isinstance(commute_zones, str):
            commute_zones = [commute_zones] if commute_zones else []
        elif not isinstance(commute_zones, list):
            commute_zones = []
        commute_zones = [zone for zone in commute_zones if str(zone or "").strip()]
        commute_on = bool(
            self._opt(CONF_COMMUTE_ENABLED, DEFAULT_COMMUTE_ENABLED, user_input)
        )
        zone_field = vol.Required if commute_on else vol.Optional
        activity_entity = activity_entities(
            self._opt(CONF_ACTIVITY_ENTITY, DEFAULT_ACTIVITY_ENTITY, user_input)
        )
        activity_field = (
            vol.Optional(CONF_ACTIVITY_ENTITY, default=activity_entity)
            if activity_entity
            else vol.Optional(CONF_ACTIVITY_ENTITY)
        )

        schema: dict[Any, Any] = {
            vol.Required(
                CONF_COMMUTE_ENABLED,
                default=self._opt(
                    CONF_COMMUTE_ENABLED, DEFAULT_COMMUTE_ENABLED, user_input
                ),
            ): bool,
            zone_field(
                CONF_COMMUTE_ZONES,
                default=commute_zones,
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="zone", multiple=True)
            ),
            activity_field: selector.EntitySelector(
                selector.EntitySelectorConfig(multiple=True)
            ),
            vol.Optional(
                CONF_AMAP_KEY,
                default=self._opt(CONF_AMAP_KEY, "", user_input),
            ): _PASSWORD_SELECTOR,
        }

        suggested = {**entry.data, **entry.options}
        if user_input is not None:
            suggested.update(user_input)
        if not isinstance(suggested.get(CONF_ACTIVITY_ENTITY), list):
            suggested[CONF_ACTIVITY_ENTITY] = []
        return self.async_show_form(
            step_id="amap",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(schema), suggested
            ),
            errors=errors,
        )
