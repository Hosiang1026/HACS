from __future__ import annotations

from typing import Any
from uuid import uuid4

import voluptuous as vol
import voluptuous_serialize

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers import config_validation as cv
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
    Selector,
    TextSelector,
    TimeSelector,
)

from .const import (
    CONDITION_LOGICS,
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
    DEFAULT_TARGET_ACTION,
    DEFAULT_TRIGGER_TYPE,
    DOMAIN,
    TARGET_ACTIONS,
    TRIGGER_NUMERIC_ABOVE,
    TRIGGER_NUMERIC_BELOW,
    TRIGGER_TIME,
    TRIGGER_TYPES,
    TRIGGER_ZONE_ENTER,
    TRIGGER_ZONE_LEAVE,
    WEEKDAYS,
)
from .coordinator import _float_or, _int_or, conditions_to_slots, normalize_rule

_SECTION_BASIC = "rule_basic"
_SECTION_TRIGGER = "trigger"
_SECTION_TRIGGER_STATE = "trigger_state"
_SECTION_TRIGGER_NUMERIC = "trigger_numeric"
_SECTION_TRIGGER_TIME = "time_trigger"
_SECTION_TRIGGER_ZONE = "trigger_zone"
_SECTION_CONDITIONS = "conditions"
_SECTION_ACTION = "action"
_SECTION_BROADCAST = "broadcast"
_SECTION_TIMING = "timing"
_COND_1_ROW = "cond_1_row"
_COND_2_ROW = "cond_2_row"
_COND_3_ROW = "cond_3_row"
_TIME_ROW = "time_row"
_RULE_SECTIONS = (
    _SECTION_BASIC,
    _SECTION_TRIGGER,
    _SECTION_TRIGGER_STATE,
    _SECTION_TRIGGER_NUMERIC,
    _SECTION_TRIGGER_TIME,
    _SECTION_TRIGGER_ZONE,
    _SECTION_CONDITIONS,
    _SECTION_ACTION,
    _SECTION_BROADCAST,
    _SECTION_TIMING,
)
_ZONE_TRIGGERS = (TRIGGER_ZONE_ENTER, TRIGGER_ZONE_LEAVE)


class _FormGrid(Selector):
    selector_type = "grid"
    CONFIG_SCHEMA = vol.Schema({}, extra=vol.ALLOW_EXTRA)

    def __init__(self, fields: dict, column_min_width: str = "120px") -> None:
        self.config: dict[str, Any] = {}
        self._fields = fields
        self._column_min_width = column_min_width
        self._inner = vol.Schema(fields)

    def __call__(self, data: Any) -> Any:
        return self._inner(data)

    def serialize(self) -> dict[str, Any]:
        return {
            "type": "grid",
            "flatten": False,
            "column_min_width": self._column_min_width,
            "schema": voluptuous_serialize.convert(
                vol.Schema(self._fields),
                custom_serializer=cv.custom_serializer,
            ),
        }


def _as_list(value: Any) -> list:
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    return list(value)


def _rule_form_defaults(rule: dict[str, Any] | None = None) -> dict[str, Any]:
    if not rule:
        return {}
    data = dict(rule)
    data.update(conditions_to_slots(rule.get(CONF_CONDITIONS) or []))
    return data


def _weekdays_selector(_defaults: dict[str, Any] | None = None) -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=WEEKDAYS,
            multiple=True,
            mode=SelectSelectorMode.DROPDOWN,
            translation_key="weekdays",
        )
    )


def _trigger_type_selector() -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=TRIGGER_TYPES,
            mode=SelectSelectorMode.DROPDOWN,
            translation_key="trigger_type",
        )
    )


