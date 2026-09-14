from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN

STORAGE_VERSION = 1


class CarStatsStore:
    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._store = Store(hass, STORAGE_VERSION, DOMAIN)
        self._data: dict[str, Any] = {"entries": {}}
        self._lock = asyncio.Lock()
        self._listeners: list[Callable[[], Coroutine[Any, Any, None]]] = []

    async def async_load(self) -> None:
        data = await self._store.async_load()
        if isinstance(data, dict) and isinstance(data.get("entries"), dict):
            self._data = data
        else:
            self._data = {"entries": {}}

    def async_add_listener(self, listener: Callable[[], Coroutine[Any, Any, None]]) -> Callable[[], None]:
        self._listeners.append(listener)

        def _remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return _remove

    async def _save(self, notify: bool = True) -> None:
        await self._store.async_save(self._data)
        if notify:
            for listener in list(self._listeners):
                self.hass.async_create_task(listener())

    async def _mutate(self, fn, notify: bool = True) -> Any:
        async with self._lock:
            result = fn()
            await self._save(notify=notify)
            return result

    def snapshot(self, entry_id: str) -> dict[str, Any]:
        snap = self._entry(entry_id).get("snapshot")
        return snap if isinstance(snap, dict) else {}

    async def save_snapshot(self, entry_id: str, snapshot: dict[str, Any]) -> None:
        def _do() -> None:
            self._entry(entry_id)["snapshot"] = snapshot

        await self._mutate(_do, notify=False)

    def _entry(self, entry_id: str) -> dict[str, Any]:
        entries: dict[str, Any] = self._data.setdefault("entries", {})
        if entry_id not in entries:
            entries[entry_id] = {
                "refuels": [],
                "expenses": [],
                "maintenances": [],
                "odometer": 0,
                "yearly_history": {},
            }
        return entries[entry_id]

    def get(self, entry_id: str) -> dict[str, Any]:
        return self._entry(entry_id)

    def all_entries(self) -> dict[str, Any]:
        return self._data.get("entries", {})

    async def remove_entry(self, entry_id: str) -> None:
        def _do() -> None:
            self._data.setdefault("entries", {}).pop(entry_id, None)

        await self._mutate(_do, notify=False)

    async def set_odometer(self, entry_id: str, odometer: float) -> None:
        def _do() -> None:
            self._entry(entry_id)["odometer"] = float(odometer)

        await self._mutate(_do)

    async def add_refuel(
        self,
        entry_id: str,
        odo: float,
        liters: float,
        cost: float,
        price: float,
        full: bool = True,
        station: str = "",
        update_odometer: bool = True,
    ) -> None:
        def _do() -> None:
            rec = self._entry(entry_id)
            item: dict[str, Any] = {
                "ts": dt_util.now().isoformat(),
                "odo": float(odo),
                "liters": float(liters),
                "cost": float(cost),
                "price": float(price),
                "full": bool(full),
            }
            name = (station or "").strip()
            if name:
                item["station"] = name
            rec["refuels"].append(item)
            if update_odometer and float(odo) > 0:
                rec["odometer"] = float(odo)

        await self._mutate(_do)

    async def add_expense(self, entry_id: str, exp_type: str, amount: float) -> None:
        def _do() -> None:
            self._entry(entry_id)["expenses"].append(
                {
                    "ts": dt_util.now().isoformat(),
                    "type": exp_type,
                    "amount": float(amount),
                }
            )

        await self._mutate(_do)

    async def add_maintenance(
        self,
        entry_id: str,
        odo: float,
        maint_type: str = "常规",
        cost: float = 0,
        next_odo: float | None = None,
        next_date: str | None = None,
        ts: str | None = None,
    ) -> None:
        def _do() -> None:
            self._entry(entry_id)["maintenances"].append(
                {
                    "ts": ts or dt_util.now().isoformat(),
                    "odo": float(odo),
                    "type": maint_type,
                    "cost": float(cost),
                    "next_odo": next_odo,
                    "next_date": next_date,
                }
            )

        await self._mutate(_do)

    async def update_fields(self, entry_id: str, **kwargs: Any) -> None:
        def _do() -> None:
            self._entry(entry_id).update(kwargs)

        await self._mutate(_do)
