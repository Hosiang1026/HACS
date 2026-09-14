from __future__ import annotations

import asyncio
from datetime import datetime, time, timedelta
import logging
from typing import Any, Callable
from uuid import uuid4

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_change,
)
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util
from homeassistant.util import slugify

from .const import (
    ACTION_CLOSE,
    ACTION_NONE,
    ACTION_OPEN,
    ACTION_TOGGLE,
    ACTION_TURN_OFF,
    ACTION_TURN_ON,
    CONDITION_AND,
    CONDITION_OR,
    CONF_BROADCAST_FAIL,
    CONF_BROADCAST_SUCCESS,
    CONF_COND_1_ENTITY,
    CONF_COND_1_STATE,
    CONF_COND_2_ENTITY,
    CONF_COND_2_STATE,
    CONF_COND_3_ENTITY,
    CONF_COND_3_STATE,
    CONF_CONDITION_LOGIC,
    CONF_CONDITIONS,
    CONF_COOLDOWN,
    CONF_DELAY,
    CONF_VERIFY_DELAY,
    CONF_MESSAGE,
    CONF_MESSAGE_FAIL,
    CONF_NAME,
    CONF_NUMERIC_THRESHOLD,
    CONF_RULE_ENABLED,
    CONF_RULE_ID,
    CONF_RULE_NAME,
    CONF_RULE_ROOM,
    CONF_RULES,
    CONF_TARGET_ACTION,
    CONF_TARGET_ENTITIES,
    CONF_TIME_AFTER,
    CONF_TIME_BEFORE,
    CONF_TRIGGER_ENTITY,
    CONF_TRIGGER_FROM,
    CONF_TRIGGER_PERSON,
    CONF_TRIGGER_TIME,
    CONF_TRIGGER_TO,
    CONF_TRIGGER_TYPE,
    CONF_TTS_DEVICES,
    CONF_WEEKDAYS,
    DEFAULT_BROADCAST_FAIL,
    DEFAULT_BROADCAST_SUCCESS,
    DEFAULT_CONDITION_LOGIC,
    DEFAULT_COOLDOWN,
    DEFAULT_DELAY,
    DEFAULT_VERIFY_DELAY,
    DOMAIN,
    STORAGE_VERSION,
    TRIGGER_NUMERIC_ABOVE,
    TRIGGER_NUMERIC_BELOW,
    TRIGGER_STATE,
    TRIGGER_TIME,
    TRIGGER_ZONE_ENTER,
    TRIGGER_ZONE_LEAVE,
    WEEKDAY_INDEX,
    WEEKDAYS,
)

_LOGGER = logging.getLogger(__name__)

_DOMAIN_SERVICE = {
    ACTION_TURN_ON: {
        "switch": ("switch", "turn_on"),
        "light": ("light", "turn_on"),
        "input_boolean": ("input_boolean", "turn_on"),
        "fan": ("fan", "turn_on"),
        "climate": ("climate", "turn_on"),
        "media_player": ("media_player", "turn_on"),
        "vacuum": ("vacuum", "start"),
        "script": ("script", "turn_on"),
        "scene": ("scene", "turn_on"),
        "cover": ("cover", "open_cover"),
    },
    ACTION_TURN_OFF: {
        "switch": ("switch", "turn_off"),
        "light": ("light", "turn_off"),
        "input_boolean": ("input_boolean", "turn_off"),
        "fan": ("fan", "turn_off"),
        "climate": ("climate", "turn_off"),
        "media_player": ("media_player", "turn_off"),
        "vacuum": ("vacuum", "return_to_base"),
        "cover": ("cover", "close_cover"),
    },
    ACTION_TOGGLE: {
        "switch": ("switch", "toggle"),
        "light": ("light", "toggle"),
        "input_boolean": ("input_boolean", "toggle"),
        "fan": ("fan", "toggle"),
        "media_player": ("media_player", "toggle"),
        "cover": ("cover", "toggle"),
    },
    ACTION_OPEN: {
        "cover": ("cover", "open_cover"),
    },
    ACTION_CLOSE: {
        "cover": ("cover", "close_cover"),
    },
}

_ON_DOMAINS = {
    "switch",
    "light",
    "input_boolean",
    "fan",
}
_OFF_DOMAINS = _ON_DOMAINS


