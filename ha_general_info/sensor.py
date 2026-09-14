from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    CONF_ITEMS,
    CONF_LIMIT,
    CONF_NAME,
    CONF_PREDICT_ENABLED,
    CONF_TYPES,
    DEFAULT_LOTTERY_PREDICT,
    DEFAULT_NAME,
    DEFAULT_NEWS_LIMIT,
    DOMAIN,
    LOTTERY_SSQ,
    LOTTERY_TYPES,
    MANUFACTURER,
    METAL_BANK,
    METAL_GOLD,
    METAL_ITEMS,
    METAL_SHOP,
    METAL_SILVER,
    VERSION,
)
from .coordinators.lottery import LotteryCoordinator
from .coordinators.media import MediaCoordinator
from .coordinators.metal import MetalCoordinator
from .coordinators.news import NewsCoordinator
from .coordinators.stock import StockCoordinator
from .coordinators.update_stamp import coord_updated_at
from .entity import GeneralInfoEntity

_LOTTERY_OBJECT = {
    "ssq": "lottery_ssq",
    "3d": "lottery_fc3d",
    "kl8": "lottery_kl8",
    "qlc": "lottery_qlc",
}
_LOTTERY_KEY = {"ssq": "ssq", "3d": "fc3d", "kl8": "kl8", "qlc": "qlc"}
_MEDIA_LABEL = {"movie": "电影", "tv": "剧集", "music": "音乐"}
_MEDIA_ICON = {
    "movie": "mdi:movie",
    "tv": "mdi:television-classic",
    "music": "mdi:music",
}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = []
    device_name = entry.title or entry.data.get(CONF_NAME) or DEFAULT_NAME

    entities.append(CreatedAtSensor(entry, device_name))

    if lottery := data.get("lottery"):
        entities.append(ModuleUpdatedSensor(lottery, object_id="lottery_updated_at"))
        types = lottery.module_cfg.get(CONF_TYPES) or list(LOTTERY_TYPES)
        for t in types:
            entities.append(LotterySensor(lottery, t))
        if lottery.module_cfg.get(CONF_PREDICT_ENABLED, DEFAULT_LOTTERY_PREDICT):
            if LOTTERY_SSQ in types:
                entities.append(LotteryPredictSensor(lottery, LOTTERY_SSQ))

    if metal := data.get("metal"):
        entities.append(ModuleUpdatedSensor(metal, object_id="metal_updated_at"))
        raw = metal.module_cfg.get(CONF_ITEMS) or []
        if isinstance(raw, str):
            raw = [raw]
        items = [x for x in raw if x in METAL_ITEMS] or list(METAL_ITEMS)
        if METAL_GOLD in items:
            entities.append(
                MetalPriceSensor(metal, "gold", "metal_gold", "metal_gold")
            )
        if METAL_SILVER in items:
            entities.append(
                MetalPriceSensor(metal, "silver", "metal_silver", "metal_silver")
            )
        if METAL_SHOP in items:
            entities.append(
                MetalPriceSensor(metal, "shop", "metal_shop", "metal_shop")
            )
        if METAL_BANK in items:
            entities.append(
                MetalPriceSensor(metal, "bank", "metal_bank", "metal_bank")
            )
        entities.append(
            MetalIntlSensor(
                metal,
                "intl_gold",
                "metal_intl_gold",
                "metal_intl_gold",
            )
        )
        entities.append(
            MetalIntlSensor(
                metal,
                "intl_silver",
                "metal_intl_silver",
                "metal_intl_silver",
            )
        )
        entities.append(MetalSanjinCostSensor(metal, "shop"))
        entities.append(MetalSanjinCostSensor(metal, "gold"))
        if metal.module_cfg.get("track_low", True):
            entities.append(MetalLowSensor(metal, "gold"))
            entities.append(MetalLowSensor(metal, "silver"))

    if news := data.get("news"):
        entities.append(ModuleUpdatedSensor(news, object_id="news_updated_at"))
        limit = int(news.module_cfg.get(CONF_LIMIT) or DEFAULT_NEWS_LIMIT)
        for idx in range(max(1, limit)):
            entities.append(NewsItemSensor(news, idx))

    if stock := data.get("stock"):
        entities.append(ModuleUpdatedSensor(stock, object_id="stock_updated_at"))
        for code in stock.module_cfg.get("symbols") or []:
            entities.append(StockSensor(stock, code))

    if media := data.get("media"):
        entities.append(ModuleUpdatedSensor(media, object_id="media_updated_at"))
        raw = media.module_cfg.get("items") or []
        if isinstance(raw, str):
            raw = [raw]
        items = [x for x in raw if x in ("movie", "tv", "music")] or [
            "movie",
            "tv",
            "music",
        ]
        limit = int(media.module_cfg.get(CONF_LIMIT) or 10)
        for key in items:
            for idx in range(max(1, limit)):
                entities.append(MediaItemSensor(media, key, idx))

    async_add_entities(entities)


class GlobalDeviceSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_should_poll = False
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(
        self,
        entry: ConfigEntry,
        device_name: str,
        *,
        key: str,
        object_id: str,
        translation_key: str,
    ) -> None:
        self._entry = entry
        self._object_id = object_id
        self.entity_id = f"sensor.{object_id}"
        self._attr_suggested_object_id = object_id
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_translation_key = translation_key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=device_name,
            manufacturer=MANUFACTURER,
            sw_version=VERSION,
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        wanted = f"sensor.{self._object_id}"
        if self.entity_id == wanted:
            return
        registry = async_get_entity_registry(self.hass)
        if registry.async_get(self.entity_id):
            try:
                registry.async_update_entity(self.entity_id, new_entity_id=wanted)
            except ValueError:
                pass


class CreatedAtSensor(GlobalDeviceSensor):
    _attr_icon = "mdi:calendar-plus"

    def __init__(self, entry: ConfigEntry, device_name: str) -> None:
        super().__init__(
            entry,
            device_name,
            key="created",
            object_id="created_at",
            translation_key="created_at",
        )

    @property
    def native_value(self) -> datetime | None:
        created = getattr(self._entry, "created_at", None)
        if created is None:
            return None
        if created.tzinfo is None:
            return dt_util.as_utc(created)
        return dt_util.as_utc(created)


