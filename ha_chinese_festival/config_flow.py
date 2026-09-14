from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
import re
import uuid
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
    TimeSelector,
)
import yaml

from .const import (
    AI_MODELS,
    ANNIVERSARY_TYPE_LUNAR,
    ANNIVERSARY_TYPE_SOLAR,
    ANNIVERSARY_TYPE_SUM,
    BIRTHDAY_TYPE_LUNAR,
    BIRTHDAY_TYPE_SOLAR,
    CONF_AI_API_KEY,
    CONF_AI_API_URL,
    CONF_AI_ENABLED,
    CONF_AI_MODEL,
    CONF_ANNIVERSARIES,
    CONF_BIRTHDAYS,
    CONF_FREEWAY,
    CONF_HOLIDAY,
    CONF_HOLIDAY_AUTO,
    CONF_INTENT_ENABLED,
    CONF_ITEM_DATE,
    CONF_ITEM_ID,
    CONF_ITEM_KIND,
    CONF_ITEM_NAME,
    CONF_ITEM_TYPE,
    CONF_LANGUAGE,
    CONF_LEGAL,
    CONF_LICENSES,
    CONF_NEAR_ANNIVERSARY_DAYS,
    CONF_NEAR_BIRTHDAY_DAYS,
    CONF_NEAR_FESTIVAL_DAYS,
    CONF_NEAR_LICENSE_DAYS,
    CONF_NOTIFY,
    CONF_NOTIFY_CALENDAR,
    CONF_NOTIFY_CALENDAR_TIME,
    CONF_NOTIFY_FESTIVAL,
    CONF_NOTIFY_FESTIVAL_TIME,
    CONF_NOTIFY_LICENSE,
    CONF_NOTIFY_LICENSE_TIME,
    CONF_NOTIFY_MEMORIAL,
    CONF_NOTIFY_MEMORIAL_TIME,
    CONF_NOTIFY_RULES,
    CONF_NOTIFY_RULES_ENABLED,
    CONF_REPAIR,
    DEFAULT_AI_API_KEY,
    DEFAULT_AI_API_URL,
    DEFAULT_AI_ENABLED,
    DEFAULT_AI_MODEL,
    DEFAULT_HOLIDAY_AUTO,
    DEFAULT_INTENT_ENABLED,
    DEFAULT_LANGUAGE,
    DEFAULT_NEAR_ANNIVERSARY_DAYS,
    DEFAULT_NEAR_BIRTHDAY_DAYS,
    DEFAULT_NEAR_FESTIVAL_DAYS,
    DEFAULT_NEAR_LICENSE_DAYS,
    DEFAULT_NOTIFY_CALENDAR,
    DEFAULT_NOTIFY_CALENDAR_TIME,
    DEFAULT_NOTIFY_FESTIVAL,
    DEFAULT_NOTIFY_FESTIVAL_TIME,
    DEFAULT_NOTIFY_LICENSE,
    DEFAULT_NOTIFY_LICENSE_TIME,
    DEFAULT_NOTIFY_MEMORIAL,
    DEFAULT_NOTIFY_MEMORIAL_TIME,
    DEFAULT_NOTIFY_RULES,
    DEFAULT_NOTIFY_RULES_ENABLED,
    DOMAIN,
    ITEM_KIND_ANNIVERSARY,
    ITEM_KIND_BIRTHDAY,
    ITEM_KIND_LEGAL,
    ITEM_KIND_LICENSE,
    ITEM_KIND_TO_KEY,
    ITEM_KINDS,
)
from .festival_engine import (
    default_anniversaries,
    default_birthdays,
    default_licenses,
)

_YMD_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MD_RE = re.compile(r"^\d{2}-\d{2}$")

_KIND_LABEL = {
    ITEM_KIND_LICENSE: "证件",
    ITEM_KIND_BIRTHDAY: "生日",
    ITEM_KIND_ANNIVERSARY: "纪念日",
    ITEM_KIND_LEGAL: "法定节假日",
}


def _get(src: dict, key: str, default: Any) -> Any:
    if key in src and src[key] not in (None, ""):
        return src[key]
    return default


def _notify_values(raw: Any) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, str):
        return [raw]
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


def _notify_rules_to_text(raw: Any) -> str:
    if raw in (None, "", {}):
        return ""
    if isinstance(raw, str):
        return raw
    try:
        return yaml.safe_dump(raw, allow_unicode=True, sort_keys=False).strip()
    except Exception:
        return str(raw)


def _parse_notify_rules(raw: Any) -> tuple[dict | None, str | None]:
    if raw in (None, ""):
        return {}, None
    if isinstance(raw, dict):
        return raw, None
    text = str(raw).strip()
    if not text:
        return {}, None
    try:
        loaded = yaml.safe_load(text)
    except Exception:
        return None, "invalid_yaml"
    if loaded is None:
        return {}, None
    if not isinstance(loaded, dict):
        return None, "invalid_yaml"
    return loaded, None


