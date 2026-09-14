from __future__ import annotations

from typing import Any

from homeassistant.components.weather import Forecast, WeatherEntity, WeatherEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    UnitOfLength,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .apis.caiyun import _SKYCON
from .apis.qweather import _QW_CONDITION
from .apis.tianqi import map_condition
from .const import DOMAIN, PROVIDER_CAIYUN, PROVIDER_QWEATHER
from .coordinators.weather import WeatherCoordinator
from .entity import WeatherForecastEntity
from .weather_util import (
    day_precip,
    day_precip_prob,
    parse_forecast_datetime,
    to_float,
    visibility_km,
    wind_bearing,
    wind_speed_kmh,
)


def _day_condition(code: Any) -> str | None:
    if code is None:
        return None
    s = str(code).strip()
    if s in _SKYCON:
        return _SKYCON[s]
    if s in _QW_CONDITION:
        return _QW_CONDITION[s]
    return map_condition(s)


def _hour_condition(item: dict[str, Any]) -> str | None:
    return _day_condition(item.get("fa") or item.get("icon") or item.get("condition"))


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    entities: list[WeatherEntity] = []
    for coord in data.get("cities") or []:
        entities.append(CityWeather(coord))
    async_add_entities(entities)


class CityWeather(WeatherForecastEntity, WeatherEntity):
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_native_pressure_unit = UnitOfPressure.HPA
    _attr_native_wind_speed_unit = UnitOfSpeed.KILOMETERS_PER_HOUR
    _attr_native_visibility_unit = UnitOfLength.KILOMETERS
    _attr_native_precipitation_unit = UnitOfLength.MILLIMETERS
    _attr_supported_features = (
        WeatherEntityFeature.FORECAST_DAILY | WeatherEntityFeature.FORECAST_HOURLY
    )

    def __init__(self, coordinator: WeatherCoordinator) -> None:
        super().__init__(
            coordinator,
            key="condition",
            platform="weather",
            object_id=coordinator.slug,
            device_id=coordinator.device_id,
            device_name=coordinator.device_name,
        )
        self._attr_name = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        @callback
        def _forecast_listener() -> None:
            self.hass.async_create_task(
                self.async_update_listeners(("daily", "hourly"))
            )

        self.async_on_remove(self.coordinator.async_add_listener(_forecast_listener))
        if self.coordinator.data:
            self.hass.async_create_task(
                self.async_update_listeners(("daily", "hourly"))
            )

    @property
    def condition(self) -> str | None:
        return (self.coordinator.data or {}).get("condition")

    @property
    def native_temperature(self) -> float | None:
        return (self.coordinator.data or {}).get("temp")

    @property
    def native_apparent_temperature(self) -> float | None:
        return to_float((self.coordinator.data or {}).get("feels"))

    @property
    def humidity(self) -> float | None:
        return (self.coordinator.data or {}).get("humidity")

    @property
    def native_pressure(self) -> float | None:
        return to_float((self.coordinator.data or {}).get("pressure"))

    @property
    def native_wind_speed(self) -> float | None:
        data = self.coordinator.data or {}
        speed = data.get("wind_speed")
        if speed is not None:
            return to_float(speed)
        return wind_speed_kmh(data.get("wind_scale"))

    @property
    def wind_bearing(self) -> float | str | None:
        data = self.coordinator.data or {}
        bearing = wind_bearing(data.get("wind_bearing"))
        if bearing is not None:
            return bearing
        return wind_bearing(data.get("wind_dir"))

    @property
    def native_visibility(self) -> float | None:
        return visibility_km((self.coordinator.data or {}).get("visibility"))

    @property
    def attribution(self) -> str:
        provider = getattr(self.coordinator, "provider", None)
        if provider == PROVIDER_QWEATHER:
            return "QWeather"
        if provider == PROVIDER_CAIYUN:
            return "Caiyun"
        return "weather.com.cn"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        attrs: dict[str, Any] = {}
        indices = data.get("indices") or {}
        if isinstance(indices, dict) and indices:
            attrs["indices"] = indices
        daily = self._forecast_daily_list()
        if not daily:
            return attrs
        compat: list[dict[str, Any]] = []
        for item in daily:
            row: dict[str, Any] = {
                "datetime": item.get("datetime"),
                "condition": item.get("condition"),
                "temperature": item.get("native_temperature"),
                "templow": item.get("native_templow"),
            }
            if item.get("humidity") is not None:
                row["humidity"] = item.get("humidity")
            if item.get("native_precipitation") is not None:
                row["precipitation"] = item.get("native_precipitation")
            if item.get("precipitation_probability") is not None:
                row["precipitation_probability"] = item.get(
                    "precipitation_probability"
                )
            compat.append(row)
        attrs["forecast"] = compat
        return attrs

    def _forecast_daily_list(self) -> list[Forecast]:
        raw = (self.coordinator.data or {}).get("forecast") or []
        days = int(self.coordinator.instance.get("forecast_days") or 7)
        out: list[Forecast] = []
        now = dt_util.now()
        for day in raw[:days]:
            if not isinstance(day, dict):
                continue
            when = parse_forecast_datetime(
                day.get("fi") or day.get("fxDate") or day.get("date"), now
            )
            item: Forecast = {
                "datetime": when.isoformat(),
                "condition": _day_condition(
                    day.get("fa") or day.get("iconDay") or day.get("icon")
                )
                or "cloudy",
                "native_temperature": to_float(
                    day.get("fc") or day.get("tempMax") or day.get("temp")
                ),
                "native_templow": to_float(day.get("fd") or day.get("tempMin")),
                "humidity": to_float(day.get("fn") or day.get("humidity")),
            }
            precip = day_precip(day)
            if precip is not None:
                item["native_precipitation"] = precip
            pop = day_precip_prob(day)
            if pop is not None:
                item["precipitation_probability"] = pop
            out.append(item)
        return out

    def _forecast_hourly_list(self) -> list[Forecast]:
        raw = (self.coordinator.data or {}).get("hourly") or []
        out: list[Forecast] = []
        now = dt_util.now()
        for hour in raw[:24]:
            if not isinstance(hour, dict):
                continue
            when = _parse_hour_datetime(
                hour.get("fxTime") or hour.get("datetime"), now
            )
            item: Forecast = {
                "datetime": when.isoformat(),
                "condition": _hour_condition(hour) or "cloudy",
                "native_temperature": to_float(
                    hour.get("temp") or hour.get("fc")
                ),
                "humidity": to_float(hour.get("humidity") or hour.get("fn")),
            }
            precip = day_precip(hour)
            if precip is not None:
                item["native_precipitation"] = precip
            pop = day_precip_prob(hour)
            if pop is not None:
                item["precipitation_probability"] = pop
            out.append(item)
        return out

    async def async_forecast_daily(self) -> list[Forecast] | None:
        return self._forecast_daily_list() or None

    async def async_forecast_hourly(self) -> list[Forecast] | None:
        return self._forecast_hourly_list() or None