def _trigger_type_fields(defaults: dict[str, Any]) -> dict[Any, Any]:
    d = defaults
    fields: dict[Any, Any] = {
        vol.Required(
            CONF_TRIGGER_TYPE,
            default=d.get(CONF_TRIGGER_TYPE, DEFAULT_TRIGGER_TYPE),
        ): _trigger_type_selector(),
    }
    weekdays = _as_list(d.get(CONF_WEEKDAYS))
    if weekdays:
        fields[vol.Optional(CONF_WEEKDAYS, default=weekdays)] = _weekdays_selector(d)
    else:
        fields[vol.Optional(CONF_WEEKDAYS)] = _weekdays_selector(d)
    return fields


def _trigger_state_fields(defaults: dict[str, Any]) -> dict[Any, Any]:
    d = defaults
    fields: dict[Any, Any] = {}
    entity = (
        d.get(CONF_TRIGGER_ENTITY)
        if d.get(CONF_TRIGGER_TYPE) not in _ZONE_TRIGGERS
        else None
    )
    if entity:
        fields[vol.Optional(CONF_TRIGGER_ENTITY, default=entity)] = EntitySelector()
    else:
        fields[vol.Optional(CONF_TRIGGER_ENTITY)] = EntitySelector()
    fields[vol.Optional(CONF_TRIGGER_TO, default=d.get(CONF_TRIGGER_TO, ""))] = (
        TextSelector()
    )
    fields[vol.Optional(CONF_TRIGGER_FROM, default=d.get(CONF_TRIGGER_FROM, ""))] = (
        TextSelector()
    )
    return fields


def _trigger_numeric_fields(defaults: dict[str, Any]) -> dict[Any, Any]:
    d = defaults
    fields: dict[Any, Any] = {}
    entity = (
        d.get(CONF_TRIGGER_ENTITY)
        if d.get(CONF_TRIGGER_TYPE) not in _ZONE_TRIGGERS
        else None
    )
    if entity:
        fields[vol.Optional(CONF_TRIGGER_ENTITY, default=entity)] = EntitySelector()
    else:
        fields[vol.Optional(CONF_TRIGGER_ENTITY)] = EntitySelector()
    fields[
        vol.Optional(
            CONF_NUMERIC_THRESHOLD,
            default=_float_or(d.get(CONF_NUMERIC_THRESHOLD)),
        )
    ] = NumberSelector(
        NumberSelectorConfig(
            min=-999999, max=999999, step=0.1, mode=NumberSelectorMode.BOX
        )
    )
    return fields


def _trigger_time_fields(defaults: dict[str, Any]) -> dict[Any, Any]:
    d = defaults
    if d.get(CONF_TRIGGER_TIME):
        return {
            vol.Optional(CONF_TRIGGER_TIME, default=d[CONF_TRIGGER_TIME]): TimeSelector()
        }
    return {vol.Optional(CONF_TRIGGER_TIME): TimeSelector()}


def _trigger_zone_fields(defaults: dict[str, Any]) -> dict[Any, Any]:
    d = defaults
    fields: dict[Any, Any] = {}
    person_sel = EntitySelector(EntitySelectorConfig(domain=["person"]))
    zone_sel = EntitySelector(EntitySelectorConfig(domain=["zone"]))
    if d.get(CONF_TRIGGER_PERSON):
        fields[vol.Optional(CONF_TRIGGER_PERSON, default=d[CONF_TRIGGER_PERSON])] = (
            person_sel
        )
    else:
        fields[vol.Optional(CONF_TRIGGER_PERSON)] = person_sel
    if d.get(CONF_TRIGGER_ENTITY) and d.get(CONF_TRIGGER_TYPE) in _ZONE_TRIGGERS:
        fields[vol.Optional(CONF_TRIGGER_ENTITY, default=d[CONF_TRIGGER_ENTITY])] = (
            zone_sel
        )
    else:
        fields[vol.Optional(CONF_TRIGGER_ENTITY)] = zone_sel
    return fields