class ModuleUpdatedSensor(GeneralInfoEntity, SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:update"

    def __init__(self, coordinator: DataUpdateCoordinator, *, object_id: str) -> None:
        super().__init__(
            coordinator,
            key="updated_at",
            platform="sensor",
            object_id=object_id,
            device_id=coordinator.device_id,
            device_name=coordinator.device_name,
            translation_key="updated_at",
        )

    @property
    def native_value(self) -> datetime | None:
        return coord_updated_at(self.coordinator)


class LotterySensor(GeneralInfoEntity, SensorEntity):
    _attr_icon = "mdi:ticket-confirmation"

    def __init__(self, coordinator: LotteryCoordinator, lottery_type: str) -> None:
        self._lottery_type = lottery_type
        object_id = _LOTTERY_OBJECT.get(lottery_type, f"lottery_{lottery_type}")
        key = _LOTTERY_KEY.get(lottery_type, lottery_type)
        super().__init__(
            coordinator,
            key=key,
            platform="sensor",
            object_id=object_id,
            device_id=coordinator.device_id,
            device_name=coordinator.device_name,
            translation_key=f"lottery_{key}",
        )

    @property
    def native_value(self):
        item = (self.coordinator.data or {}).get(self._lottery_type) or {}
        red = item.get("red")
        blue = item.get("blue")
        if red and blue:
            return f"{red}+{blue}"
        if red:
            return str(red)
        content = item.get("content")
        if content:
            return str(content)
        return item.get("code")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        item = (self.coordinator.data or {}).get(self._lottery_type) or {}
        return {
            "code": item.get("code"),
            "date": item.get("date"),
            "red": item.get("red"),
            "blue": item.get("blue"),
            "content": item.get("content"),
            "sales": item.get("sales"),
            "poolmoney": item.get("poolmoney"),
        }


class LotteryPredictSensor(GeneralInfoEntity, SensorEntity):
    _attr_icon = "mdi:crystal-ball"

    def __init__(self, coordinator: LotteryCoordinator, lottery_type: str) -> None:
        self._lottery_type = lottery_type
        super().__init__(
            coordinator,
            key="ssq_predict",
            platform="sensor",
            object_id="lottery_ssq_predict",
            device_id=coordinator.device_id,
            device_name=coordinator.device_name,
            translation_key="lottery_ssq_predict",
        )

    def _predict(self) -> dict[str, Any]:
        item = (self.coordinator.data or {}).get(self._lottery_type) or {}
        predict = item.get("predict")
        return predict if isinstance(predict, dict) else {}

    @property
    def native_value(self):
        return self._predict().get("value")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        p = self._predict()
        return {
            "red": p.get("red"),
            "blue": p.get("blue"),
            "method": p.get("method"),
            "based_on": p.get("based_on"),
            "hot_red": p.get("hot_red"),
            "cold_red": p.get("cold_red"),
            "hot_blue": p.get("hot_blue"),
            "cold_blue": p.get("cold_blue"),
        }


class MetalPriceSensor(GeneralInfoEntity, SensorEntity):
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:gold"

    def __init__(
        self,
        coordinator: MetalCoordinator,
        data_key: str,
        object_id: str,
        translation_key: str,
    ) -> None:
        super().__init__(
            coordinator,
            key=data_key,
            platform="sensor",
            object_id=object_id,
            device_id=coordinator.device_id,
            device_name=coordinator.device_name,
            translation_key=translation_key,
        )
        self._data_key = data_key

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get(self._data_key)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        if self._data_key == "shop":
            shops = data.get("shops") or {}
            return {
                "shops": shops,
                "count": len(shops) if isinstance(shops, dict) else 0,
            }
        if self._data_key == "bank":
            banks = data.get("banks") or {}
            return {
                "banks": banks,
                "count": len(banks) if isinstance(banks, dict) else 0,
            }
        return {
            "text": data.get(f"{self._data_key}_text"),
        }


class MetalIntlSensor(GeneralInfoEntity, SensorEntity):
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:earth"

    def __init__(
        self,
        coordinator: MetalCoordinator,
        data_key: str,
        object_id: str,
        translation_key: str,
    ) -> None:
        super().__init__(
            coordinator,
            key=data_key,
            platform="sensor",
            object_id=object_id,
            device_id=coordinator.device_id,
            device_name=coordinator.device_name,
            translation_key=translation_key,
        )
        self._data_key = data_key

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get(self._data_key)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        prefix = self._data_key
        return {
            "cny_per_g": data.get(f"{prefix}_cny"),
            "change": data.get(f"{prefix}_change"),
            "change_pct": data.get(f"{prefix}_change_pct"),
            "high": data.get(f"{prefix}_high"),
            "low": data.get(f"{prefix}_low"),
            "date": data.get(f"{prefix}_date"),
            "usd_cny": data.get("usd_cny"),
            "text": data.get(f"{prefix}_text"),
        }


class MetalSanjinCostSensor(GeneralInfoEntity, SensorEntity):
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:ring"

    def __init__(self, coordinator: MetalCoordinator, source: str) -> None:
        self._source = source
        key = f"sanjin_{source}_cost"
        super().__init__(
            coordinator,
            key=key,
            platform="sensor",
            object_id=f"metal_{key}",
            device_id=coordinator.device_id,
            device_name=coordinator.device_name,
            translation_key=f"metal_{key}",
        )

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get(f"sanjin_{self._source}_cost")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        return {
            "necklace_g": data.get("sanjin_necklace"),
            "bracelet_g": data.get("sanjin_bracelet"),
            "ring_g": data.get("sanjin_ring"),
            "total_g": data.get("sanjin_grams"),
            "unit_price": data.get(f"sanjin_{self._source}_unit"),
        }


class MetalLowSensor(GeneralInfoEntity, SensorEntity):
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:trending-down"

    def __init__(self, coordinator: MetalCoordinator, kind: str) -> None:
        self._kind = kind
        key = f"{kind}_low"
        super().__init__(
            coordinator,
            key=key,
            platform="sensor",
            object_id=f"metal_{key}",
            device_id=coordinator.device_id,
            device_name=coordinator.device_name,
            translation_key=f"metal_{key}",
        )

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get(f"{self._kind}_low")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "date": (self.coordinator.data or {}).get(f"{self._kind}_low_date")
        }


