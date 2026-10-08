from __future__ import annotations

import math
import re
from typing import Any


def wgs84_to_gcj02(lng: float, lat: float) -> tuple[float, float]:
    if not (72.004 <= lng <= 137.8347 and 0.8293 <= lat <= 55.8271):
        return lng, lat

    a = 6378245.0
    ee = 0.00669342162296594323

    def _transform_lat(x: float, y: float) -> float:
        ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
        ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
        ret += (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
        ret += (160.0 * math.sin(y / 12.0 * math.pi) + 320.0 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
        return ret

    def _transform_lng(x: float, y: float) -> float:
        ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
        ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
        ret += (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
        ret += (150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
        return ret

    dlat = _transform_lat(lng - 105.0, lat - 35.0)
    dlng = _transform_lng(lng - 105.0, lat - 35.0)
    radlat = lat / 180.0 * math.pi
    magic = math.sin(radlat)
    magic = 1 - ee * magic * magic
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((a * (1 - ee)) / (magic * sqrtmagic) * math.pi)
    dlng = (dlng * 180.0) / (a / sqrtmagic * math.cos(radlat) * math.pi)

    return lng + dlng, lat + dlat


def get_stable_device_id(device: dict[str, Any]) -> str | None:
    device_id = device.get("deviceId") or device.get("device_id")
    if device_id:
        return str(device_id)
    device_sn = device.get("deviceSn")
    if device_sn:
        return str(device_sn)
    uniq_resource = device.get("uniqResource")
    if uniq_resource:
        return str(uniq_resource)
    return None


def generate_slug(model: str, device_id: str = "") -> str:
    if not model or model.strip().lower() in ("unknown", ""):
        if device_id and len(device_id) >= 6:
            return f"honor_{device_id[:6].lower()}"
        raise ValueError("无法生成 slug：model 和 device_id 均为空")

    text = model.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text)
    text = text.strip("_")

    if not text.startswith("honor_"):
        text = f"honor_{text}"

    return text or f"honor_{device_id[:6].lower()}"
