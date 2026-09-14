from __future__ import annotations

from typing import Any


def convert_text(text: Any, language: str) -> str:
    if text is None:
        return ""
    body = str(text)
    if language != "zh-Hant":
        return body
    try:
        import zhconv

        return zhconv.convert(body, "zh-hant")
    except Exception:
        return body


def convert_obj(obj: Any, language: str) -> Any:
    if language != "zh-Hant":
        return obj
    if isinstance(obj, str):
        return convert_text(obj, language)
    if isinstance(obj, list):
        return [convert_obj(x, language) for x in obj]
    if isinstance(obj, tuple):
        return tuple(convert_obj(x, language) for x in obj)
    if isinstance(obj, dict):
        return {k: convert_obj(v, language) for k, v in obj.items()}
    return obj