def _parse_hour_datetime(val: Any, now: Any) -> Any:
    from datetime import datetime

    from homeassistant.util import dt as dt_util

    s = str(val or "").strip()
    if not s:
        return now
    try:
        if "T" in s or "+" in s or s.endswith("Z"):
            parsed = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                return now.replace(
                    year=parsed.year,
                    month=parsed.month,
                    day=parsed.day,
                    hour=parsed.hour,
                    minute=parsed.minute,
                    second=0,
                    microsecond=0,
                )
            return dt_util.as_local(parsed)
        if len(s) >= 16 and s[4] == "-" and s[10] in (" ", "T"):
            parsed = datetime.fromisoformat(s[:16].replace(" ", "T"))
            return now.replace(
                year=parsed.year,
                month=parsed.month,
                day=parsed.day,
                hour=parsed.hour,
                minute=parsed.minute,
                second=0,
                microsecond=0,
            )
        if "/" in s and " " in s:
            parsed = datetime.strptime(s[:16], "%Y/%m/%d %H:%M")
            return now.replace(
                year=parsed.year,
                month=parsed.month,
                day=parsed.day,
                hour=parsed.hour,
                minute=parsed.minute,
                second=0,
                microsecond=0,
            )
    except (TypeError, ValueError):
        pass
    return now
