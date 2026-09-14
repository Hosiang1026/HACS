from __future__ import annotations

from collections import Counter
from typing import Any

from .const import LOTTERY_SSQ

_RULES = {
    LOTTERY_SSQ: {"red": (1, 33, 6), "blue": (1, 16, 1), "pad": 2},
}


def _parse_nums(raw: Any) -> list[int]:
    if raw is None or raw == "":
        return []
    if isinstance(raw, (list, tuple)):
        out: list[int] = []
        for x in raw:
            try:
                out.append(int(str(x).strip()))
            except (TypeError, ValueError):
                continue
        return out
    text = str(raw).replace("，", ",").replace(" ", ",")
    out = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(int(part))
        except ValueError:
            continue
    return out


def _fmt(nums: list[int], pad: int) -> str:
    return ",".join(f"{n:0{pad}d}" for n in nums)


def _top_n(
    counter: Counter[int],
    lo: int,
    hi: int,
    n: int,
    exclude: set[int] | None = None,
) -> list[int]:
    exclude = exclude or set()
    ranked = sorted(
        (
            (num, cnt)
            for num, cnt in counter.items()
            if lo <= num <= hi and num not in exclude
        ),
        key=lambda x: (-x[1], x[0]),
    )
    picked = [num for num, _ in ranked[:n]]
    if len(picked) < n:
        for num in range(lo, hi + 1):
            if num in exclude or num in picked:
                continue
            picked.append(num)
            if len(picked) >= n:
                break
    return sorted(picked)


def _cold_n(
    counter: Counter[int],
    lo: int,
    hi: int,
    n: int,
    exclude: set[int] | None = None,
) -> list[int]:
    exclude = exclude or set()
    ranked = sorted(
        ((num, counter.get(num, 0)) for num in range(lo, hi + 1) if num not in exclude),
        key=lambda x: (x[1], x[0]),
    )
    return sorted(num for num, _ in ranked[:n])


def predict_from_history(
    lottery_type: str, history: list[dict[str, Any]]
) -> dict[str, Any] | None:
    if lottery_type != LOTTERY_SSQ:
        return None
    rule = _RULES[LOTTERY_SSQ]
    if not history:
        return None
    pad = int(rule["pad"])
    red_lo, red_hi, red_n = rule["red"]
    blue_lo, blue_hi, blue_n = rule["blue"]

    red_counter: Counter[int] = Counter()
    blue_counter: Counter[int] = Counter()
    for item in history:
        for n in _parse_nums(item.get("red") or item.get("content")):
            if red_lo <= n <= red_hi:
                red_counter[n] += 1
        for n in _parse_nums(item.get("blue")):
            if blue_lo <= n <= blue_hi:
                blue_counter[n] += 1

    red = _top_n(red_counter, red_lo, red_hi, red_n)
    cold_red = _cold_n(red_counter, red_lo, red_hi, red_n)
    blue_nums = _top_n(blue_counter, blue_lo, blue_hi, blue_n, exclude=set(red))
    cold_blue_nums = _cold_n(
        blue_counter, blue_lo, blue_hi, blue_n, exclude=set(red)
    )
    red_s = _fmt(red, pad)
    blue = _fmt(blue_nums, pad)
    return {
        "value": f"{red_s}+{blue}",
        "red": red_s,
        "blue": blue,
        "method": "frequency",
        "based_on": len(history),
        "hot_red": red_s,
        "cold_red": _fmt(cold_red, pad),
        "hot_blue": blue,
        "cold_blue": _fmt(cold_blue_nums, pad),
    }
