from __future__ import annotations

import hashlib
import logging
import os
import secrets
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import AUDIO_EXT, DOMAIN

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}_library"


def _track_id(path: str) -> str:
    return hashlib.md5(path.encode("utf-8")).hexdigest()[:16]


def _tag_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        value = value[0] if value else ""
    return str(value).strip()


def _read_tags(path: str) -> dict[str, Any]:
    title = os.path.splitext(os.path.basename(path))[0]
    artist = ""
    album = ""
    duration = 0
    has_cover = False
    has_lyric = False
    try:
        from mutagen import File

        audio = File(path, easy=True)
        if audio is not None:
            title = _tag_text(audio.get("title")) or title
            artist = _tag_text(audio.get("artist"))
            album = _tag_text(audio.get("album"))
            if audio.info and getattr(audio.info, "length", None):
                duration = int(audio.info.length)
        raw = File(path)
        if raw is not None:
            if getattr(raw, "pictures", None):
                has_cover = len(raw.pictures) > 0
            tags = getattr(raw, "tags", None)
            if tags:
                for key in tags:
                    k = str(key)
                    if k.startswith("APIC") or k == "covr" or k.startswith("----:com.apple.iTunes:covr"):
                        has_cover = True
                    if k.startswith("USLT") or k.startswith("\xa9lyr") or k == "LYRICS":
                        has_lyric = True
    except Exception:
        pass
    lrc = os.path.splitext(path)[0] + ".lrc"
    if os.path.isfile(lrc):
        has_lyric = True
    folder = os.path.basename(os.path.dirname(path))
    return {
        "id": _track_id(path),
        "source": "local",
        "title": title,
        "artist": artist,
        "album": album,
        "duration": duration,
        "folder": folder,
        "path": path,
        "has_cover": has_cover,
        "has_lyric": has_lyric,
    }


def _extract_cover(path: str) -> tuple[bytes | None, str]:
    try:
        from mutagen import File

        audio = File(path)
        if audio is None:
            return None, "image/jpeg"
        if getattr(audio, "pictures", None):
            pic = audio.pictures[0]
            return pic.data, pic.mime or "image/jpeg"
        tags = getattr(audio, "tags", None)
        if not tags:
            return None, "image/jpeg"
        for key in tags:
            k = str(key)
            item = tags[key]
            if k.startswith("APIC"):
                return item.data, getattr(item, "mime", None) or "image/jpeg"
            if k == "covr":
                data = item[0] if isinstance(item, list) else item
                return bytes(data), "image/jpeg"
    except Exception:
        pass
    return None, "image/jpeg"


def _extract_lyric(path: str) -> str:
    lrc = os.path.splitext(path)[0] + ".lrc"
    if os.path.isfile(lrc):
        try:
            with open(lrc, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        except Exception:
            pass
    try:
        from mutagen import File
        from mutagen.id3 import USLT

        audio = File(path)
        if audio is None:
            return ""
        tags = getattr(audio, "tags", None)
        if not tags:
            return ""
        for key in tags:
            item = tags[key]
            if isinstance(item, USLT):
                return str(item.text or "")
            k = str(key)
            if k.startswith("USLT") or k.startswith("\xa9lyr") or k == "LYRICS":
                text = getattr(item, "text", None)
                if text:
                    return str(text)
                if isinstance(item, list):
                    return str(item[0])
                return str(item)
    except Exception:
        pass
    return ""


class MusicLibrary:
    def __init__(self, hass: HomeAssistant, music_path: str) -> None:
        self.hass = hass
        self.music_path = music_path
        self.session_key = secrets.token_urlsafe(24)
        self.tracks: list[dict[str, Any]] = []
        self._by_id: dict[str, dict[str, Any]] = {}
        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY)

    def get(self, track_id: str) -> dict[str, Any] | None:
        return self._by_id.get(track_id)

    def public_tracks(self) -> list[dict[str, Any]]:
        out = []
        for t in self.tracks:
            item = {k: v for k, v in t.items() if k != "path"}
            out.append(item)
        return out

    async def load(self) -> None:
        data = await self._store.async_load()
        if data and data.get("path") == self.music_path and data.get("tracks"):
            self.tracks = data["tracks"]
            self._by_id = {t["id"]: t for t in self.tracks}
            return
        await self.async_scan()

    async def async_scan(self) -> int:
        path = self.music_path
        tracks = await self.hass.async_add_executor_job(self._scan_sync, path)
        self.tracks = tracks
        self._by_id = {t["id"]: t for t in tracks}
        await self._store.async_save({"path": path, "tracks": tracks})
        _LOGGER.info("scanned %s tracks from %s", len(tracks), path)
        return len(tracks)

    def _scan_sync(self, root: str) -> list[dict[str, Any]]:
        tracks: list[dict[str, Any]] = []
        if not os.path.isdir(root):
            return tracks
        for dirpath, _, files in os.walk(root):
            files.sort()
            for name in files:
                ext = os.path.splitext(name)[1].lower()
                if ext not in AUDIO_EXT:
                    continue
                full = os.path.join(dirpath, name)
                try:
                    tracks.append(_read_tags(full))
                except Exception as err:
                    _LOGGER.debug("skip %s: %s", full, err)
        tracks.sort(key=lambda t: (t.get("folder") or "", t.get("artist") or "", t.get("title") or ""))
        return tracks

    def cover(self, track_id: str) -> tuple[bytes | None, str]:
        track = self.get(track_id)
        if not track:
            return None, "image/jpeg"
        return _extract_cover(track["path"])

    def lyric(self, track_id: str) -> str:
        track = self.get(track_id)
        if not track:
            return ""
        return _extract_lyric(track["path"])
