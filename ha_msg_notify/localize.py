from functools import lru_cache
import json
from pathlib import Path
from typing import Any

from .const import DOMAIN

_DIR = Path(__file__).parent / "translations"


@lru_cache(maxsize=8)
def _load(lang: str) -> dict[str, Any]:
    path = _DIR / f"{lang}.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _lang(hass: Any) -> str:
    lang = getattr(getattr(hass, "config", None), "language", None) or "en"
    if lang.startswith("zh"):
        return "zh-Hans"
    return lang


def _dig(data: dict[str, Any], parts: list[str]) -> Any:
    cur: Any = data
    for part in parts:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def translate(hass: Any, *path: str, default: str | None = None) -> str:
    lang = _lang(hass)
    for code in (lang, "zh-Hans" if lang.startswith("zh") else "", "en"):
        if not code:
            continue
        val = _dig(_load(code), list(path))
        if isinstance(val, str) and val:
            return val
    return default or (path[-1] if path else "")


def selector_options(hass: Any, key: str, values: list[str]) -> list[dict[str, str]]:
    return [
        {
            "value": value,
            "label": translate(hass, "selector", key, "options", value, default=value),
        }
        for value in values
    ]


def _file_msg(lang: str | None, key: str) -> str | None:
    lang = lang or "en"
    data = _load(lang)
    if not data and lang.startswith("zh"):
        data = _load("zh-Hans")
    if not data:
        data = _load("en")
    item = (data.get("exceptions") or {}).get(key)
    if isinstance(item, dict):
        return item.get("message")
    return None


def tr(hass: Any, key: str, **kwargs: Any) -> str:
    lang = _lang(hass)
    text = None
    try:
        from homeassistant.helpers.translation import async_get_cached_translations

        trans = async_get_cached_translations(hass, lang, "exceptions", DOMAIN)
        text = trans.get(f"component.{DOMAIN}.exceptions.{key}.message")
    except Exception:
        text = None
    if not text:
        text = _file_msg(lang, key) or _file_msg("en", key) or key
    text = str(text).replace("\\n", "\n")
    if kwargs:
        return text.format(**kwargs)
    return text
