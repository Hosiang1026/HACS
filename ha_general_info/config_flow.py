from __future__ import annotations
from copy import deepcopy
from typing import Any
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TimeSelector,
)
from .const import (
    CONF_ANNOUNCE,
    CONF_ENABLED,
    CONF_FEEDS,
    CONF_INTERVAL,
    CONF_ITEMS,
    CONF_LIMIT,
    CONF_NOTIFY,
    CONF_NOTIFY_ENABLED,
    CONF_NOTIFY_END,
    CONF_NOTIFY_START,
    CONF_PREDICT_ENABLED,
    CONF_PROVIDER,
    CONF_SANJIN_BRACELET,
    CONF_SANJIN_NECKLACE,
    CONF_SANJIN_RING,
    CONF_SYMBOLS,
    CONF_TRACK_LOW,
    CONF_TRADING_ONLY,
    CONF_TYPES,
    CONF_NOTIFY_CHANGE_PCT,
    CONF_NOTIFY_ON_CHANGE,
    DEFAULT_LOTTERY_INTERVAL,
    DEFAULT_LOTTERY_PREDICT,
    DEFAULT_MEDIA_INTERVAL,
    DEFAULT_METAL_INTERVAL,
    DEFAULT_NAME,
    DEFAULT_NEWS_FEEDS,
    DEFAULT_NEWS_INTERVAL,
    DEFAULT_NOTIFY_ENABLED,
    DEFAULT_NOTIFY_END,
    DEFAULT_NOTIFY_START,
    DEFAULT_SANJIN_BRACELET,
    DEFAULT_SANJIN_NECKLACE,
    DEFAULT_SANJIN_RING,
    DEFAULT_STOCK_CHANGE_PCT,
    DEFAULT_STOCK_INTERVAL,
    DOMAIN,
    LOTTERY_TYPES,
    METAL_ITEMS,
    MODULE_LOTTERY,
    MODULE_MEDIA,
    MODULE_METAL,
    MODULE_NEWS,
    MODULE_STOCK,
    PROVIDER_CWL,
    PROVIDER_HUANGJINJIAGE,
    PROVIDER_RSS,
    PROVIDER_SINA,
    PROVIDER_TENCENT,
)
from .defaults import default_options, merge_options


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


class GeneralInfoConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1
    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._options: dict[str, Any] = default_options()
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        if user_input is not None:
            self._data = {
                CONF_NAME: user_input.get(CONF_NAME) or DEFAULT_NAME,
                CONF_NOTIFY: _notify_values(user_input.get(CONF_NOTIFY)),
                CONF_ANNOUNCE: user_input.get(CONF_ANNOUNCE),
                CONF_NOTIFY_ENABLED: user_input.get(
                    CONF_NOTIFY_ENABLED, DEFAULT_NOTIFY_ENABLED
                ),
            }
            self._options[MODULE_LOTTERY][CONF_ENABLED] = bool(
                user_input.get("enable_lottery", True)
            )
            self._options[MODULE_METAL][CONF_ENABLED] = bool(
                user_input.get("enable_metal", True)
            )
            self._options[MODULE_NEWS][CONF_ENABLED] = bool(
                user_input.get("enable_news", True)
            )
            self._options[MODULE_STOCK][CONF_ENABLED] = bool(
                user_input.get("enable_stock", False)
            )
            self._options[MODULE_MEDIA][CONF_ENABLED] = bool(
                user_input.get("enable_media", False)
            )
            if self._options[MODULE_STOCK].get(CONF_ENABLED):
                return await self.async_step_stock_setup()
            if self._options[MODULE_MEDIA].get(CONF_ENABLED):
                return await self.async_step_media_setup()
            return self._create()
        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=DEFAULT_NAME): TextSelector(),
                vol.Optional(CONF_NOTIFY): SelectSelector(
                    SelectSelectorConfig(
                        options=_notify_options(self.hass),
                        multiple=True,
                        custom_value=True,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(CONF_ANNOUNCE): EntitySelector(
                    EntitySelectorConfig(domain=["media_player", "tts", "text", "input_text"])
                ),
                vol.Required(
                    CONF_NOTIFY_ENABLED, default=DEFAULT_NOTIFY_ENABLED
                ): BooleanSelector(),
                vol.Required("enable_lottery", default=True): BooleanSelector(),
                vol.Required("enable_metal", default=True): BooleanSelector(),
                vol.Required("enable_news", default=True): BooleanSelector(),
                vol.Required("enable_stock", default=False): BooleanSelector(),
                vol.Required("enable_media", default=False): BooleanSelector(),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)
    async def async_step_stock_setup(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        cfg = self._options[MODULE_STOCK]
        if user_input is not None:
            symbols = [
                x.strip().lower()
                for x in str(user_input.get("symbols_text") or "")
                .replace(",", "\n")
                .splitlines()
                if x.strip()
            ]
            cfg[CONF_SYMBOLS] = symbols
            cfg[CONF_PROVIDER] = user_input.get(CONF_PROVIDER) or PROVIDER_SINA
            self._options[MODULE_STOCK] = cfg
            if self._options[MODULE_MEDIA].get(CONF_ENABLED):
                return await self.async_step_media_setup()
            return self._create()
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_PROVIDER, default=cfg.get(CONF_PROVIDER, PROVIDER_SINA)
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=[PROVIDER_SINA, PROVIDER_TENCENT],
                        mode=SelectSelectorMode.DROPDOWN,
                        translation_key="stock_provider",
                    )
                ),
                vol.Optional("symbols_text", default=""): TextSelector(
                    TextSelectorConfig(multiline=True)
                ),
            }
        )
        return self.async_show_form(step_id="stock_setup", data_schema=schema)
    async def async_step_media_setup(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        cfg = self._options[MODULE_MEDIA]
        if user_input is not None:
            allowed = {"movie", "tv", "music"}
            raw = user_input.get(CONF_ITEMS) or []
            if isinstance(raw, str):
                raw = [raw]
            cfg[CONF_ITEMS] = [x for x in raw if x in allowed]
            self._options[MODULE_MEDIA] = cfg
            return self._create()
        items = [x for x in (cfg.get(CONF_ITEMS) or []) if x in ("movie", "tv", "music")]
        items_key = (
            vol.Optional(CONF_ITEMS, default=items)
            if items
            else vol.Optional(CONF_ITEMS)
        )
        schema = vol.Schema(
            {
                items_key: SelectSelector(
                    SelectSelectorConfig(
                        options=["movie", "tv", "music"],
                        multiple=True,
                        mode=SelectSelectorMode.LIST,
                        translation_key="media_items",
                    )
                ),
            }
        )
        return self.async_show_form(step_id="media_setup", data_schema=schema)
    def _create(self) -> ConfigFlowResult:
        options = deepcopy(self._options)
        options[CONF_NOTIFY] = self._data.get(CONF_NOTIFY)
        options[CONF_ANNOUNCE] = self._data.get(CONF_ANNOUNCE)
        options[CONF_NOTIFY_ENABLED] = self._data.get(
            CONF_NOTIFY_ENABLED, DEFAULT_NOTIFY_ENABLED
        )
        return self.async_create_entry(
            title=self._data.get(CONF_NAME) or DEFAULT_NAME,
            data={CONF_NAME: self._data.get(CONF_NAME) or DEFAULT_NAME},
            options=options,
        )
    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return GeneralInfoOptionsFlow()


class GeneralInfoOptionsFlow(OptionsFlow):
    def __init__(self) -> None:
        self._options: dict[str, Any] = {}
    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._options = merge_options(dict(self.config_entry.options))
        return await self.async_step_menu(user_input)
    def _save(self) -> ConfigFlowResult:
        return self.async_create_entry(title="", data=self._options)
    async def async_step_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            next_step = user_input.get("next")
            if next_step == "global":
                return await self.async_step_global()
            if next_step == "lottery":
                return await self.async_step_lottery()
            if next_step == "metal":
                return await self.async_step_metal()
            if next_step == "news":
                return await self.async_step_news()
            if next_step == "stock":
                return await self.async_step_stock()
            if next_step == "media":
                return await self.async_step_media()
        schema = vol.Schema(
            {
                vol.Required("next", default="global"): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            "global",
                            "lottery",
                            "metal",
                            "news",
                            "stock",
                            "media",
                        ],
                        mode=SelectSelectorMode.LIST,
                        translation_key="menu_next",
                    )
                )
            }
        )
        return self.async_show_form(step_id="menu", data_schema=schema)
    async def async_step_global(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._options[CONF_NOTIFY] = _notify_values(user_input.get(CONF_NOTIFY))
            self._options[CONF_ANNOUNCE] = user_input.get(CONF_ANNOUNCE)
            self._options[CONF_NOTIFY_ENABLED] = user_input.get(
                CONF_NOTIFY_ENABLED, True
            )
            return self._save()
        notify = _notify_values(self._options.get(CONF_NOTIFY))
        notify_key = (
            vol.Optional(CONF_NOTIFY, default=notify)
            if notify
            else vol.Optional(CONF_NOTIFY)
        )
        announce = self._options.get(CONF_ANNOUNCE)
        announce_key = (
            vol.Optional(CONF_ANNOUNCE, default=announce)
            if announce
            else vol.Optional(CONF_ANNOUNCE)
        )
        schema = vol.Schema(
            {
                notify_key: SelectSelector(
                    SelectSelectorConfig(
                        options=_notify_options(self.hass, notify),
                        multiple=True,
                        custom_value=True,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
                announce_key: EntitySelector(
                    EntitySelectorConfig(
                        domain=["media_player", "tts", "text", "input_text"]
                    )
                ),
                vol.Required(
                    CONF_NOTIFY_ENABLED,
                    default=self._options.get(CONF_NOTIFY_ENABLED, True),
                ): BooleanSelector(),
            }
        )
        return self.async_show_form(step_id="global", data_schema=schema)
    async def async_step_lottery(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        cfg = self._options.setdefault(MODULE_LOTTERY, {})
        if user_input is not None:
            types = user_input.get(CONF_TYPES) or list(LOTTERY_TYPES)
            if isinstance(types, str):
                types = [types]
            cfg.update(user_input)
            cfg[CONF_TYPES] = list(types)
            cfg[CONF_PROVIDER] = PROVIDER_CWL
            self._options[MODULE_LOTTERY] = cfg
            return self._save()
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_ENABLED, default=cfg.get(CONF_ENABLED, True)
                ): BooleanSelector(),
                vol.Required(
                    CONF_TYPES, default=cfg.get(CONF_TYPES) or list(LOTTERY_TYPES)
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=list(LOTTERY_TYPES),
                        multiple=True,
                        mode=SelectSelectorMode.LIST,
                        translation_key="lottery_types",
                    )
                ),
                vol.Required(
                    CONF_INTERVAL, default=cfg.get(CONF_INTERVAL, DEFAULT_LOTTERY_INTERVAL)
                ): NumberSelector(
                    NumberSelectorConfig(min=1, max=30, mode=NumberSelectorMode.BOX)
                ),
                vol.Required(
                    CONF_PREDICT_ENABLED,
                    default=cfg.get(CONF_PREDICT_ENABLED, DEFAULT_LOTTERY_PREDICT),
                ): BooleanSelector(),
                vol.Required(
                    CONF_NOTIFY_ENABLED, default=cfg.get(CONF_NOTIFY_ENABLED, False)
                ): BooleanSelector(),
                vol.Required(
                    CONF_NOTIFY_START,
                    default=cfg.get(CONF_NOTIFY_START, DEFAULT_NOTIFY_START),
                ): TimeSelector(),
                vol.Required(
                    CONF_NOTIFY_END,
                    default=cfg.get(CONF_NOTIFY_END, DEFAULT_NOTIFY_END),
                ): TimeSelector(),
            }
        )
        return self.async_show_form(step_id="lottery", data_schema=schema)
    async def async_step_metal(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        cfg = self._options.setdefault(MODULE_METAL, {})
        if user_input is not None:
            items = user_input.get(CONF_ITEMS) or []
            if isinstance(items, str):
                items = [items]
            cfg.update(user_input)
            cfg[CONF_ITEMS] = list(items)
            cfg[CONF_PROVIDER] = PROVIDER_HUANGJINJIAGE
            cfg[CONF_TRACK_LOW] = bool(user_input.get(CONF_TRACK_LOW, True))
            self._options[MODULE_METAL] = cfg
            return self._save()
        items = cfg.get(CONF_ITEMS) or []
        items_key = (
            vol.Optional(CONF_ITEMS, default=list(items))
            if items
            else vol.Optional(CONF_ITEMS)
        )
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_ENABLED, default=cfg.get(CONF_ENABLED, True)
                ): BooleanSelector(),
                items_key: SelectSelector(
                    SelectSelectorConfig(
                        options=list(METAL_ITEMS),
                        multiple=True,
                        mode=SelectSelectorMode.LIST,
                        translation_key="metal_items",
                    )
                ),
                vol.Required(
                    CONF_INTERVAL, default=cfg.get(CONF_INTERVAL, DEFAULT_METAL_INTERVAL)
                ): NumberSelector(
                    NumberSelectorConfig(min=5, max=1440, mode=NumberSelectorMode.BOX)
                ),
                vol.Required(
                    CONF_TRACK_LOW, default=cfg.get(CONF_TRACK_LOW, True)
                ): BooleanSelector(),
                vol.Required(
                    CONF_SANJIN_NECKLACE,
                    default=cfg.get(CONF_SANJIN_NECKLACE, DEFAULT_SANJIN_NECKLACE),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0, max=200, step=0.1, mode=NumberSelectorMode.BOX
                    )
                ),
                vol.Required(
                    CONF_SANJIN_BRACELET,
                    default=cfg.get(CONF_SANJIN_BRACELET, DEFAULT_SANJIN_BRACELET),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0, max=200, step=0.1, mode=NumberSelectorMode.BOX
                    )
                ),
                vol.Required(
                    CONF_SANJIN_RING,
                    default=cfg.get(CONF_SANJIN_RING, DEFAULT_SANJIN_RING),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0, max=200, step=0.1, mode=NumberSelectorMode.BOX
                    )
                ),
                vol.Required(
                    CONF_NOTIFY_ENABLED, default=cfg.get(CONF_NOTIFY_ENABLED, False)
                ): BooleanSelector(),
                vol.Required(
                    CONF_NOTIFY_START,
                    default=cfg.get(CONF_NOTIFY_START, DEFAULT_NOTIFY_START),
                ): TimeSelector(),
                vol.Required(
                    CONF_NOTIFY_END,
                    default=cfg.get(CONF_NOTIFY_END, DEFAULT_NOTIFY_END),
                ): TimeSelector(),
            }
        )
        return self.async_show_form(step_id="metal", data_schema=schema)
    async def async_step_news(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        cfg = self._options.setdefault(MODULE_NEWS, {})
        if user_input is not None:
            feeds_raw = user_input.pop("feeds_text", "")
            feeds = [x.strip() for x in str(feeds_raw).splitlines() if x.strip()]
            cfg.update(user_input)
            cfg[CONF_FEEDS] = feeds or list(DEFAULT_NEWS_FEEDS)
            cfg[CONF_PROVIDER] = PROVIDER_RSS
            self._options[MODULE_NEWS] = cfg
            return self._save()
        feeds = cfg.get(CONF_FEEDS) or list(DEFAULT_NEWS_FEEDS)
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_ENABLED, default=cfg.get(CONF_ENABLED, True)
                ): BooleanSelector(),
                vol.Optional(
                    "feeds_text", default="\n".join(feeds)
                ): TextSelector(TextSelectorConfig(multiline=True)),
                vol.Required(
                    CONF_LIMIT, default=cfg.get(CONF_LIMIT, 10)
                ): NumberSelector(
                    NumberSelectorConfig(min=1, max=50, mode=NumberSelectorMode.BOX)
                ),
                vol.Required(
                    CONF_INTERVAL, default=cfg.get(CONF_INTERVAL, DEFAULT_NEWS_INTERVAL)
                ): NumberSelector(
                    NumberSelectorConfig(min=0, max=1440, mode=NumberSelectorMode.BOX)
                ),
                vol.Required(
                    CONF_NOTIFY_ENABLED, default=cfg.get(CONF_NOTIFY_ENABLED, False)
                ): BooleanSelector(),
                vol.Required(
                    CONF_NOTIFY_START,
                    default=cfg.get(CONF_NOTIFY_START, DEFAULT_NOTIFY_START),
                ): TimeSelector(),
                vol.Required(
                    CONF_NOTIFY_END,
                    default=cfg.get(CONF_NOTIFY_END, DEFAULT_NOTIFY_END),
                ): TimeSelector(),
            }
        )
        return self.async_show_form(step_id="news", data_schema=schema)
    async def async_step_stock(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        cfg = self._options.setdefault(MODULE_STOCK, {})
        if user_input is not None:
            symbols_raw = user_input.pop("symbols_text", "")
            symbols = [
                x.strip().lower()
                for x in str(symbols_raw).replace(",", "\n").splitlines()
                if x.strip()
            ]
            cfg.update(user_input)
            cfg[CONF_SYMBOLS] = symbols
            self._options[MODULE_STOCK] = cfg
            return self._save()
        symbols = cfg.get(CONF_SYMBOLS) or []
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_ENABLED, default=cfg.get(CONF_ENABLED, False)
                ): BooleanSelector(),
                vol.Required(
                    CONF_PROVIDER, default=cfg.get(CONF_PROVIDER, PROVIDER_SINA)
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=[PROVIDER_SINA, PROVIDER_TENCENT],
                        mode=SelectSelectorMode.DROPDOWN,
                        translation_key="stock_provider",
                    )
                ),
                vol.Optional(
                    "symbols_text", default="\n".join(symbols)
                ): TextSelector(TextSelectorConfig(multiline=True)),
                vol.Required(
                    CONF_INTERVAL,
                    default=cfg.get(CONF_INTERVAL, DEFAULT_STOCK_INTERVAL),
                ): NumberSelector(
                    NumberSelectorConfig(min=1, max=60, mode=NumberSelectorMode.BOX)
                ),
                vol.Required(
                    CONF_TRADING_ONLY, default=cfg.get(CONF_TRADING_ONLY, True)
                ): BooleanSelector(),
                vol.Required(
                    CONF_NOTIFY_CHANGE_PCT,
                    default=cfg.get(CONF_NOTIFY_CHANGE_PCT, DEFAULT_STOCK_CHANGE_PCT),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0, max=20, step=0.5, mode=NumberSelectorMode.BOX
                    )
                ),
                vol.Required(
                    CONF_NOTIFY_ENABLED, default=cfg.get(CONF_NOTIFY_ENABLED, False)
                ): BooleanSelector(),
                vol.Required(
                    CONF_NOTIFY_START,
                    default=cfg.get(CONF_NOTIFY_START, DEFAULT_NOTIFY_START),
                ): TimeSelector(),
                vol.Required(
                    CONF_NOTIFY_END,
                    default=cfg.get(CONF_NOTIFY_END, DEFAULT_NOTIFY_END),
                ): TimeSelector(),
            }
        )
        return self.async_show_form(step_id="stock", data_schema=schema)
    async def async_step_media(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        cfg = self._options.setdefault(MODULE_MEDIA, {})
        if user_input is not None:
            allowed = {"movie", "tv", "music"}
            raw = user_input.get(CONF_ITEMS) or []
            if isinstance(raw, str):
                raw = [raw]
            items = [x for x in raw if x in allowed]
            cfg.update(user_input)
            cfg[CONF_ITEMS] = items
            self._options[MODULE_MEDIA] = cfg
            return self._save()
        items = [x for x in (cfg.get(CONF_ITEMS) or []) if x in ("movie", "tv", "music")]
        items_key = (
            vol.Optional(CONF_ITEMS, default=items)
            if items
            else vol.Optional(CONF_ITEMS)
        )
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_ENABLED, default=cfg.get(CONF_ENABLED, False)
                ): BooleanSelector(),
                items_key: SelectSelector(
                    SelectSelectorConfig(
                        options=["movie", "tv", "music"],
                        multiple=True,
                        mode=SelectSelectorMode.LIST,
                        translation_key="media_items",
                    )
                ),
                vol.Required(
                    CONF_LIMIT, default=cfg.get(CONF_LIMIT, 10)
                ): NumberSelector(
                    NumberSelectorConfig(min=1, max=30, mode=NumberSelectorMode.BOX)
                ),
                vol.Required(
                    CONF_INTERVAL, default=cfg.get(CONF_INTERVAL, DEFAULT_MEDIA_INTERVAL)
                ): NumberSelector(
                    NumberSelectorConfig(min=30, max=1440, mode=NumberSelectorMode.BOX)
                ),
                vol.Required(
                    CONF_NOTIFY_ON_CHANGE,
                    default=cfg.get(CONF_NOTIFY_ON_CHANGE, False),
                ): BooleanSelector(),
                vol.Required(
                    CONF_NOTIFY_ENABLED, default=cfg.get(CONF_NOTIFY_ENABLED, False)
                ): BooleanSelector(),
                vol.Required(
                    CONF_NOTIFY_START,
                    default=cfg.get(CONF_NOTIFY_START, DEFAULT_NOTIFY_START),
                ): TimeSelector(),
                vol.Required(
                    CONF_NOTIFY_END,
                    default=cfg.get(CONF_NOTIFY_END, DEFAULT_NOTIFY_END),
                ): TimeSelector(),
            }
        )
        return self.async_show_form(step_id="media", data_schema=schema)
