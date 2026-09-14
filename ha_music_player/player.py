from __future__ import annotations

import os
import random
from ipaddress import ip_address
from typing import Any
from urllib.parse import urlparse

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.network import get_url
from homeassistant.util import dt as dt_util

from .const import (
    AUDIO_EXT,
    CONF_ENABLE_XIAOAI,
    CONF_MEDIA_PLAYERS,
    CONF_XIAOMI_HOME,
    CONF_XIAOMI_MIOT,
    DOMAIN,
)
from .library import MusicLibrary


def _ok_lan_ip(host: str) -> bool:
    try:
        addr = ip_address(host)
    except ValueError:
        return False
    if addr.version != 4 or not addr.is_private or addr.is_loopback or addr.is_link_local:
        return False
    b1, b2 = addr.packed[0], addr.packed[1]
    if b1 == 172 and b2 >= 17:
        return False
    return True


async def _adapter_ip(hass: HomeAssistant) -> str | None:
    try:
        from homeassistant.components.network import async_get_adapters

        adapters = await async_get_adapters(hass)
    except Exception:
        return None
    cands: list[tuple[bool, str]] = []
    for ad in adapters:
        enabled = ad.get("enabled", True) if isinstance(ad, dict) else getattr(ad, "enabled", True)
        default = ad.get("default", False) if isinstance(ad, dict) else getattr(ad, "default", False)
        ipv4 = ad.get("ipv4") if isinstance(ad, dict) else getattr(ad, "ipv4", None)
        if not enabled:
            continue
        for item in ipv4 or []:
            addr = item.get("address") if isinstance(item, dict) else getattr(item, "address", None)
            if addr and _ok_lan_ip(addr):
                cands.append((bool(default), addr))
    cands.sort(key=lambda x: not x[0])
    return cands[0][1] if cands else None


async def _lan_base(hass: HomeAssistant) -> str:
    api = hass.config.api
    scheme = "https" if api and api.use_ssl else "http"
    port = (api.port if api and api.port else None) or 8123
    try:
        base = get_url(hass, prefer_external=False, allow_cloud=False, allow_ip=True)
        parsed = urlparse(base)
        host = parsed.hostname or ""
        if _ok_lan_ip(host):
            return base.rstrip("/")
    except HomeAssistantError:
        pass
    if api and api.local_ip and _ok_lan_ip(api.local_ip):
        return f"{scheme}://{api.local_ip}:{port}"
    ip = await _adapter_ip(hass)
    if ip:
        return f"{scheme}://{ip}:{port}"
    try:
        return get_url(hass, prefer_external=False).rstrip("/")
    except HomeAssistantError:
        return get_url(hass).rstrip("/")