def _expected_state(
    entity_id: str, action: str, before: str | None
) -> str | set[str] | None:
    domain = entity_id.split(".", 1)[0]
    if domain in ("scene", "script"):
        return None
    if action == ACTION_TOGGLE:
        if before == "on":
            return "off"
        if before == "off":
            return "on"
        if before == "open":
            return "closed"
        if before == "closed":
            return "open"
        return None
    if action == ACTION_TURN_ON:
        if domain == "cover":
            return {"open", "opening"}
        if domain == "vacuum":
            return {"cleaning", "returning", "on"}
        if domain == "climate":
            return None
        if domain == "media_player":
            return {"on", "playing", "idle", "paused"}
        if domain in _ON_DOMAINS:
            return "on"
        return None
    if action == ACTION_TURN_OFF:
        if domain == "cover":
            return {"closed", "closing"}
        if domain == "vacuum":
            return {"docked", "idle", "off"}
        if domain == "climate":
            return "off"
        if domain == "media_player":
            return {"off", "standby", "idle"}
        if domain in _OFF_DOMAINS:
            return "off"
        return None
    if action == ACTION_OPEN:
        return {"open", "opening"}
    if action == ACTION_CLOSE:
        return {"closed", "closing"}
    return None


_COND_SLOTS = (
    (CONF_COND_1_ENTITY, CONF_COND_1_STATE),
    (CONF_COND_2_ENTITY, CONF_COND_2_STATE),
    (CONF_COND_3_ENTITY, CONF_COND_3_STATE),
)


def _as_list(value: Any) -> list:
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    return list(value)


def _parse_time(value: str | None) -> time | None:
    if not value:
        return None
    parts = str(value).split(":")
    if len(parts) < 2:
        return None
    try:
        hour = int(parts[0])
        minute = int(parts[1])
        second = int(parts[2]) if len(parts) > 2 else 0
        return time(hour, minute, second)
    except (TypeError, ValueError):
        return None


def _in_window(now_t: time, start: time | None, end: time | None) -> bool:
    if start is None and end is None:
        return True
    if start is not None and end is not None:
        if start <= end:
            return start <= now_t <= end
        return now_t >= start or now_t <= end
    if start is not None:
        return now_t >= start
    return now_t <= end