def _global_fields(hass: HomeAssistant | None = None, defaults: dict | None = None) -> dict:
    defaults = defaults or {}
    return {
        vol.Required(CONF_LANGUAGE): SelectSelector(
            SelectSelectorConfig(
                options=["zh-Hans", "zh-Hant"],
                mode=SelectSelectorMode.DROPDOWN,
                translation_key="language",
            )
        ),
        vol.Required(CONF_NOTIFY_CALENDAR): BooleanSelector(),
        vol.Required(CONF_NOTIFY_CALENDAR_TIME): TimeSelector(),
        vol.Required(CONF_NOTIFY_FESTIVAL): BooleanSelector(),
        vol.Required(CONF_NOTIFY_FESTIVAL_TIME): TimeSelector(),
        vol.Required(CONF_NOTIFY_MEMORIAL): BooleanSelector(),
        vol.Required(CONF_NOTIFY_MEMORIAL_TIME): TimeSelector(),
        vol.Required(CONF_NOTIFY_LICENSE): BooleanSelector(),
        vol.Required(CONF_NOTIFY_LICENSE_TIME): TimeSelector(),
        vol.Optional(CONF_NOTIFY): SelectSelector(
            SelectSelectorConfig(
                options=_notify_options(hass, _get(defaults, CONF_NOTIFY, None)),
                multiple=True,
                custom_value=True,
                mode=SelectSelectorMode.DROPDOWN,
            )
        ),
        vol.Required(CONF_NEAR_FESTIVAL_DAYS): NumberSelector(
            NumberSelectorConfig(min=1, max=60, step=1, mode=NumberSelectorMode.BOX)
        ),
        vol.Required(CONF_NEAR_BIRTHDAY_DAYS): NumberSelector(
            NumberSelectorConfig(min=1, max=60, step=1, mode=NumberSelectorMode.BOX)
        ),
        vol.Required(CONF_NEAR_ANNIVERSARY_DAYS): NumberSelector(
            NumberSelectorConfig(min=1, max=60, step=1, mode=NumberSelectorMode.BOX)
        ),
        vol.Required(CONF_NEAR_LICENSE_DAYS): NumberSelector(
            NumberSelectorConfig(min=1, max=365, step=1, mode=NumberSelectorMode.BOX)
        ),
        vol.Required(CONF_HOLIDAY_AUTO): BooleanSelector(),
        vol.Required(CONF_AI_ENABLED): BooleanSelector(),
        vol.Optional(CONF_AI_API_URL): TextSelector(),
        vol.Optional(CONF_AI_API_KEY): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
        vol.Optional(CONF_AI_MODEL): SelectSelector(
            SelectSelectorConfig(
                options=list(AI_MODELS),
                mode=SelectSelectorMode.DROPDOWN,
                custom_value=True,
            )
        ),
        vol.Required(CONF_NOTIFY_RULES_ENABLED): BooleanSelector(),
        vol.Optional(CONF_NOTIFY_RULES): TextSelector(
            TextSelectorConfig(multiline=True)
        ),
        vol.Required(CONF_INTENT_ENABLED): BooleanSelector(),
    }


def _memorial_enabled(src: dict, defaults: dict | None = None) -> bool:
    defaults = defaults or {}
    if CONF_NOTIFY_MEMORIAL in src and src.get(CONF_NOTIFY_MEMORIAL) not in (None, ""):
        return bool(src.get(CONF_NOTIFY_MEMORIAL))
    if CONF_NOTIFY_MEMORIAL in defaults and defaults.get(CONF_NOTIFY_MEMORIAL) not in (
        None,
        "",
    ):
        return bool(defaults.get(CONF_NOTIFY_MEMORIAL))
    bday = src.get("notify_birthday", defaults.get("notify_birthday", DEFAULT_NOTIFY_MEMORIAL))
    anni = src.get(
        "notify_anniversary", defaults.get("notify_anniversary", DEFAULT_NOTIFY_MEMORIAL)
    )
    return bool(bday) or bool(anni)


def _memorial_time_value(src: dict, defaults: dict | None = None) -> str:
    defaults = defaults or {}
    for bag in (src, defaults):
        for key in (
            CONF_NOTIFY_MEMORIAL_TIME,
            "notify_birthday_time",
            "notify_anniversary_time",
        ):
            val = bag.get(key)
            if val not in (None, ""):
                return str(val)
    return DEFAULT_NOTIFY_MEMORIAL_TIME