class RuntimePlayer:
    def __init__(self, hass: HomeAssistant, entry, library: MusicLibrary) -> None:
        self.hass = hass
        self.entry = entry
        self.library = library
        self.index = 0
        self.playing = False
        self.position = 0.0
        self.duration = 0.0
        self.position_updated = dt_util.utcnow()
        self.volume = 0.8
        self.shuffle = False
        self.repeat = "all"
        self.source = "browser"
        self.active = False
        self._entity = None

    def attach(self, entity) -> None:
        self._entity = entity

    def notify(self) -> None:
        if self._entity is not None and self._entity.hass is not None:
            self._entity.async_write_ha_state()

    def fire(self, action: str, **data: Any) -> None:
        payload = {"action": action}
        payload.update(data)
        self.hass.bus.async_fire(f"{DOMAIN}_cmd", payload)

    def conf(self) -> dict[str, Any]:
        return {**self.entry.data, **self.entry.options}

    def track(self) -> dict[str, Any] | None:
        tracks = self.library.tracks
        if not tracks:
            return None
        self.index = self.index % len(tracks)
        return tracks[self.index]

    def sources(self) -> list[str]:
        out = ["browser"]
        own = self._own_id()
        for pid in self.conf().get(CONF_MEDIA_PLAYERS) or []:
            if pid and pid != own:
                out.append("sp:" + pid)
        cfg = self.conf()
        if cfg.get(CONF_ENABLE_XIAOAI) and (cfg.get(CONF_XIAOMI_HOME) or cfg.get(CONF_XIAOMI_MIOT)):
            out.append("xiaoai")
        return out

    def _own_id(self) -> str:
        return self._entity.entity_id if self._entity is not None else ""

    def target_ids(self) -> list[str]:
        cfg = self.conf()
        own = self._own_id()
        if self.source == "xiaoai":
            return [x for x in (cfg.get(CONF_XIAOMI_MIOT), cfg.get(CONF_XIAOMI_HOME)) if x and x != own]
        if self.source.startswith("sp:"):
            eid = self.source[3:]
            return [eid] if eid and eid != own else []
        return []

    async def play_url(self, track_id: str) -> str:
        t = self.library.get(track_id)
        ext = os.path.splitext((t or {}).get("path") or "")[1].lower()
        if ext not in AUDIO_EXT:
            ext = ".mp3"
        base = await _lan_base(self.hass)
        return f"{base}/api/ha_music_player/file/{self.library.session_key}/{track_id}/track{ext}"

    async def call_targets(self, service: str, extra: dict | None = None, *, play: bool = False) -> None:
        data = dict(extra or {})
        for eid in self.target_ids():
            try:
                await self.hass.services.async_call(
                    "media_player", service, {**data, "entity_id": eid}, blocking=True
                )
                if play:
                    return
            except Exception:
                pass

    async def play_index(self, index: int) -> None:
        tracks = self.library.tracks
        if not tracks:
            return
        self.index = index % len(tracks)
        t = self.track()
        self.active = True
        self.playing = True
        self.position = 0.0
        self.duration = float((t or {}).get("duration") or 0)
        self.position_updated = dt_util.utcnow()
        self.fire("play", index=self.index, track_id=(t or {}).get("id") or "")
        if self.source != "browser" and t:
            url = await self.play_url(t["id"])
            await self.call_targets(
                "play_media",
                {"media_content_id": url, "media_content_type": "music"},
                play=True,
            )
        self.notify()

    async def play(self) -> None:
        if self.active and not self.playing:
            self.playing = True
            self.position_updated = dt_util.utcnow()
            self.fire("resume")
            if self.source != "browser":
                await self.call_targets("media_play")
            self.notify()
            return
        await self.play_index(self.index)

    async def pause(self) -> None:
        self.playing = False
        self.position_updated = dt_util.utcnow()
        self.fire("pause")
        if self.source != "browser":
            await self.call_targets("media_pause")
        self.notify()

    async def stop(self) -> None:
        self.playing = False
        self.position = 0.0
        self.position_updated = dt_util.utcnow()
        self.fire("stop")
        if self.source != "browser":
            await self.call_targets("media_stop")
        self.notify()

    async def next(self) -> None:
        n = len(self.library.tracks)
        if not n:
            return
        nxt = random.randrange(n) if self.shuffle else self.index + 1
        await self.play_index(nxt)

    async def prev(self) -> None:
        n = len(self.library.tracks)
        if not n:
            return
        nxt = random.randrange(n) if self.shuffle else self.index - 1
        await self.play_index(nxt)

    async def seek(self, pos: float) -> None:
        self.position = max(0.0, pos)
        self.position_updated = dt_util.utcnow()
        self.fire("seek", pos=self.position)
        if self.source != "browser":
            await self.call_targets("media_seek", {"seek_position": self.position})
        self.notify()

    async def set_volume(self, volume: float) -> None:
        self.volume = min(1.0, max(0.0, volume))
        self.fire("volume", volume=self.volume)
        if self.source != "browser":
            await self.call_targets("volume_set", {"volume_level": self.volume})
        self.notify()

    async def set_shuffle(self, shuffle: bool) -> None:
        self.shuffle = shuffle
        self.fire("shuffle", shuffle=self.shuffle)
        self.notify()

    async def set_repeat(self, repeat: str) -> None:
        self.repeat = repeat
        self.fire("repeat", repeat=self.repeat)
        self.notify()

    async def set_source(self, source: str) -> None:
        self.source = source
        self.fire("source", source=self.source)
        if self.playing:
            await self.play()
        else:
            self.notify()

    def apply_frontend(self, data: dict[str, Any]) -> None:
        prev = (
            self.index,
            self.playing,
            float(self.position),
            int(self.duration or 0),
            round(self.volume, 2),
            self.shuffle,
            self.repeat,
            self.source,
        )
        tid = data.get("track_id")
        if tid:
            self.active = True
            for i, t in enumerate(self.library.tracks):
                if t["id"] == tid:
                    self.index = i
                    break
        elif "index" in data:
            self.index = int(data["index"])
        if "playing" in data:
            self.playing = bool(data["playing"])
        if "pos" in data:
            self.position = float(data["pos"] or 0)
            self.position_updated = dt_util.utcnow()
        if "duration" in data:
            self.duration = float(data["duration"] or 0)
        if "volume" in data:
            self.volume = float(data["volume"])
        if "shuffle" in data:
            self.shuffle = bool(data["shuffle"])
        if "repeat" in data:
            self.repeat = str(data["repeat"])
        if "output" in data:
            self.source = str(data["output"])
        same = (
            self.index == prev[0]
            and self.playing == prev[1]
            and int(self.duration or 0) == prev[3]
            and round(self.volume, 2) == prev[4]
            and self.shuffle == prev[5]
            and self.repeat == prev[6]
            and self.source == prev[7]
        )
        if same and abs(self.position - prev[2]) < 1.5:
            return
        self.notify()