def _int_or(value: Any, default: int) -> int:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float_or(value: Any, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _build_conditions(raw: dict[str, Any]) -> list[dict[str, str]]:
    conditions: list[dict[str, str]] = []
    has_slot = any(raw.get(ek) for ek, _sk in _COND_SLOTS)
    if has_slot:
        for ek, sk in _COND_SLOTS:
            eid = raw.get(ek)
            if not eid:
                continue
            conditions.append(
                {
                    "entity_id": str(eid).strip(),
                    "state": str(raw.get(sk) or "").strip(),
                }
            )
        return conditions
    existing = raw.get(CONF_CONDITIONS)
    if isinstance(existing, list):
        for item in existing:
            if not isinstance(item, dict):
                continue
            eid = (item.get("entity_id") or "").strip()
            if not eid:
                continue
            conditions.append(
                {
                    "entity_id": eid,
                    "state": str(item.get("state") or "").strip(),
                }
            )
    return conditions


def conditions_to_slots(conditions: list[dict[str, str]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for idx, (ek, sk) in enumerate(_COND_SLOTS):
        if idx < len(conditions):
            out[ek] = conditions[idx].get("entity_id") or None
            out[sk] = conditions[idx].get("state") or ""
        else:
            out[ek] = None
            out[sk] = ""
    return out


def normalize_rule(raw: dict[str, Any]) -> dict[str, Any]:
    conditions = _build_conditions(raw)
    weekdays = [d for d in _as_list(raw.get(CONF_WEEKDAYS)) if d in WEEKDAYS]
    ttype = raw.get(CONF_TRIGGER_TYPE) or TRIGGER_STATE
    entity = raw.get(CONF_TRIGGER_ENTITY) or ""
    person = raw.get(CONF_TRIGGER_PERSON) or ""
    if ttype == TRIGGER_TIME:
        entity = ""
        person = ""
    elif ttype not in (TRIGGER_ZONE_ENTER, TRIGGER_ZONE_LEAVE):
        person = ""
    return {
        CONF_RULE_ID: raw.get(CONF_RULE_ID) or str(uuid4()),
        CONF_RULE_NAME: raw.get(CONF_RULE_NAME) or "规则",
        CONF_RULE_ROOM: (raw.get(CONF_RULE_ROOM) or "").strip(),
        CONF_RULE_ENABLED: raw.get(CONF_RULE_ENABLED, True),
        CONF_TRIGGER_ENTITY: entity,
        CONF_TRIGGER_PERSON: person,
        CONF_TRIGGER_TYPE: ttype,
        CONF_TRIGGER_TO: raw.get(CONF_TRIGGER_TO) or "",
        CONF_TRIGGER_FROM: raw.get(CONF_TRIGGER_FROM) or "",
        CONF_TRIGGER_TIME: raw.get(CONF_TRIGGER_TIME) or "",
        CONF_WEEKDAYS: weekdays,
        CONF_NUMERIC_THRESHOLD: _float_or(raw.get(CONF_NUMERIC_THRESHOLD)),
        CONF_CONDITION_LOGIC: raw.get(CONF_CONDITION_LOGIC) or DEFAULT_CONDITION_LOGIC,
        CONF_CONDITIONS: conditions,
        CONF_TIME_AFTER: raw.get(CONF_TIME_AFTER) or "",
        CONF_TIME_BEFORE: raw.get(CONF_TIME_BEFORE) or "",
        CONF_TARGET_ENTITIES: _as_list(raw.get(CONF_TARGET_ENTITIES)),
        CONF_TARGET_ACTION: raw.get(CONF_TARGET_ACTION) or ACTION_NONE,
        CONF_MESSAGE: raw.get(CONF_MESSAGE) or "",
        CONF_MESSAGE_FAIL: raw.get(CONF_MESSAGE_FAIL) or "",
        CONF_BROADCAST_SUCCESS: bool(
            raw.get(CONF_BROADCAST_SUCCESS, DEFAULT_BROADCAST_SUCCESS)
        ),
        CONF_BROADCAST_FAIL: bool(raw.get(CONF_BROADCAST_FAIL, DEFAULT_BROADCAST_FAIL)),
        CONF_COOLDOWN: _int_or(raw.get(CONF_COOLDOWN), DEFAULT_COOLDOWN),
        CONF_DELAY: _int_or(raw.get(CONF_DELAY), DEFAULT_DELAY),
        CONF_VERIFY_DELAY: _int_or(raw.get(CONF_VERIFY_DELAY), DEFAULT_VERIFY_DELAY),
    }


def rule_slug(rule: dict[str, Any]) -> str:
    slug = slugify(rule.get(CONF_RULE_NAME) or "rule")
    if slug:
        return slug
    return (rule.get(CONF_RULE_ID) or "rule")[:8]


def rule_entity_key(rule: dict[str, Any]) -> str:
    slug = rule_slug(rule)
    rid = (rule.get(CONF_RULE_ID) or "")[:8]
    if slug:
        return f"{slug}_{rid}"
    return rid or "rule"


def rule_trigger_entity_text(rule: dict[str, Any]) -> str:
    ttype = rule.get(CONF_TRIGGER_TYPE) or TRIGGER_STATE
    if ttype == TRIGGER_TIME:
        return "—"
    if ttype in (TRIGGER_ZONE_ENTER, TRIGGER_ZONE_LEAVE):
        person = (rule.get(CONF_TRIGGER_PERSON) or "").strip()
        zone = (rule.get(CONF_TRIGGER_ENTITY) or "").strip()
        if person and zone:
            return f"{person} / {zone}"
        return person or zone or "—"
    return (rule.get(CONF_TRIGGER_ENTITY) or "").strip() or "—"


def rule_trigger_condition_text(rule: dict[str, Any]) -> str:
    ttype = rule.get(CONF_TRIGGER_TYPE) or TRIGGER_STATE
    if ttype == TRIGGER_TIME:
        text = f"定时 {rule.get(CONF_TRIGGER_TIME) or ''}".strip()
        days = _as_list(rule.get(CONF_WEEKDAYS))
        if days:
            text = f"{text} ({','.join(days)})"
        return text or "定时"
    if ttype == TRIGGER_ZONE_ENTER:
        return "进入区域"
    if ttype == TRIGGER_ZONE_LEAVE:
        return "离开区域"
    if ttype == TRIGGER_STATE:
        parts: list[str] = []
        if rule.get(CONF_TRIGGER_FROM):
            parts.append(f"从 {rule[CONF_TRIGGER_FROM]}")
        if rule.get(CONF_TRIGGER_TO):
            parts.append(f"到 {rule[CONF_TRIGGER_TO]}")
        return " ".join(parts) if parts else "状态变化"
    if ttype == TRIGGER_NUMERIC_ABOVE:
        return f"数值上限为{rule.get(CONF_NUMERIC_THRESHOLD, 0)}"
    if ttype == TRIGGER_NUMERIC_BELOW:
        return f"数值下限为{rule.get(CONF_NUMERIC_THRESHOLD, 0)}"
    return "—"


def rule_extra_condition_text(rule: dict[str, Any]) -> str:
    parts: list[str] = []
    conditions = rule.get(CONF_CONDITIONS) or []
    if conditions:
        logic = (
            " 且 "
            if (rule.get(CONF_CONDITION_LOGIC) or CONDITION_AND) != CONDITION_OR
            else " 或 "
        )
        cond_parts: list[str] = []
        for item in conditions:
            eid = (item.get("entity_id") or "").strip()
            if not eid:
                continue
            state = (item.get("state") or "").strip()
            cond_parts.append(f"{eid}={state}" if state else eid)
        if cond_parts:
            parts.append(logic.join(cond_parts))
    after = rule.get(CONF_TIME_AFTER)
    before = rule.get(CONF_TIME_BEFORE)
    if after or before:
        window: list[str] = []
        if after:
            window.append(f"≥{after}")
        if before:
            window.append(f"≤{before}")
        parts.append("时间窗 " + " ".join(window))
    days = _as_list(rule.get(CONF_WEEKDAYS))
    if days and (rule.get(CONF_TRIGGER_TYPE) or TRIGGER_STATE) != TRIGGER_TIME:
        parts.append("星期 " + ",".join(days))
    return "；".join(parts) if parts else "无"


def _rule_runtime(
    rule: dict[str, Any], stored: dict[str, Any] | None = None
) -> dict[str, Any]:
    stored = stored or {}
    enabled = (
        bool(stored["enabled"])
        if "enabled" in stored
        else bool(rule.get(CONF_RULE_ENABLED, True))
    )
    return {
        "trigger_entity": rule_trigger_entity_text(rule),
        "trigger_condition": rule_trigger_condition_text(rule),
        "extra_condition": rule_extra_condition_text(rule),
        "exec_state": stored.get("exec_state") or "",
        "exec_time": stored.get("exec_time"),
        "enabled": enabled,
    }


class SceneCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, _LOGGER, name=f"{DOMAIN}_{entry.entry_id}")
        self.entry = entry
        self._unsub_state = None
        self._unsub_times: list[Callable[[], None]] = []
        self._last_fire: dict[str, datetime] = {}
        self._enabled = True
        self._stats: dict[str, Any] = {}
        self._store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self.data: dict[str, Any] = {
            "enabled": True,
            "rules": {},
        }

    def _build_rules_data(
        self, stored_rules: dict[str, Any] | None = None
    ) -> dict[str, dict[str, Any]]:
        stored_rules = stored_rules or {}
        return {
            rule[CONF_RULE_ID]: _rule_runtime(
                rule, stored_rules.get(rule[CONF_RULE_ID])
            )
            for rule in self.rules
        }

    def _normalize_stats(self, raw: dict[str, Any] | None) -> dict[str, Any]:
        raw = raw or {}
        return {
            "today": str(raw.get("today") or ""),
            "today_success": _int_or(raw.get("today_success"), 0),
            "today_fail": _int_or(raw.get("today_fail"), 0),
        }

    def _today_stats(self) -> tuple[int, int]:
        today = dt_util.now().date().isoformat()
        if self._stats.get("today") != today:
            return 0, 0
        return _int_or(self._stats.get("today_success"), 0), _int_or(
            self._stats.get("today_fail"), 0
        )

    def _stat_counts(self) -> dict[str, int]:
        rules = self.rules
        enabled = sum(1 for r in rules if self.is_rule_enabled(r[CONF_RULE_ID]))
        today_success, today_fail = self._today_stats()
        return {
            "enabled_count": enabled,
            "disabled_count": len(rules) - enabled,
            "today_success": today_success,
            "today_fail": today_fail,
        }

    def _sync_data(self, rules_data: dict[str, dict[str, Any]] | None = None) -> None:
        if rules_data is None:
            rules_data = self.data.get("rules") or {}
        self.data = {
            "enabled": self._enabled,
            **self._stat_counts(),
            "rules": rules_data,
        }

    def _record_exec(self, ok: bool) -> None:
        today = dt_util.now().date().isoformat()
        stats = dict(self._stats)
        if stats.get("today") != today:
            stats["today"] = today
            stats["today_success"] = 0
            stats["today_fail"] = 0
        if ok:
            stats["today_success"] = _int_or(stats.get("today_success"), 0) + 1
        else:
            stats["today_fail"] = _int_or(stats.get("today_fail"), 0) + 1
        self._stats = stats

    @property
    def scene_name(self) -> str:
        return self.entry.data.get(CONF_NAME) or self.entry.title or "智能场景"

    @property
    def entity_prefix(self) -> str:
        slug = slugify(self.scene_name)
        if slug:
            return slug
        return f"scene_{self.entry.entry_id[:8]}"

    def cfg(self, key: str, default: Any = None) -> Any:
        if key in self.entry.options:
            return self.entry.options[key]
        return self.entry.data.get(key, default)

    @property
    def rules(self) -> list[dict[str, Any]]:
        return [normalize_rule(r) for r in _as_list(self.cfg(CONF_RULES, []))]

    @property
    def tts_devices(self) -> list[str]:
        return _as_list(self.cfg(CONF_TTS_DEVICES, []))

    async def async_setup(self) -> None:
        stored = await self._store.async_load() or {}
        self._enabled = bool(stored.get("enabled", True))
        self._stats = self._normalize_stats(stored.get("stats"))
        self._sync_data(self._build_rules_data(stored.get("rules")))
        self._listen()
        self.async_set_updated_data(self.data)

    async def async_shutdown(self) -> None:
        if self._unsub_state:
            self._unsub_state()
            self._unsub_state = None
        for unsub in self._unsub_times:
            unsub()
        self._unsub_times = []

    def _listen(self) -> None:
        if self._unsub_state:
            self._unsub_state()
            self._unsub_state = None
        for unsub in self._unsub_times:
            unsub()
        self._unsub_times = []

        for rule in self.rules:
            ttype = rule.get(CONF_TRIGGER_TYPE) or TRIGGER_STATE
            if ttype == TRIGGER_TIME:
                if not rule.get(CONF_TRIGGER_TIME):
                    _LOGGER.warning(
                        "time rule missing trigger_time: %s",
                        rule.get(CONF_RULE_NAME),
                    )
                continue
            if ttype in (TRIGGER_ZONE_ENTER, TRIGGER_ZONE_LEAVE):
                if not rule.get(CONF_TRIGGER_PERSON) or not rule.get(
                    CONF_TRIGGER_ENTITY
                ):
                    _LOGGER.warning(
                        "zone rule missing person/zone: %s",
                        rule.get(CONF_RULE_NAME),
                    )
                continue
            if not rule.get(CONF_TRIGGER_ENTITY):
                _LOGGER.warning(
                    "rule missing trigger_entity: %s",
                    rule.get(CONF_RULE_NAME),
                )

        entities: set[str] = set()
        for r in self.rules:
            ttype = r.get(CONF_TRIGGER_TYPE) or TRIGGER_STATE
            if ttype == TRIGGER_TIME:
                continue
            if ttype in (TRIGGER_ZONE_ENTER, TRIGGER_ZONE_LEAVE):
                if r.get(CONF_TRIGGER_PERSON):
                    entities.add(r[CONF_TRIGGER_PERSON])
            elif r.get(CONF_TRIGGER_ENTITY):
                entities.add(r[CONF_TRIGGER_ENTITY])
        if entities:
            self._unsub_state = async_track_state_change_event(
                self.hass, list(entities), self._on_state_change
            )

        for rule in self.rules:
            if rule.get(CONF_TRIGGER_TYPE) != TRIGGER_TIME:
                continue
            trigger_t = _parse_time(rule.get(CONF_TRIGGER_TIME) or None)
            if trigger_t is None:
                continue
            rid = rule[CONF_RULE_ID]

            @callback
            def _time_fire(_now: datetime, rule_id: str = rid) -> None:
                matched = next(
                    (r for r in self.rules if r.get(CONF_RULE_ID) == rule_id), None
                )
                if matched is None:
                    return
                self.hass.async_create_task(self._handle_time_rule(matched))

            self._unsub_times.append(
                async_track_time_change(
                    self.hass,
                    _time_fire,
                    hour=trigger_t.hour,
                    minute=trigger_t.minute,
                    second=trigger_t.second,
                )
            )

    async def _save(self) -> None:
        rules_store = {}
        for rid, data in (self.data.get("rules") or {}).items():
            item: dict[str, Any] = {
                "exec_state": data.get("exec_state") or "",
                "exec_time": data.get("exec_time"),
            }
            if "enabled" in data:
                item["enabled"] = bool(data["enabled"])
            rules_store[rid] = item
        await self._store.async_save(
            {
                "enabled": self._enabled,
                "stats": self._stats,
                "rules": rules_store,
            }
        )

    def is_rule_enabled(self, rule_id: str) -> bool:
        rule_data = (self.data.get("rules") or {}).get(rule_id)
        if rule_data and "enabled" in rule_data:
            return bool(rule_data["enabled"])
        rule = next((r for r in self.rules if r[CONF_RULE_ID] == rule_id), None)
        if rule:
            return bool(rule.get(CONF_RULE_ENABLED, True))
        return False

    async def async_set_rule_enabled(self, rule_id: str, value: bool) -> None:
        rules_data = dict(self.data.get("rules") or {})
        current = dict(rules_data.get(rule_id) or {})
        rule = next((r for r in self.rules if r[CONF_RULE_ID] == rule_id), None)
        if rule:
            current.setdefault("trigger_entity", rule_trigger_entity_text(rule))
            current.setdefault("trigger_condition", rule_trigger_condition_text(rule))
            current.setdefault("extra_condition", rule_extra_condition_text(rule))
            current.setdefault("exec_state", "")
        current["enabled"] = value
        rules_data[rule_id] = current
        self._sync_data(rules_data)
        await self._save()
        self.async_set_updated_data(self.data)

    async def async_manual_trigger(self, rule_id: str) -> None:
        if not self._enabled:
            return
        if not self.is_rule_enabled(rule_id):
            return
        rule = next((r for r in self.rules if r[CONF_RULE_ID] == rule_id), None)
        if rule is None:
            return
        await self._execute_rule(rule, dt_util.now(), manual=True)

    async def async_set_enabled(self, value: bool) -> None:
        self._enabled = value
        self._sync_data()
        await self._save()
        self.async_set_updated_data(self.data)

    @callback
    def _on_state_change(self, event: Event) -> None:
        self.hass.async_create_task(self._handle_event(event))

    async def _handle_time_rule(self, rule: dict[str, Any]) -> None:
        if not self._enabled:
            return
        if not self.is_rule_enabled(rule[CONF_RULE_ID]):
            return
        now = dt_util.now()
        if not self._match_weekdays(rule, now):
            return
        if not self._match_conditions(rule):
            return
        if not self._match_time_window(rule, now.time()):
            return
        if not self._pass_cooldown(rule, now):
            return
        await self._execute_rule(rule, now)

    async def _handle_event(self, event: Event) -> None:
        if not self._enabled:
            return
        entity_id = event.data.get("entity_id")
        old_state = event.data.get("old_state")
        new_state = event.data.get("new_state")
        if new_state is None:
            return
        old_val = old_state.state if old_state else None
        new_val = new_state.state
        now = dt_util.now()
        for rule in self.rules:
            ttype = rule.get(CONF_TRIGGER_TYPE) or TRIGGER_STATE
            if ttype == TRIGGER_TIME:
                continue
            if not self.is_rule_enabled(rule[CONF_RULE_ID]):
                continue
            if ttype in (TRIGGER_ZONE_ENTER, TRIGGER_ZONE_LEAVE):
                if (rule.get(CONF_TRIGGER_PERSON) or "") != entity_id:
                    continue
                if not self._match_zone_trigger(rule, old_state, new_state):
                    continue
            else:
                if old_val == new_val:
                    continue
                trigger_entity = rule.get(CONF_TRIGGER_ENTITY) or ""
                if not trigger_entity or trigger_entity != entity_id:
                    continue
                if not self._match_trigger(rule, old_val, new_val):
                    continue
            if not self._match_weekdays(rule, now):
                continue
            if not self._match_conditions(rule):
                continue
            if not self._match_time_window(rule, now.time()):
                continue
            if not self._pass_cooldown(rule, now):
                continue
            self.hass.async_create_task(self._execute_rule(rule, now))

    def _pass_cooldown(self, rule: dict[str, Any], now: datetime) -> bool:
        rid = rule[CONF_RULE_ID]
        cooldown = _int_or(rule.get(CONF_COOLDOWN), 0)
        last = self._last_fire.get(rid)
        if last and cooldown > 0 and now - last < timedelta(seconds=cooldown):
            return False
        self._last_fire[rid] = now
        return True

    def _match_weekdays(self, rule: dict[str, Any], now: datetime) -> bool:
        days = _as_list(rule.get(CONF_WEEKDAYS))
        if not days:
            return True
        return now.weekday() in {
            WEEKDAY_INDEX[d] for d in days if d in WEEKDAY_INDEX
        }

    def _person_in_zone(self, person_state: Any, zone_entity_id: str) -> bool:
        if person_state is None:
            return False
        pstate = person_state.state
        if pstate in ("unknown", "unavailable"):
            return False
        zone_state = self.hass.states.get(zone_entity_id)
        if zone_state is None:
            return False
        if zone_entity_id == "zone.home":
            return pstate == "home"
        return pstate == zone_state.name

    def _match_zone_trigger(
        self, rule: dict[str, Any], old_state: Any, new_state: Any
    ) -> bool:
        zone_entity = (rule.get(CONF_TRIGGER_ENTITY) or "").strip()
        if not zone_entity or new_state is None:
            return False
        if new_state.state in ("unknown", "unavailable"):
            return False
        if old_state is not None and old_state.state in ("unknown", "unavailable"):
            return False
        was_in = self._person_in_zone(old_state, zone_entity)
        now_in = self._person_in_zone(new_state, zone_entity)
        ttype = rule.get(CONF_TRIGGER_TYPE)
        if ttype == TRIGGER_ZONE_ENTER:
            return (not was_in) and now_in
        if ttype == TRIGGER_ZONE_LEAVE:
            return was_in and (not now_in)
        return False

    def _match_trigger(
        self, rule: dict[str, Any], old_val: str | None, new_val: str
    ) -> bool:
        ttype = rule.get(CONF_TRIGGER_TYPE) or TRIGGER_STATE
        if ttype == TRIGGER_STATE:
            to_val = (rule.get(CONF_TRIGGER_TO) or "").strip()
            from_val = (rule.get(CONF_TRIGGER_FROM) or "").strip()
            if to_val and new_val != to_val:
                return False
            if from_val and (old_val or "") != from_val:
                return False
            return True
        try:
            new_num = float(new_val)
            old_num = (
                float(old_val)
                if old_val not in (None, "unknown", "unavailable")
                else None
            )
        except (TypeError, ValueError):
            return False
        threshold = _float_or(rule.get(CONF_NUMERIC_THRESHOLD))
        if ttype == TRIGGER_NUMERIC_ABOVE:
            if new_num <= threshold:
                return False
            return old_num is None or old_num <= threshold
        if ttype == TRIGGER_NUMERIC_BELOW:
            if new_num >= threshold:
                return False
            return old_num is None or old_num >= threshold
        return False

    def _match_conditions(self, rule: dict[str, Any]) -> bool:
        conditions = rule.get(CONF_CONDITIONS) or []
        if not conditions:
            return True
        results: list[bool] = []
        for item in conditions:
            eid = (item.get("entity_id") or "").strip()
            if not eid:
                continue
            state = self.hass.states.get(eid)
            if state is None:
                results.append(False)
                continue
            expected = (item.get("state") or "").strip()
            if not expected:
                results.append(True)
            else:
                results.append(state.state == expected)
        if not results:
            return True
        logic = rule.get(CONF_CONDITION_LOGIC) or CONDITION_AND
        if logic == CONDITION_OR:
            return any(results)
        return all(results)

    def _match_time_window(self, rule: dict[str, Any], now_t: time) -> bool:
        after = _parse_time(rule.get(CONF_TIME_AFTER) or None)
        before = _parse_time(rule.get(CONF_TIME_BEFORE) or None)
        return _in_window(now_t, after, before)

    async def _execute_rule(
        self, rule: dict[str, Any], now: datetime, manual: bool = False
    ) -> None:
        delay = 0 if manual else _int_or(rule.get(CONF_DELAY), 0)
        if delay > 0:
            await asyncio.sleep(delay)
        if not self._enabled:
            return
        action = rule.get(CONF_TARGET_ACTION) or ACTION_NONE
        targets = _as_list(rule.get(CONF_TARGET_ENTITIES))
        ok = True
        before_states: dict[str, str | None] = {}
        if action != ACTION_NONE and targets:
            for eid in targets:
                st = self.hass.states.get(eid)
                before_states[eid] = st.state if st else None
                if not await self._call_action(eid, action):
                    ok = False
            verify_delay = _int_or(rule.get(CONF_VERIFY_DELAY), DEFAULT_VERIFY_DELAY)
            if verify_delay > 0:
                await asyncio.sleep(verify_delay)
            if not self._enabled:
                return
            for eid in targets:
                if not self._verify_target(eid, action, before_states.get(eid)):
                    _LOGGER.warning(
                        "state verify failed: %s action=%s", eid, action
                    )
                    ok = False
        elif action != ACTION_NONE and not targets:
            _LOGGER.warning(
                "scene rule %s has action %s but no targets",
                rule.get(CONF_RULE_NAME),
                action,
            )
            ok = False
        rule_name = rule.get(CONF_RULE_NAME) or "规则"
        exec_state = "成功" if ok else "失败"
        if ok:
            message = (rule.get(CONF_MESSAGE) or "").strip() or f"{rule_name}执行成功"
            if rule.get(CONF_BROADCAST_SUCCESS):
                await self._broadcast(message)
        else:
            _LOGGER.warning("scene rule failed: %s", rule_name)
            message = (rule.get(CONF_MESSAGE_FAIL) or "").strip() or f"{rule_name}执行失败"
            if rule.get(CONF_BROADCAST_FAIL):
                await self._broadcast(message)
        rid = rule[CONF_RULE_ID]
        rules_data = dict(self.data.get("rules") or {})
        current = dict(rules_data.get(rid) or {})
        current.update(
            {
                "trigger_entity": rule_trigger_entity_text(rule),
                "trigger_condition": rule_trigger_condition_text(rule),
                "extra_condition": rule_extra_condition_text(rule),
                "exec_state": exec_state,
                "exec_time": now.strftime("%Y-%m-%d %H:%M:%S"),
            }
        )
        if "enabled" not in current:
            current["enabled"] = self.is_rule_enabled(rid)
        rules_data[rid] = current
        self._record_exec(ok)
        self._sync_data(rules_data)
        await self._save()
        self.async_set_updated_data(self.data)

    def _verify_target(
        self, entity_id: str, action: str, before: str | None
    ) -> bool:
        state = self.hass.states.get(entity_id)
        if state is None:
            return False
        current = state.state
        if current in ("unavailable", "unknown"):
            return False
        domain = entity_id.split(".", 1)[0]
        if domain == "climate" and action == ACTION_TURN_ON:
            return current != "off"
        expected = _expected_state(entity_id, action, before)
        if expected is None:
            return True
        if isinstance(expected, (set, list, tuple)):
            return current in expected
        return current == expected

    async def _call_action(self, entity_id: str, action: str) -> bool:
        if not isinstance(entity_id, str) or "." not in entity_id:
            return False
        domain = entity_id.split(".", 1)[0]
        mapping = _DOMAIN_SERVICE.get(action, {})
        pair = mapping.get(domain)
        if not pair:
            if action == ACTION_TURN_ON:
                pair = (domain, "turn_on")
            elif action == ACTION_TURN_OFF:
                pair = (domain, "turn_off")
            elif action == ACTION_TOGGLE:
                pair = (domain, "toggle")
            else:
                _LOGGER.warning("unsupported action %s for %s", action, entity_id)
                return False
        svc_domain, svc = pair
        try:
            await self.hass.services.async_call(
                svc_domain,
                svc,
                {"entity_id": entity_id},
                blocking=True,
            )
            return True
        except Exception:
            _LOGGER.exception("action failed: %s %s", action, entity_id)
            return False

    async def _broadcast(self, text: str) -> None:
        for eid in self.tts_devices:
            if not isinstance(eid, str) or "." not in eid:
                continue
            domain = eid.split(".", 1)[0]
            try:
                if domain in ("text", "input_text"):
                    await self.hass.services.async_call(
                        domain,
                        "set_value",
                        {"entity_id": eid, "value": text},
                        blocking=False,
                    )
                elif domain == "media_player":
                    if self.hass.services.has_service(
                        "xiaomi_miot", "intelligent_speaker"
                    ):
                        await self.hass.services.async_call(
                            "xiaomi_miot",
                            "intelligent_speaker",
                            {
                                "entity_id": eid,
                                "text": text,
                                "execute": False,
                                "silent": False,
                            },
                            blocking=False,
                        )
                    elif self.hass.services.has_service("tts", "speak"):
                        await self.hass.services.async_call(
                            "tts",
                            "speak",
                            {"media_player_entity_id": eid, "message": text},
                            blocking=False,
                        )
            except Exception:
                _LOGGER.exception("broadcast failed: %s", eid)