def _global_values(defaults: dict) -> dict:
    values = {
        CONF_LANGUAGE: str(_get(defaults, CONF_LANGUAGE, DEFAULT_LANGUAGE)),
        CONF_NOTIFY_CALENDAR: bool(
            _get(defaults, CONF_NOTIFY_CALENDAR, DEFAULT_NOTIFY_CALENDAR)
        ),
        CONF_NOTIFY_FESTIVAL: bool(
            _get(defaults, CONF_NOTIFY_FESTIVAL, DEFAULT_NOTIFY_FESTIVAL)
        ),
        CONF_NOTIFY_MEMORIAL: _memorial_enabled(defaults),
        CONF_NOTIFY_LICENSE: bool(
            _get(defaults, CONF_NOTIFY_LICENSE, DEFAULT_NOTIFY_LICENSE)
        ),
        CONF_NOTIFY_CALENDAR_TIME: str(
            _get(defaults, CONF_NOTIFY_CALENDAR_TIME, DEFAULT_NOTIFY_CALENDAR_TIME)
        ),
        CONF_NOTIFY_FESTIVAL_TIME: str(
            _get(defaults, CONF_NOTIFY_FESTIVAL_TIME, DEFAULT_NOTIFY_FESTIVAL_TIME)
        ),
        CONF_NOTIFY_MEMORIAL_TIME: _memorial_time_value(defaults),
        CONF_NOTIFY_LICENSE_TIME: str(
            _get(defaults, CONF_NOTIFY_LICENSE_TIME, DEFAULT_NOTIFY_LICENSE_TIME)
        ),
        CONF_NEAR_FESTIVAL_DAYS: int(
            _get(defaults, CONF_NEAR_FESTIVAL_DAYS, DEFAULT_NEAR_FESTIVAL_DAYS)
        ),
        CONF_NEAR_BIRTHDAY_DAYS: int(
            _get(defaults, CONF_NEAR_BIRTHDAY_DAYS, DEFAULT_NEAR_BIRTHDAY_DAYS)
        ),
        CONF_NEAR_ANNIVERSARY_DAYS: int(
            _get(defaults, CONF_NEAR_ANNIVERSARY_DAYS, DEFAULT_NEAR_ANNIVERSARY_DAYS)
        ),
        CONF_NEAR_LICENSE_DAYS: int(
            _get(defaults, CONF_NEAR_LICENSE_DAYS, DEFAULT_NEAR_LICENSE_DAYS)
        ),
        CONF_HOLIDAY_AUTO: bool(_get(defaults, CONF_HOLIDAY_AUTO, DEFAULT_HOLIDAY_AUTO)),
        CONF_AI_ENABLED: bool(_get(defaults, CONF_AI_ENABLED, DEFAULT_AI_ENABLED)),
        CONF_AI_API_URL: str(_get(defaults, CONF_AI_API_URL, DEFAULT_AI_API_URL)),
        CONF_AI_API_KEY: str(_get(defaults, CONF_AI_API_KEY, DEFAULT_AI_API_KEY)),
        CONF_AI_MODEL: str(_get(defaults, CONF_AI_MODEL, DEFAULT_AI_MODEL)),
        CONF_NOTIFY_RULES_ENABLED: bool(
            _get(defaults, CONF_NOTIFY_RULES_ENABLED, DEFAULT_NOTIFY_RULES_ENABLED)
        ),
        CONF_NOTIFY_RULES: _notify_rules_to_text(
            _get(defaults, CONF_NOTIFY_RULES, DEFAULT_NOTIFY_RULES)
        ),
        CONF_INTENT_ENABLED: bool(
            _get(defaults, CONF_INTENT_ENABLED, DEFAULT_INTENT_ENABLED)
        ),
    }
    notify = _notify_values(_get(defaults, CONF_NOTIFY, None))
    if notify:
        values[CONF_NOTIFY] = notify
    return values


def _global_options(src: dict) -> dict:
    try:
        near_fest = int(src.get(CONF_NEAR_FESTIVAL_DAYS, DEFAULT_NEAR_FESTIVAL_DAYS))
    except (TypeError, ValueError):
        near_fest = DEFAULT_NEAR_FESTIVAL_DAYS
    try:
        near_lic = int(src.get(CONF_NEAR_LICENSE_DAYS, DEFAULT_NEAR_LICENSE_DAYS))
    except (TypeError, ValueError):
        near_lic = DEFAULT_NEAR_LICENSE_DAYS
    try:
        near_bday = int(src.get(CONF_NEAR_BIRTHDAY_DAYS, DEFAULT_NEAR_BIRTHDAY_DAYS))
    except (TypeError, ValueError):
        near_bday = DEFAULT_NEAR_BIRTHDAY_DAYS
    try:
        near_anni = int(
            src.get(CONF_NEAR_ANNIVERSARY_DAYS, DEFAULT_NEAR_ANNIVERSARY_DAYS)
        )
    except (TypeError, ValueError):
        near_anni = DEFAULT_NEAR_ANNIVERSARY_DAYS
    rules, _err = _parse_notify_rules(src.get(CONF_NOTIFY_RULES))
    if rules is None:
        rules = DEFAULT_NOTIFY_RULES
    return {
        CONF_LANGUAGE: str(src.get(CONF_LANGUAGE, DEFAULT_LANGUAGE) or DEFAULT_LANGUAGE),
        CONF_NOTIFY_CALENDAR: bool(
            src.get(CONF_NOTIFY_CALENDAR, DEFAULT_NOTIFY_CALENDAR)
        ),
        CONF_NOTIFY_FESTIVAL: bool(
            src.get(CONF_NOTIFY_FESTIVAL, DEFAULT_NOTIFY_FESTIVAL)
        ),
        CONF_NOTIFY_MEMORIAL: _memorial_enabled(src),
        CONF_NOTIFY_LICENSE: bool(src.get(CONF_NOTIFY_LICENSE, DEFAULT_NOTIFY_LICENSE)),
        CONF_NOTIFY: _notify_values(src.get(CONF_NOTIFY)),
        CONF_NOTIFY_CALENDAR_TIME: str(
            src.get(CONF_NOTIFY_CALENDAR_TIME, DEFAULT_NOTIFY_CALENDAR_TIME)
        ),
        CONF_NOTIFY_FESTIVAL_TIME: str(
            src.get(CONF_NOTIFY_FESTIVAL_TIME, DEFAULT_NOTIFY_FESTIVAL_TIME)
        ),
        CONF_NOTIFY_MEMORIAL_TIME: _memorial_time_value(src),
        CONF_NOTIFY_LICENSE_TIME: str(
            src.get(CONF_NOTIFY_LICENSE_TIME, DEFAULT_NOTIFY_LICENSE_TIME)
        ),
        CONF_NEAR_FESTIVAL_DAYS: near_fest,
        CONF_NEAR_BIRTHDAY_DAYS: near_bday,
        CONF_NEAR_ANNIVERSARY_DAYS: near_anni,
        CONF_NEAR_LICENSE_DAYS: near_lic,
        CONF_HOLIDAY_AUTO: bool(src.get(CONF_HOLIDAY_AUTO, DEFAULT_HOLIDAY_AUTO)),
        CONF_AI_ENABLED: bool(src.get(CONF_AI_ENABLED, DEFAULT_AI_ENABLED)),
        CONF_AI_API_URL: str(src.get(CONF_AI_API_URL, DEFAULT_AI_API_URL) or DEFAULT_AI_API_URL),
        CONF_AI_API_KEY: str(src.get(CONF_AI_API_KEY, DEFAULT_AI_API_KEY) or ""),
        CONF_AI_MODEL: str(src.get(CONF_AI_MODEL, DEFAULT_AI_MODEL) or DEFAULT_AI_MODEL),
        CONF_NOTIFY_RULES_ENABLED: bool(
            src.get(CONF_NOTIFY_RULES_ENABLED, DEFAULT_NOTIFY_RULES_ENABLED)
        ),
        CONF_NOTIFY_RULES: rules,
        CONF_INTENT_ENABLED: bool(
            src.get(CONF_INTENT_ENABLED, DEFAULT_INTENT_ENABLED)
        ),
    }