class NewsItemSensor(GeneralInfoEntity, SensorEntity):
    _attr_icon = "mdi:newspaper"

    def __init__(self, coordinator: NewsCoordinator, index: int) -> None:
        self._index = index
        n = index + 1
        super().__init__(
            coordinator,
            key=f"item_{n}",
            platform="sensor",
            object_id=f"news_{n}",
            device_id=coordinator.device_id,
            device_name=coordinator.device_name,
            name=f"新闻{n}",
        )

    def _item(self) -> dict[str, Any]:
        items = (self.coordinator.data or {}).get("items") or []
        if self._index < len(items) and isinstance(items[self._index], dict):
            return items[self._index]
        return {}

    @property
    def native_value(self):
        return self._item().get("title")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        item = self._item()
        return {
            "url": item.get("url"),
            "time": item.get("time"),
            "index": self._index + 1,
        }


class StockSensor(GeneralInfoEntity, SensorEntity):
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:chart-line"

    def __init__(self, coordinator: StockCoordinator, code: str) -> None:
        self._code = code.lower()
        super().__init__(
            coordinator,
            key=self._code,
            platform="sensor",
            object_id=f"stock_{self._code}",
            device_id=coordinator.device_id,
            device_name=coordinator.device_name,
            name=self._code,
        )

    @property
    def native_value(self):
        item = (self.coordinator.data or {}).get(self._code) or {}
        return item.get("price")

    @property
    def name(self) -> str:
        item = (self.coordinator.data or {}).get(self._code) or {}
        return item.get("name") or self._code

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        item = (self.coordinator.data or {}).get(self._code) or {}
        return {
            "code": self._code,
            "change": item.get("change"),
            "change_pct": item.get("change_pct"),
            "open": item.get("open"),
            "high": item.get("high"),
            "low": item.get("low"),
            "prev_close": item.get("prev_close"),
            "volume": item.get("volume"),
            "amount": item.get("amount"),
            "date": item.get("date"),
            "time": item.get("time"),
        }


class MediaItemSensor(GeneralInfoEntity, SensorEntity):
    def __init__(
        self, coordinator: MediaCoordinator, category: str, index: int
    ) -> None:
        self._category = category
        self._index = index
        n = index + 1
        label = _MEDIA_LABEL.get(category, category)
        super().__init__(
            coordinator,
            key=f"{category}_{n}",
            platform="sensor",
            object_id=f"media_{category}_{n}",
            device_id=coordinator.device_id,
            device_name=coordinator.device_name,
            name=f"{label}{n}",
        )
        self._attr_icon = _MEDIA_ICON.get(category, "mdi:star")

    def _row(self) -> dict[str, Any]:
        block = (self.coordinator.data or {}).get(self._category) or {}
        items = block.get("items") or []
        if self._index < len(items) and isinstance(items[self._index], dict):
            return items[self._index]
        return {}

    @property
    def native_value(self):
        row = self._row()
        title = (row.get("title") or "").strip()
        if self._category == "music" and row.get("artists"):
            return f"{title} - {row.get('artists')}" if title else None
        return title or None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        row = self._row()
        attrs: dict[str, Any] = {
            "title": row.get("title"),
            "artists": row.get("artists"),
            "album": row.get("album"),
            "rating": row.get("rating"),
            "card_subtitle": row.get("card_subtitle"),
            "url": row.get("url"),
            "id": row.get("id"),
            "index": self._index + 1,
            "category": self._category,
        }
        release = row.get("release_date")
        if self._category == "movie":
            attrs["release_date"] = release
        elif self._category == "tv":
            attrs["premiere_date"] = release
        elif self._category == "music":
            attrs["release_date"] = release
        return attrs