def _trigger_type_values(d: dict[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {
        CONF_TRIGGER_TYPE: d.get(CONF_TRIGGER_TYPE, DEFAULT_TRIGGER_TYPE),
    }
    weekdays = _as_list(d.get(CONF_WEEKDAYS))
    if weekdays:
        values[CONF_WEEKDAYS] = weekdays
    return values


def _trigger_state_values(d: dict[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {
        CONF_TRIGGER_TO: d.get(CONF_TRIGGER_TO, ""),
        CONF_TRIGGER_FROM: d.get(CONF_TRIGGER_FROM, ""),
    }
    if d.get(CONF_TRIGGER_ENTITY) and d.get(CONF_TRIGGER_TYPE) not in _ZONE_TRIGGERS:
        values[CONF_TRIGGER_ENTITY] = d[CONF_TRIGGER_ENTITY]
    return values


def _trigger_numeric_values(d: dict[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {
        CONF_NUMERIC_THRESHOLD: _float_or(d.get(CONF_NUMERIC_THRESHOLD)),
    }
    if d.get(CONF_TRIGGER_ENTITY) and d.get(CONF_TRIGGER_TYPE) not in _ZONE_TRIGGERS:
        values[CONF_TRIGGER_ENTITY] = d[CONF_TRIGGER_ENTITY]
    return values


def _trigger_time_values(d: dict[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    if d.get(CONF_TRIGGER_TIME):
        values[CONF_TRIGGER_TIME] = d[CONF_TRIGGER_TIME]
    return values


def _trigger_zone_values(d: dict[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    if d.get(CONF_TRIGGER_PERSON):
        values[CONF_TRIGGER_PERSON] = d[CONF_TRIGGER_PERSON]
    if d.get(CONF_TRIGGER_ENTITY) and d.get(CONF_TRIGGER_TYPE) in _ZONE_TRIGGERS:
        values[CONF_TRIGGER_ENTITY] = d[CONF_TRIGGER_ENTITY]
    return values


def _merge_section(out: dict[str, Any], part: Any) -> None:
    if not isinstance(part, dict):
        return
    for k, v in part.items():
        if v in (None, "", []):
            out.setdefault(k, v)
        else:
            out[k] = v


def _condition_fields(defaults: dict[str, Any]) -> dict[Any, Any]:
    d = defaults

    def _cond_row(ek: str, sk: str) -> _FormGrid:
        row: dict[Any, Any] = {}
        if d.get(ek):
            row[vol.Optional(ek, default=d[ek])] = EntitySelector()
        else:
            row[vol.Optional(ek)] = EntitySelector()
        row[vol.Optional(sk, default=d.get(sk, ""))] = TextSelector()
        return _FormGrid(row, column_min_width="160px")

    time_row: dict[Any, Any] = {}
    if d.get(CONF_TIME_AFTER):
        time_row[vol.Optional(CONF_TIME_AFTER, default=d[CONF_TIME_AFTER])] = (
            TimeSelector()
        )
    else:
        time_row[vol.Optional(CONF_TIME_AFTER)] = TimeSelector()
    if d.get(CONF_TIME_BEFORE):
        time_row[vol.Optional(CONF_TIME_BEFORE, default=d[CONF_TIME_BEFORE])] = (
            TimeSelector()
        )
    else:
        time_row[vol.Optional(CONF_TIME_BEFORE)] = TimeSelector()

    return {
        vol.Required(
            CONF_CONDITION_LOGIC,
            default=d.get(CONF_CONDITION_LOGIC, DEFAULT_CONDITION_LOGIC),
        ): SelectSelector(
            SelectSelectorConfig(
                options=CONDITION_LOGICS,
                mode=SelectSelectorMode.DROPDOWN,
                translation_key="condition_logic",
            )
        ),
        vol.Optional(_COND_1_ROW): _cond_row(CONF_COND_1_ENTITY, CONF_COND_1_STATE),
        vol.Optional(_COND_2_ROW): _cond_row(CONF_COND_2_ENTITY, CONF_COND_2_STATE),
        vol.Optional(_COND_3_ROW): _cond_row(CONF_COND_3_ENTITY, CONF_COND_3_STATE),
        vol.Optional(_TIME_ROW): _FormGrid(time_row, column_min_width="160px"),
    }


def _condition_values(d: dict[str, Any]) -> dict[str, Any]:
    def _row(ek: str, sk: str) -> dict[str, Any]:
        row: dict[str, Any] = {sk: d.get(sk, "")}
        if d.get(ek):
            row[ek] = d[ek]
        return row

    values: dict[str, Any] = {
        CONF_CONDITION_LOGIC: d.get(CONF_CONDITION_LOGIC, DEFAULT_CONDITION_LOGIC),
        _COND_1_ROW: _row(CONF_COND_1_ENTITY, CONF_COND_1_STATE),
        _COND_2_ROW: _row(CONF_COND_2_ENTITY, CONF_COND_2_STATE),
        _COND_3_ROW: _row(CONF_COND_3_ENTITY, CONF_COND_3_STATE),
    }
    time_vals: dict[str, Any] = {}
    if d.get(CONF_TIME_AFTER):
        time_vals[CONF_TIME_AFTER] = d[CONF_TIME_AFTER]
    if d.get(CONF_TIME_BEFORE):
        time_vals[CONF_TIME_BEFORE] = d[CONF_TIME_BEFORE]
    if time_vals:
        values[_TIME_ROW] = time_vals
    return values


def _action_fields(defaults: dict[str, Any]) -> dict[Any, Any]:
    d = defaults
    targets = _as_list(d.get(CONF_TARGET_ENTITIES))
    fields: dict[Any, Any] = {}
    if targets:
        fields[vol.Optional(CONF_TARGET_ENTITIES, default=targets)] = EntitySelector(
            EntitySelectorConfig(multiple=True)
        )
    else:
        fields[vol.Optional(CONF_TARGET_ENTITIES)] = EntitySelector(
            EntitySelectorConfig(multiple=True)
        )
    fields[
        vol.Optional(
            CONF_TARGET_ACTION,
            default=d.get(CONF_TARGET_ACTION, DEFAULT_TARGET_ACTION),
        )
    ] = SelectSelector(
        SelectSelectorConfig(
            options=TARGET_ACTIONS,
            mode=SelectSelectorMode.DROPDOWN,
            translation_key="target_action",
        )
    )
    return fields


def _action_values(d: dict[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {
        CONF_TARGET_ACTION: d.get(CONF_TARGET_ACTION, DEFAULT_TARGET_ACTION),
    }
    targets = _as_list(d.get(CONF_TARGET_ENTITIES))
    if targets:
        values[CONF_TARGET_ENTITIES] = targets
    return values


def _broadcast_fields(defaults: dict[str, Any]) -> dict[Any, Any]:
    d = defaults
    return {
        vol.Required(
            CONF_BROADCAST_SUCCESS,
            default=d.get(CONF_BROADCAST_SUCCESS, DEFAULT_BROADCAST_SUCCESS),
        ): BooleanSelector(),
        vol.Optional(CONF_MESSAGE, default=d.get(CONF_MESSAGE, "")): TextSelector(),
        vol.Required(
            CONF_BROADCAST_FAIL,
            default=d.get(CONF_BROADCAST_FAIL, DEFAULT_BROADCAST_FAIL),
        ): BooleanSelector(),
        vol.Optional(CONF_MESSAGE_FAIL, default=d.get(CONF_MESSAGE_FAIL, "")): TextSelector(),
    }


def _broadcast_values(d: dict[str, Any]) -> dict[str, Any]:
    return {
        CONF_BROADCAST_SUCCESS: d.get(CONF_BROADCAST_SUCCESS, DEFAULT_BROADCAST_SUCCESS),
        CONF_MESSAGE: d.get(CONF_MESSAGE, ""),
        CONF_BROADCAST_FAIL: d.get(CONF_BROADCAST_FAIL, DEFAULT_BROADCAST_FAIL),
        CONF_MESSAGE_FAIL: d.get(CONF_MESSAGE_FAIL, ""),
    }


def _timing_fields(defaults: dict[str, Any]) -> dict[Any, Any]:
    d = defaults
    return {
        vol.Required(
            CONF_COOLDOWN,
            default=_int_or(d.get(CONF_COOLDOWN), DEFAULT_COOLDOWN),
        ): NumberSelector(
            NumberSelectorConfig(
                min=0,
                max=86400,
                step=1,
                mode=NumberSelectorMode.BOX,
                unit_of_measurement="s",
            )
        ),
        vol.Required(
            CONF_DELAY,
            default=_int_or(d.get(CONF_DELAY), DEFAULT_DELAY),
        ): NumberSelector(
            NumberSelectorConfig(
                min=0,
                max=600,
                step=1,
                mode=NumberSelectorMode.BOX,
                unit_of_measurement="s",
            )
        ),
        vol.Required(
            CONF_VERIFY_DELAY,
            default=_int_or(d.get(CONF_VERIFY_DELAY), DEFAULT_VERIFY_DELAY),
        ): NumberSelector(
            NumberSelectorConfig(
                min=0,
                max=120,
                step=1,
                mode=NumberSelectorMode.BOX,
                unit_of_measurement="s",
            )
        ),
    }


def _timing_values(d: dict[str, Any]) -> dict[str, Any]:
    return {
        CONF_COOLDOWN: _int_or(d.get(CONF_COOLDOWN), DEFAULT_COOLDOWN),
        CONF_DELAY: _int_or(d.get(CONF_DELAY), DEFAULT_DELAY),
        CONF_VERIFY_DELAY: _int_or(d.get(CONF_VERIFY_DELAY), DEFAULT_VERIFY_DELAY),
    }


def _rule_schema(defaults: dict[str, Any] | None = None) -> dict[Any, Any]:
    d = _rule_form_defaults(defaults)
    return {
        vol.Required(_SECTION_BASIC): section(
            vol.Schema(
                {
                    vol.Required(
                        CONF_RULE_NAME, default=d.get(CONF_RULE_NAME, "规则")
                    ): TextSelector(),
                    vol.Optional(
                        CONF_RULE_ROOM, default=d.get(CONF_RULE_ROOM, "")
                    ): TextSelector(),
                    vol.Required(
                        CONF_RULE_ENABLED, default=d.get(CONF_RULE_ENABLED, True)
                    ): BooleanSelector(),
                }
            ),
            {"collapsed": False},
        ),
        vol.Required(_SECTION_TRIGGER): section(
            vol.Schema(_trigger_type_fields(d)),
            {"collapsed": False},
        ),
        vol.Required(_SECTION_TRIGGER_STATE): section(
            vol.Schema(_trigger_state_fields(d)),
            {"collapsed": False},
        ),
        vol.Required(_SECTION_TRIGGER_NUMERIC): section(
            vol.Schema(_trigger_numeric_fields(d)),
            {"collapsed": False},
        ),
        vol.Required(_SECTION_TRIGGER_TIME): section(
            vol.Schema(_trigger_time_fields(d)),
            {"collapsed": False},
        ),
        vol.Required(_SECTION_TRIGGER_ZONE): section(
            vol.Schema(_trigger_zone_fields(d)),
            {"collapsed": False},
        ),
        vol.Required(_SECTION_CONDITIONS): section(
            vol.Schema(_condition_fields(d)),
            {"collapsed": False},
        ),
        vol.Required(_SECTION_ACTION): section(
            vol.Schema(_action_fields(d)),
            {"collapsed": False},
        ),
        vol.Required(_SECTION_BROADCAST): section(
            vol.Schema(_broadcast_fields(d)),
            {"collapsed": False},
        ),
        vol.Required(_SECTION_TIMING): section(
            vol.Schema(_timing_fields(d)),
            {"collapsed": False},
        ),
    }


def _rule_values(defaults: dict[str, Any] | None = None) -> dict[str, Any]:
    d = _rule_form_defaults(defaults)
    return {
        _SECTION_BASIC: {
            CONF_RULE_NAME: d.get(CONF_RULE_NAME, "规则"),
            CONF_RULE_ROOM: d.get(CONF_RULE_ROOM, ""),
            CONF_RULE_ENABLED: d.get(CONF_RULE_ENABLED, True),
        },
        _SECTION_TRIGGER: _trigger_type_values(d),
        _SECTION_TRIGGER_STATE: _trigger_state_values(d),
        _SECTION_TRIGGER_NUMERIC: _trigger_numeric_values(d),
        _SECTION_TRIGGER_TIME: _trigger_time_values(d),
        _SECTION_TRIGGER_ZONE: _trigger_zone_values(d),
        _SECTION_CONDITIONS: _condition_values(d),
        _SECTION_ACTION: _action_values(d),
        _SECTION_BROADCAST: _broadcast_values(d),
        _SECTION_TIMING: _timing_values(d),
    }


def _row_from_src(
    out: dict[str, Any], cond: dict[str, Any], row_key: str, ek: str, sk: str
) -> None:
    row = cond.get(row_key)
    if isinstance(row, dict):
        if ek in row:
            out[ek] = row[ek]
        if sk in row:
            out[sk] = row[sk]


def _rule_from_input(src: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in _RULE_SECTIONS:
        _merge_section(out, src.get(key))
    skip = set(_RULE_SECTIONS)
    for k, v in src.items():
        if k not in skip and k not in out:
            out[k] = v
    cond = src.get(_SECTION_CONDITIONS)
    if isinstance(cond, dict):
        _row_from_src(out, cond, _COND_1_ROW, CONF_COND_1_ENTITY, CONF_COND_1_STATE)
        _row_from_src(out, cond, _COND_2_ROW, CONF_COND_2_ENTITY, CONF_COND_2_STATE)
        _row_from_src(out, cond, _COND_3_ROW, CONF_COND_3_ENTITY, CONF_COND_3_STATE)
        time_row = cond.get(_TIME_ROW)
        if isinstance(time_row, dict):
            if CONF_TIME_AFTER in time_row:
                out[CONF_TIME_AFTER] = time_row[CONF_TIME_AFTER]
            if CONF_TIME_BEFORE in time_row:
                out[CONF_TIME_BEFORE] = time_row[CONF_TIME_BEFORE]
        for row_key in (_COND_1_ROW, _COND_2_ROW, _COND_3_ROW, _TIME_ROW):
            out.pop(row_key, None)

    state = src.get(_SECTION_TRIGGER_STATE)
    numeric = src.get(_SECTION_TRIGGER_NUMERIC)
    zone = src.get(_SECTION_TRIGGER_ZONE)
    state = state if isinstance(state, dict) else {}
    numeric = numeric if isinstance(numeric, dict) else {}
    zone = zone if isinstance(zone, dict) else {}
    ttype = out.get(CONF_TRIGGER_TYPE, DEFAULT_TRIGGER_TYPE)
    if ttype in _ZONE_TRIGGERS:
        out[CONF_TRIGGER_PERSON] = zone.get(CONF_TRIGGER_PERSON) or ""
        out[CONF_TRIGGER_ENTITY] = zone.get(CONF_TRIGGER_ENTITY) or ""
    elif ttype in (TRIGGER_NUMERIC_ABOVE, TRIGGER_NUMERIC_BELOW):
        out[CONF_TRIGGER_ENTITY] = (
            numeric.get(CONF_TRIGGER_ENTITY) or state.get(CONF_TRIGGER_ENTITY) or ""
        )
        out[CONF_TRIGGER_PERSON] = ""
    elif ttype != TRIGGER_TIME:
        out[CONF_TRIGGER_ENTITY] = (
            state.get(CONF_TRIGGER_ENTITY) or numeric.get(CONF_TRIGGER_ENTITY) or ""
        )
        out[CONF_TRIGGER_PERSON] = ""
    else:
        out[CONF_TRIGGER_PERSON] = ""
    return out


def _validate_rule(flat: dict[str, Any]) -> dict[str, str]:
    errors: dict[str, str] = {}
    trigger_type = flat.get(CONF_TRIGGER_TYPE, DEFAULT_TRIGGER_TYPE)
    if trigger_type == TRIGGER_TIME:
        if not flat.get(CONF_TRIGGER_TIME):
            errors["base"] = "trigger_time_required"
    elif trigger_type in _ZONE_TRIGGERS:
        if not flat.get(CONF_TRIGGER_PERSON) or not flat.get(CONF_TRIGGER_ENTITY):
            errors["base"] = "trigger_zone_required"
    elif not flat.get(CONF_TRIGGER_ENTITY):
        errors["base"] = "trigger_entity_required"
    return errors


def _show_rule_form(
    flow: ConfigFlow | OptionsFlow,
    step_id: str,
    defaults: dict[str, Any] | None = None,
    errors: dict[str, str] | None = None,
) -> ConfigFlowResult:
    return flow.async_show_form(
        step_id=step_id,
        data_schema=flow.add_suggested_values_to_schema(
            vol.Schema(_rule_schema(defaults)),
            _rule_values(defaults),
        ),
        errors=errors or {},
    )


def _scene_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    d = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_NAME, default=d.get(CONF_NAME, "")): TextSelector(),
            vol.Optional(
                CONF_TTS_DEVICES, default=_as_list(d.get(CONF_TTS_DEVICES))
            ): EntitySelector(
                EntitySelectorConfig(
                    domain=["media_player", "text", "input_text"], multiple=True
                )
            ),
        }
    )


class IotSceneConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._rules: list[dict[str, Any]] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=_scene_schema())
        name = (user_input.get(CONF_NAME) or "").strip()
        if not name:
            errors["base"] = "name_required"
            return self.async_show_form(
                step_id="user", data_schema=_scene_schema(user_input), errors=errors
            )
        self._data = {
            CONF_NAME: name,
            CONF_TTS_DEVICES: _as_list(user_input.get(CONF_TTS_DEVICES)),
        }
        await self.async_set_unique_id(f"{DOMAIN}_{name}")
        self._abort_if_unique_id_configured()
        return await self.async_step_rule()

    async def async_step_rule(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is None:
            return _show_rule_form(self, "rule")
        flat = _rule_from_input(user_input)
        errors = _validate_rule(flat)
        if errors:
            return _show_rule_form(self, "rule", flat, errors)
        rule = normalize_rule({**flat, CONF_RULE_ID: str(uuid4())})
        self._rules.append(rule)
        return await self.async_step_rule_menu()

    async def async_step_rule_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is None:
            return self.async_show_menu(
                step_id="rule_menu",
                menu_options=["rule", "finish"],
            )
        return self.async_abort(reason="unknown")

    async def async_step_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_create_entry(
            title=self._data[CONF_NAME],
            data={CONF_NAME: self._data[CONF_NAME]},
            options={
                CONF_TTS_DEVICES: self._data.get(CONF_TTS_DEVICES, []),
                CONF_RULES: self._rules,
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return IotSceneOptionsFlow()


class IotSceneOptionsFlow(OptionsFlow):
    def __init__(self) -> None:
        self._rules: list[dict[str, Any]] = []
        self._edit_id: str | None = None

    def _load_rules(self) -> list[dict[str, Any]]:
        self._rules = [
            normalize_rule(r)
            for r in _as_list(self.config_entry.options.get(CONF_RULES))
        ]
        return self._rules

    def _options_data(self, rules: list[dict[str, Any]], tts: Any | None = None) -> dict:
        return {
            CONF_TTS_DEVICES: _as_list(
                tts
                if tts is not None
                else self.config_entry.options.get(CONF_TTS_DEVICES)
            ),
            CONF_RULES: rules,
        }

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._load_rules()
        return self.async_show_menu(
            step_id="init",
            menu_options=["settings", "add_rule", "edit_rule", "remove_rule"],
        )

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._load_rules()
        current = {
            CONF_NAME: self.config_entry.data.get(CONF_NAME),
            CONF_TTS_DEVICES: _as_list(self.config_entry.options.get(CONF_TTS_DEVICES)),
        }
        if user_input is None:
            return self.async_show_form(
                step_id="settings",
                data_schema=_scene_schema(current),
            )
        name = (user_input.get(CONF_NAME) or "").strip()
        if not name:
            return self.async_show_form(
                step_id="settings",
                data_schema=_scene_schema(user_input),
                errors={"base": "name_required"},
            )
        self.hass.config_entries.async_update_entry(
            self.config_entry,
            title=name,
            data={CONF_NAME: name},
        )
        return self.async_create_entry(
            title="",
            data=self._options_data(self._rules, user_input.get(CONF_TTS_DEVICES)),
        )

    async def async_step_add_rule(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._load_rules()
        if user_input is None:
            return _show_rule_form(self, "add_rule")
        flat = _rule_from_input(user_input)
        errors = _validate_rule(flat)
        if errors:
            return _show_rule_form(self, "add_rule", flat, errors)
        self._rules.append(normalize_rule({**flat, CONF_RULE_ID: str(uuid4())}))
        return self.async_create_entry(title="", data=self._options_data(self._rules))

    async def async_step_edit_rule(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._load_rules()
        options = {
            r[CONF_RULE_ID]: r.get(CONF_RULE_NAME) or r[CONF_RULE_ID]
            for r in self._rules
        }
        if not options:
            return self.async_abort(reason="no_rules")
        if user_input is None:
            return self.async_show_form(
                step_id="edit_rule",
                data_schema=vol.Schema(
                    {
                        vol.Required(CONF_RULE_ID): SelectSelector(
                            SelectSelectorConfig(
                                options=[
                                    {"value": k, "label": v}
                                    for k, v in options.items()
                                ],
                                mode=SelectSelectorMode.DROPDOWN,
                            )
                        )
                    }
                ),
            )
        self._edit_id = user_input[CONF_RULE_ID]
        return await self.async_step_edit_rule_form()

    async def async_step_edit_rule_form(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is None:
            self._load_rules()
            current = next(
                (r for r in self._rules if r[CONF_RULE_ID] == self._edit_id), None
            )
            if current is None:
                return self.async_abort(reason="no_rules")
            return _show_rule_form(self, "edit_rule_form", current)
        if not self._edit_id:
            return self.async_abort(reason="no_rules")
        flat = _rule_from_input(user_input)
        errors = _validate_rule(flat)
        if errors:
            return _show_rule_form(self, "edit_rule_form", flat, errors)
        self._load_rules()
        updated = normalize_rule({**flat, CONF_RULE_ID: self._edit_id})
        self._rules = [
            updated if r[CONF_RULE_ID] == self._edit_id else r for r in self._rules
        ]
        return self.async_create_entry(title="", data=self._options_data(self._rules))

    async def async_step_remove_rule(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._load_rules()
        options = {
            r[CONF_RULE_ID]: r.get(CONF_RULE_NAME) or r[CONF_RULE_ID]
            for r in self._rules
        }
        if not options:
            return self.async_abort(reason="no_rules")
        if user_input is None:
            return self.async_show_form(
                step_id="remove_rule",
                data_schema=vol.Schema(
                    {
                        vol.Required(CONF_RULE_ID): SelectSelector(
                            SelectSelectorConfig(
                                options=[
                                    {"value": k, "label": v}
                                    for k, v in options.items()
                                ],
                                mode=SelectSelectorMode.DROPDOWN,
                            )
                        )
                    }
                ),
            )
        rid = user_input[CONF_RULE_ID]
        self._rules = [r for r in self._rules if r[CONF_RULE_ID] != rid]
        return self.async_create_entry(title="", data=self._options_data(self._rules))