def _as_ymd(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip().replace("/", "-")
    if "T" in text:
        text = text.split("T", 1)[0]
    if " " in text:
        text = text.split(" ", 1)[0]
    parts = text.split("-")
    if len(parts) == 3:
        try:
            y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
            return date(y, m, d).isoformat()
        except ValueError:
            pass
    return text[:10]


def _valid_ymd(value: Any) -> bool:
    text = _as_ymd(value)
    if not _YMD_RE.match(text):
        return False
    try:
        datetime.strptime(text, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def _valid_md(value: Any) -> bool:
    text = str(value).replace("/", "-").strip()[:5]
    if not _MD_RE.match(text):
        return False
    try:
        datetime.strptime(text, "%m-%d")
        return True
    except ValueError:
        return False


def _kind_fields() -> dict:
    return {
        vol.Required(CONF_ITEM_KIND): SelectSelector(
            SelectSelectorConfig(
                options=list(ITEM_KINDS),
                mode=SelectSelectorMode.DROPDOWN,
                translation_key="item_kind",
            )
        )
    }


def _license_fields() -> dict:
    return {
        vol.Required(CONF_ITEM_NAME): TextSelector(),
        vol.Required(CONF_ITEM_DATE): TextSelector(
            TextSelectorConfig(placeholder="YYYY-MM-DD")
        ),
    }


def _anniversary_fields() -> dict:
    return {
        vol.Required(CONF_ITEM_NAME): TextSelector(),
        vol.Required(CONF_ITEM_DATE): TextSelector(
            TextSelectorConfig(placeholder="YYYY-MM-DD")
        ),
        vol.Required(CONF_ITEM_TYPE): SelectSelector(
            SelectSelectorConfig(
                options=[
                    str(ANNIVERSARY_TYPE_SUM),
                    str(ANNIVERSARY_TYPE_SOLAR),
                    str(ANNIVERSARY_TYPE_LUNAR),
                ],
                mode=SelectSelectorMode.DROPDOWN,
                translation_key="anniversary_type",
            )
        ),
    }


def _birthday_fields() -> dict:
    return {
        vol.Required(CONF_ITEM_NAME): TextSelector(),
        vol.Required(CONF_ITEM_DATE): TextSelector(
            TextSelectorConfig(placeholder="YYYY-MM-DD")
        ),
        vol.Required(CONF_ITEM_TYPE): SelectSelector(
            SelectSelectorConfig(
                options=[
                    str(BIRTHDAY_TYPE_LUNAR),
                    str(BIRTHDAY_TYPE_SOLAR),
                ],
                mode=SelectSelectorMode.DROPDOWN,
                translation_key="birthday_type",
            )
        ),
    }


def _legal_fields() -> dict:
    return {
        vol.Required(CONF_ITEM_NAME): TextSelector(),
        vol.Required(CONF_ITEM_DATE): TextSelector(
            TextSelectorConfig(placeholder="MM-DD")
        ),
        vol.Required(CONF_FREEWAY): SelectSelector(
            SelectSelectorConfig(
                options=["0", "1"],
                mode=SelectSelectorMode.DROPDOWN,
                translation_key="freeway",
            )
        ),
        vol.Optional(CONF_REPAIR): TextSelector(
            TextSelectorConfig(placeholder="MM-DD,MM-DD 或空")
        ),
        vol.Optional(CONF_HOLIDAY): TextSelector(
            TextSelectorConfig(placeholder="MM-DD,MM-DD")
        ),
    }


def _fields_for_kind(kind: str) -> dict:
    if kind == ITEM_KIND_LICENSE:
        return _license_fields()
    if kind == ITEM_KIND_BIRTHDAY:
        return _birthday_fields()
    if kind == ITEM_KIND_ANNIVERSARY:
        return _anniversary_fields()
    return _legal_fields()


def _parse_md_list(raw: Any) -> list[str] | int:
    if raw in (None, "", 0, "0"):
        return 0
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    parts = [p.strip() for p in str(raw).replace("，", ",").split(",") if p.strip()]
    return parts or 0


def _normalize_license(src: dict, item_id: str | None = None) -> dict:
    return {
        CONF_ITEM_ID: item_id or str(uuid.uuid4()),
        CONF_ITEM_NAME: str(src[CONF_ITEM_NAME]).strip(),
        CONF_ITEM_DATE: _as_ymd(src[CONF_ITEM_DATE]),
    }


def _normalize_anniversary(src: dict, item_id: str | None = None) -> dict:
    try:
        atype = int(src[CONF_ITEM_TYPE])
    except (TypeError, ValueError, KeyError):
        atype = ANNIVERSARY_TYPE_SOLAR
    return {
        CONF_ITEM_ID: item_id or str(uuid.uuid4()),
        CONF_ITEM_NAME: str(src[CONF_ITEM_NAME]).strip(),
        CONF_ITEM_DATE: _as_ymd(src[CONF_ITEM_DATE]),
        CONF_ITEM_TYPE: atype,
    }


def _normalize_birthday(src: dict, item_id: str | None = None) -> dict:
    try:
        btype = int(src[CONF_ITEM_TYPE])
    except (TypeError, ValueError, KeyError):
        btype = BIRTHDAY_TYPE_LUNAR
    if btype not in (BIRTHDAY_TYPE_LUNAR, BIRTHDAY_TYPE_SOLAR):
        btype = BIRTHDAY_TYPE_LUNAR
    return {
        CONF_ITEM_ID: item_id or str(uuid.uuid4()),
        CONF_ITEM_NAME: str(src[CONF_ITEM_NAME]).strip(),
        CONF_ITEM_DATE: _as_ymd(src[CONF_ITEM_DATE]),
        CONF_ITEM_TYPE: btype,
    }


def _normalize_legal(src: dict, item_id: str | None = None) -> dict:
    try:
        freeway = int(src.get(CONF_FREEWAY) or 0)
    except (TypeError, ValueError):
        freeway = 0
    return {
        CONF_ITEM_ID: item_id or str(uuid.uuid4()),
        CONF_ITEM_NAME: str(src[CONF_ITEM_NAME]).strip(),
        CONF_ITEM_DATE: str(src[CONF_ITEM_DATE]).replace("/", "-").strip()[:5],
        CONF_FREEWAY: freeway,
        CONF_REPAIR: _parse_md_list(src.get(CONF_REPAIR)),
        CONF_HOLIDAY: _parse_md_list(src.get(CONF_HOLIDAY)),
    }


def _normalize_for_kind(kind: str, src: dict, item_id: str | None = None) -> dict:
    if kind == ITEM_KIND_LICENSE:
        return _normalize_license(src, item_id)
    if kind == ITEM_KIND_BIRTHDAY:
        return _normalize_birthday(src, item_id)
    if kind == ITEM_KIND_ANNIVERSARY:
        return _normalize_anniversary(src, item_id)
    return _normalize_legal(src, item_id)


def _validate_for_kind(kind: str, user_input: dict) -> dict[str, str]:
    errors: dict[str, str] = {}
    if kind == ITEM_KIND_LEGAL:
        if not _valid_md(user_input.get(CONF_ITEM_DATE)):
            errors[CONF_ITEM_DATE] = "invalid_date"
        repair = _parse_md_list(user_input.get(CONF_REPAIR))
        holiday = _parse_md_list(user_input.get(CONF_HOLIDAY))
        if isinstance(repair, list) and any(not _valid_md(x) for x in repair):
            errors[CONF_REPAIR] = "invalid_date"
        if isinstance(holiday, list) and any(not _valid_md(x) for x in holiday):
            errors[CONF_HOLIDAY] = "invalid_date"
    elif not _valid_ymd(user_input.get(CONF_ITEM_DATE)):
        errors[CONF_ITEM_DATE] = "invalid_date"
    return errors


def _md_list_to_str(raw: Any) -> str:
    if raw in (None, "", 0, "0"):
        return ""
    if isinstance(raw, list):
        return ",".join(str(x).strip() for x in raw if str(x).strip())
    return str(raw).replace("，", ",").strip()


def _suggested_for_kind(kind: str, current: dict) -> dict:
    if kind == ITEM_KIND_LICENSE:
        return {
            CONF_ITEM_NAME: str(current.get(CONF_ITEM_NAME) or ""),
            CONF_ITEM_DATE: str(current.get(CONF_ITEM_DATE) or ""),
        }
    if kind == ITEM_KIND_BIRTHDAY:
        return {
            CONF_ITEM_NAME: str(current.get(CONF_ITEM_NAME) or ""),
            CONF_ITEM_DATE: str(current.get(CONF_ITEM_DATE) or ""),
            CONF_ITEM_TYPE: str(current.get(CONF_ITEM_TYPE, BIRTHDAY_TYPE_LUNAR)),
        }
    if kind == ITEM_KIND_ANNIVERSARY:
        return {
            CONF_ITEM_NAME: str(current.get(CONF_ITEM_NAME) or ""),
            CONF_ITEM_DATE: str(current.get(CONF_ITEM_DATE) or ""),
            CONF_ITEM_TYPE: str(current.get(CONF_ITEM_TYPE, ANNIVERSARY_TYPE_SOLAR)),
        }
    try:
        freeway = str(int(current.get(CONF_FREEWAY) or 0))
    except (TypeError, ValueError):
        freeway = "0"
    return {
        CONF_ITEM_NAME: str(current.get(CONF_ITEM_NAME) or ""),
        CONF_ITEM_DATE: str(current.get(CONF_ITEM_DATE) or ""),
        CONF_FREEWAY: freeway,
        CONF_REPAIR: _md_list_to_str(current.get(CONF_REPAIR)),
        CONF_HOLIDAY: _md_list_to_str(current.get(CONF_HOLIDAY)),
    }


def _ensure_ids(items: list) -> list[dict]:
    out: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        if not row.get(CONF_ITEM_ID):
            row[CONF_ITEM_ID] = str(uuid.uuid4())
        out.append(row)
    return out


def _item_id(item: dict) -> str:
    return str(item.get(CONF_ITEM_ID) or "")


def _pack_ref(kind: str, index: int) -> str:
    return f"{kind}:{index}"


def _unpack_ref(raw: str) -> tuple[str, int] | None:
    if not raw or ":" not in raw:
        return None
    kind, idx_raw = raw.split(":", 1)
    if kind not in ITEM_KIND_TO_KEY:
        return None
    try:
        index = int(idx_raw)
    except ValueError:
        return None
    if index < 0:
        return None
    return kind, index


def _all_item_options(options: dict) -> list[dict]:
    out: list[dict] = []
    for kind, key in ITEM_KIND_TO_KEY.items():
        items = options.get(key) or []
        if not isinstance(items, list):
            continue
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            label = item.get(CONF_ITEM_NAME) or str(index + 1)
            out.append(
                {
                    "value": _pack_ref(kind, index),
                    "label": f"[{_KIND_LABEL[kind]}] {label}",
                }
            )
    return out


def _sanitize_options(options: dict) -> dict:
    data = deepcopy(options)
    for key in (CONF_LICENSES, CONF_ANNIVERSARIES, CONF_BIRTHDAYS, CONF_LEGAL):
        items = data.get(key)
        if isinstance(items, list):
            cleaned: list[dict] = []
            for item in _ensure_ids(items):
                row = dict(item)
                if CONF_ITEM_DATE in row and row[CONF_ITEM_DATE] is not None:
                    if key == CONF_LEGAL:
                        row[CONF_ITEM_DATE] = (
                            str(row[CONF_ITEM_DATE]).replace("/", "-").strip()[:5]
                        )
                    else:
                        row[CONF_ITEM_DATE] = _as_ymd(row[CONF_ITEM_DATE])
                cleaned.append(row)
            data[key] = cleaned
        else:
            data[key] = []
    if CONF_NOTIFY_CALENDAR_TIME in data:
        data[CONF_NOTIFY_CALENDAR_TIME] = str(data[CONF_NOTIFY_CALENDAR_TIME])
    if CONF_NOTIFY_FESTIVAL_TIME in data:
        data[CONF_NOTIFY_FESTIVAL_TIME] = str(data[CONF_NOTIFY_FESTIVAL_TIME])
    if CONF_NOTIFY_LICENSE_TIME in data:
        data[CONF_NOTIFY_LICENSE_TIME] = str(data[CONF_NOTIFY_LICENSE_TIME])
    if CONF_NOTIFY_MEMORIAL_TIME in data:
        data[CONF_NOTIFY_MEMORIAL_TIME] = str(data[CONF_NOTIFY_MEMORIAL_TIME])
    if CONF_NEAR_FESTIVAL_DAYS in data:
        try:
            data[CONF_NEAR_FESTIVAL_DAYS] = int(data[CONF_NEAR_FESTIVAL_DAYS])
        except (TypeError, ValueError):
            data[CONF_NEAR_FESTIVAL_DAYS] = DEFAULT_NEAR_FESTIVAL_DAYS
    if CONF_NEAR_LICENSE_DAYS in data:
        try:
            data[CONF_NEAR_LICENSE_DAYS] = int(data[CONF_NEAR_LICENSE_DAYS])
        except (TypeError, ValueError):
            data[CONF_NEAR_LICENSE_DAYS] = DEFAULT_NEAR_LICENSE_DAYS
    if CONF_NEAR_BIRTHDAY_DAYS in data:
        try:
            data[CONF_NEAR_BIRTHDAY_DAYS] = int(data[CONF_NEAR_BIRTHDAY_DAYS])
        except (TypeError, ValueError):
            data[CONF_NEAR_BIRTHDAY_DAYS] = DEFAULT_NEAR_BIRTHDAY_DAYS
    if CONF_NEAR_ANNIVERSARY_DAYS in data:
        try:
            data[CONF_NEAR_ANNIVERSARY_DAYS] = int(data[CONF_NEAR_ANNIVERSARY_DAYS])
        except (TypeError, ValueError):
            data[CONF_NEAR_ANNIVERSARY_DAYS] = DEFAULT_NEAR_ANNIVERSARY_DAYS
    if CONF_NOTIFY in data:
        data[CONF_NOTIFY] = _notify_values(data.get(CONF_NOTIFY))
    if CONF_HOLIDAY_AUTO in data:
        data[CONF_HOLIDAY_AUTO] = bool(data.get(CONF_HOLIDAY_AUTO, DEFAULT_HOLIDAY_AUTO))
    if CONF_NOTIFY_CALENDAR in data:
        data[CONF_NOTIFY_CALENDAR] = bool(
            data.get(CONF_NOTIFY_CALENDAR, DEFAULT_NOTIFY_CALENDAR)
        )
    if CONF_NOTIFY_MEMORIAL in data:
        data[CONF_NOTIFY_MEMORIAL] = bool(
            data.get(CONF_NOTIFY_MEMORIAL, DEFAULT_NOTIFY_MEMORIAL)
        )
    if CONF_LANGUAGE in data:
        lang = str(data.get(CONF_LANGUAGE) or DEFAULT_LANGUAGE)
        data[CONF_LANGUAGE] = lang if lang in ("zh-Hans", "zh-Hant") else DEFAULT_LANGUAGE
    if CONF_AI_ENABLED in data:
        data[CONF_AI_ENABLED] = bool(data.get(CONF_AI_ENABLED, DEFAULT_AI_ENABLED))
    if CONF_AI_API_URL in data:
        data[CONF_AI_API_URL] = str(
            data.get(CONF_AI_API_URL) or DEFAULT_AI_API_URL
        )
    if CONF_AI_API_KEY in data:
        data[CONF_AI_API_KEY] = str(data.get(CONF_AI_API_KEY) or "")
    if CONF_AI_MODEL in data:
        data[CONF_AI_MODEL] = str(data.get(CONF_AI_MODEL) or DEFAULT_AI_MODEL)
    if CONF_NOTIFY_RULES_ENABLED in data:
        data[CONF_NOTIFY_RULES_ENABLED] = bool(
            data.get(CONF_NOTIFY_RULES_ENABLED, DEFAULT_NOTIFY_RULES_ENABLED)
        )
    if CONF_NOTIFY_RULES in data:
        rules, err = _parse_notify_rules(data.get(CONF_NOTIFY_RULES))
        data[CONF_NOTIFY_RULES] = rules if rules is not None else DEFAULT_NOTIFY_RULES
    if CONF_INTENT_ENABLED in data:
        data[CONF_INTENT_ENABLED] = bool(
            data.get(CONF_INTENT_ENABLED, DEFAULT_INTENT_ENABLED)
        )
    return data


class HolidayDailyConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=self.add_suggested_values_to_schema(
                    vol.Schema(
                        {
                            vol.Required(CONF_NAME, default="中国节日"): TextSelector(),
                            **_global_fields(self.hass),
                        }
                    ),
                    {
                        CONF_NAME: "中国节日",
                        **_global_values({}),
                    },
                ),
            )
        rules, err = _parse_notify_rules(user_input.get(CONF_NOTIFY_RULES))
        if err:
            errors[CONF_NOTIFY_RULES] = err
            return self.async_show_form(
                step_id="user",
                data_schema=self.add_suggested_values_to_schema(
                    vol.Schema(
                        {
                            vol.Required(CONF_NAME, default="中国节日"): TextSelector(),
                            **_global_fields(self.hass, user_input),
                        }
                    ),
                    user_input,
                ),
                errors=errors,
            )
        user_input[CONF_NOTIFY_RULES] = rules
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        name = user_input.pop(CONF_NAME)
        options = _sanitize_options(
            {
                **_global_options(user_input),
                CONF_LICENSES: await self.hass.async_add_executor_job(default_licenses),
                CONF_ANNIVERSARIES: await self.hass.async_add_executor_job(
                    default_anniversaries
                ),
                CONF_BIRTHDAYS: await self.hass.async_add_executor_job(default_birthdays),
                CONF_LEGAL: [],
                "seed_version": 3,
            }
        )
        return self.async_create_entry(title=name, data={CONF_NAME: name}, options=options)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return HolidayDailyOptionsFlow()


class HolidayDailyOptionsFlow(OptionsFlow):
    def __init__(self) -> None:
        super().__init__()
        self._edit_ref: str | None = None
        self._pending_kind: str | None = None
        self._working: dict[str, list[dict]] = {}

    def _opts(self) -> dict[str, Any]:
        return _sanitize_options(dict(self.config_entry.options))

    def _load_working(self) -> None:
        if self._working:
            return
        opts = self.config_entry.options
        for key in ITEM_KIND_TO_KEY.values():
            self._working[key] = _ensure_ids(list(opts.get(key) or []))

    def _choices(self) -> list[dict]:
        self._load_working()
        return _all_item_options(self._working)

    def _save(self, options: dict[str, Any]) -> ConfigFlowResult:
        for key, items in self._working.items():
            options[key] = items
        self._working.clear()
        self._edit_ref = None
        self._pending_kind = None
        return self.async_create_entry(title="", data=_sanitize_options(options))

    def _items(self, key: str) -> list[dict]:
        self._load_working()
        return self._working[key]

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="init",
            menu_options=[
                "global",
                "add_item",
                "edit_item",
                "remove_item",
            ],
        )

    async def async_step_global(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        current = {**self.config_entry.data, **self.config_entry.options}
        errors: dict[str, str] = {}
        if user_input is not None:
            rules, err = _parse_notify_rules(user_input.get(CONF_NOTIFY_RULES))
            if err:
                errors[CONF_NOTIFY_RULES] = err
            else:
                user_input[CONF_NOTIFY_RULES] = rules
                options = self._opts()
                options.update(_global_options(user_input))
                return self._save(options)
        return self.async_show_form(
            step_id="global",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(_global_fields(self.hass, current)),
                user_input or _global_values(current),
            ),
            errors=errors or None,
        )

    async def async_step_add_item(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is None:
            return self.async_show_form(
                step_id="add_item",
                data_schema=vol.Schema(_kind_fields()),
            )
        self._pending_kind = user_input[CONF_ITEM_KIND]
        return await self.async_step_add_item_form()

    async def async_step_add_item_form(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        kind = self._pending_kind
        if not kind:
            return await self.async_step_add_item()
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate_for_kind(kind, user_input)
            if not errors:
                key = ITEM_KIND_TO_KEY[kind]
                items = list(self._items(key))
                items.append(_normalize_for_kind(kind, user_input))
                self._working[key] = items
                options = self._opts()
                options[key] = items
                return self._save(options)
        return self.async_show_form(
            step_id="add_item_form",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(_fields_for_kind(kind)), user_input or {}
            ),
            errors=errors,
        )

    async def async_step_edit_item(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._load_working()
        choices = self._choices()
        if not choices:
            return self.async_abort(reason="no_items")
        if user_input is None:
            return self.async_show_form(
                step_id="edit_item",
                data_schema=vol.Schema(
                    {
                        vol.Required("item"): SelectSelector(
                            SelectSelectorConfig(options=choices)
                        )
                    }
                ),
            )
        self._edit_ref = str(user_input["item"])
        return await self.async_step_edit_item_form()

    async def async_step_edit_item_form(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if not self._edit_ref:
            return await self.async_step_edit_item()
        packed = _unpack_ref(self._edit_ref)
        if not packed:
            self._edit_ref = None
            return await self.async_step_edit_item()
        kind, index = packed
        key = ITEM_KIND_TO_KEY[kind]
        items = self._items(key)
        if index >= len(items):
            self._edit_ref = None
            return self.async_abort(reason="no_items")
        current = items[index]
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate_for_kind(kind, user_input)
            if not errors:
                item_id = _item_id(current) or None
                updated = _normalize_for_kind(kind, user_input, item_id)
                new_items = list(items)
                new_items[index] = updated
                self._working[key] = new_items
                options = self._opts()
                options[key] = new_items
                return self._save(options)
        suggested = dict(user_input or _suggested_for_kind(kind, current))
        for field in (
            CONF_ITEM_NAME,
            CONF_ITEM_DATE,
            CONF_FREEWAY,
            CONF_REPAIR,
            CONF_HOLIDAY,
            CONF_ITEM_TYPE,
        ):
            if field in suggested and suggested[field] is not None:
                suggested[field] = str(suggested[field])
        return self.async_show_form(
            step_id="edit_item_form",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(_fields_for_kind(kind)),
                suggested,
            ),
            errors=errors or None,
        )

    async def async_step_remove_item(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        choices = self._choices()
        if not choices:
            return self.async_abort(reason="no_items")
        if user_input is not None:
            packed = _unpack_ref(str(user_input["item"]))
            if packed:
                kind, index = packed
                key = ITEM_KIND_TO_KEY[kind]
                items = list(self._items(key))
                if 0 <= index < len(items):
                    items.pop(index)
                    self._working[key] = items
                    options = self._opts()
                    options[key] = items
                    return self._save(options)
            return await self.async_step_remove_item()
        return self.async_show_form(
            step_id="remove_item",
            data_schema=vol.Schema(
                {
                    vol.Required("item"): SelectSelector(
                        SelectSelectorConfig(options=choices)
                    )
                }
            ),
        )
