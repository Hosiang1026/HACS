from __future__ import annotations

import os

from aiohttp import web
from homeassistant.components.http import HomeAssistantView

from .const import (
    CONF_ENABLE_XIAOAI,
    CONF_MEDIA_PLAYERS,
    CONF_XIAOMI_HOME,
    CONF_XIAOMI_MIOT,
    DOMAIN,
)
from .library import MusicLibrary
from .player import RuntimePlayer


def _runtime(hass):
    data = hass.data.get(DOMAIN) or {}
    return data.get("runtime") or {}


def _library(hass) -> MusicLibrary | None:
    return _runtime(hass).get("library")


def _player(hass) -> RuntimePlayer | None:
    return _runtime(hass).get("player")


def _entry_conf(hass):
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        return {}
    entry = entries[0]
    return {**entry.data, **entry.options}


def _allowed(request, library: MusicLibrary) -> bool:
    key = request.query.get("key")
    if key and key == library.session_key:
        return True
    return request.get("hass_user") is not None


def _safe_track(library: MusicLibrary | None, track: dict | None) -> bool:
    if not library or not track or not track.get("path"):
        return False
    try:
        root = os.path.realpath(library.music_path)
        path = os.path.realpath(track["path"])
        return os.path.commonpath([root, path]) == root and os.path.isfile(path)
    except (OSError, ValueError):
        return False


class LibraryView(HomeAssistantView):
    url = "/api/ha_music_player/library"
    name = "api:ha_music_player:library"
    requires_auth = True

    async def get(self, request):
        lib = _library(request.app["hass"])
        if not lib:
            return web.Response(status=503)
        return self.json({"session_key": lib.session_key, "tracks": lib.public_tracks()})


class ConfigView(HomeAssistantView):
    url = "/api/ha_music_player/config"
    name = "api:ha_music_player:config"
    requires_auth = True

    async def get(self, request):
        hass = request.app["hass"]
        conf = _entry_conf(hass)
        players = conf.get(CONF_MEDIA_PLAYERS) or []
        if isinstance(players, str):
            players = [players] if players else []
        return self.json(
            {
                "enable_xiaoai": bool(conf.get(CONF_ENABLE_XIAOAI)),
                "xiaomi_home": conf.get(CONF_XIAOMI_HOME) or "",
                "xiaomi_miot": conf.get(CONF_XIAOMI_MIOT) or "",
                "media_players": [p for p in players if p],
            }
        )


class StateView(HomeAssistantView):
    url = "/api/ha_music_player/state"
    name = "api:ha_music_player:state"
    requires_auth = True

    async def get(self, request):
        player = _player(request.app["hass"])
        if not player:
            return web.Response(status=503)
        t = player.track()
        return self.json(
            {
                "index": player.index,
                "track_id": (t or {}).get("id") or "",
                "playing": player.playing,
                "pos": player.position,
                "duration": player.duration,
                "volume": player.volume,
                "shuffle": player.shuffle,
                "repeat": player.repeat,
                "output": player.source,
            }
        )

    async def post(self, request):
        player = _player(request.app["hass"])
        if not player:
            return web.Response(status=503)
        player.apply_frontend(await request.json())
        return self.json({"ok": True})


class ScanView(HomeAssistantView):
    url = "/api/ha_music_player/scan"
    name = "api:ha_music_player:scan"
    requires_auth = True

    async def post(self, request):
        lib = _library(request.app["hass"])
        if not lib:
            return web.Response(status=503)
        count = await lib.async_scan()
        return self.json({"count": count, "session_key": lib.session_key})


class FileView(HomeAssistantView):
    url = "/api/ha_music_player/file/{track_id}"
    extra_urls = ["/api/ha_music_player/file/{key}/{track_id}/{filename}"]
    name = "api:ha_music_player:file"
    requires_auth = False

    async def get(self, request, track_id, key=None, filename=None):
        lib = _library(request.app["hass"])
        if not lib:
            return web.Response(status=503)
        tid = track_id
        auth = key or request.query.get("key")
        if key is None and "." in track_id:
            parts = track_id.split(".")
            if len(parts) >= 3:
                auth, tid = parts[0], parts[1]
            elif len(parts) == 2:
                tid = parts[0]
        if auth:
            if auth != lib.session_key:
                return web.Response(status=401)
        elif not _allowed(request, lib):
            return web.Response(status=401)
        track = lib.get(tid)
        if not _safe_track(lib, track):
            return web.Response(status=404)
        return web.FileResponse(track["path"], headers={"Cache-Control": "private, max-age=3600"})

    async def head(self, request, track_id, key=None, filename=None):
        return await self.get(request, track_id, key=key, filename=filename)


class CoverView(HomeAssistantView):
    url = "/api/ha_music_player/cover/{track_id}"
    name = "api:ha_music_player:cover"
    requires_auth = False

    async def get(self, request, track_id):
        lib = _library(request.app["hass"])
        if not lib or not _allowed(request, lib):
            return web.Response(status=401)
        if not _safe_track(lib, lib.get(track_id)):
            return web.Response(status=404)
        data, mime = await request.app["hass"].async_add_executor_job(lib.cover, track_id)
        if not data:
            return web.Response(status=404)
        return web.Response(body=data, content_type=mime, headers={"Cache-Control": "private, max-age=86400"})


class LyricView(HomeAssistantView):
    url = "/api/ha_music_player/lyric/{track_id}"
    name = "api:ha_music_player:lyric"
    requires_auth = False

    async def get(self, request, track_id):
        lib = _library(request.app["hass"])
        if not lib or not _allowed(request, lib):
            return web.Response(status=401)
        if not _safe_track(lib, lib.get(track_id)):
            return web.Response(status=404)
        text = await request.app["hass"].async_add_executor_job(lib.lyric, track_id)
        return self.json({"lyric": text or ""})


class PlayUrlView(HomeAssistantView):
    url = "/api/ha_music_player/play_url/{track_id}"
    name = "api:ha_music_player:play_url"
    requires_auth = True

    async def get(self, request, track_id):
        hass = request.app["hass"]
        lib = _library(hass)
        player = _player(hass)
        track = lib.get(track_id) if lib else None
        if not _safe_track(lib, track):
            return web.Response(status=404)
        if not player:
            return web.Response(status=503)
        url = await player.play_url(track_id)
        return self.json({"url": url, "key": lib.session_key})
