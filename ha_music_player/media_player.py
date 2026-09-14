from __future__ import annotations

from homeassistant.components.media_player import (
    BrowseMedia,
    MediaClass,
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
    RepeatMode,
)
from homeassistant.components.media_player.errors import BrowseError
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, MANUFACTURER, VERSION
from .player import RuntimePlayer

FEATURES = (
    MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.PAUSE
    | MediaPlayerEntityFeature.STOP
    | MediaPlayerEntityFeature.NEXT_TRACK
    | MediaPlayerEntityFeature.PREVIOUS_TRACK
    | MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.SEEK
    | MediaPlayerEntityFeature.PLAY_MEDIA
    | MediaPlayerEntityFeature.BROWSE_MEDIA
    | MediaPlayerEntityFeature.SELECT_SOURCE
    | MediaPlayerEntityFeature.SHUFFLE_SET
    | MediaPlayerEntityFeature.REPEAT_SET
)

REPEAT_TO_HA = {"one": RepeatMode.ONE, "all": RepeatMode.ALL, "off": RepeatMode.OFF}
HA_TO_REPEAT = {RepeatMode.ONE: "one", RepeatMode.ALL: "all", RepeatMode.OFF: "off"}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    player: RuntimePlayer = hass.data[DOMAIN]["runtime"]["player"]
    entity = HaMusicPlayerEntity(entry, player)
    player.attach(entity)
    async_add_entities([entity])


class HaMusicPlayerEntity(MediaPlayerEntity):
    _attr_supported_features = FEATURES
    _attr_device_class = MediaPlayerDeviceClass.SPEAKER
    _attr_has_entity_name = False
    _attr_name = "音乐播放器"

    def __init__(self, entry: ConfigEntry, player: RuntimePlayer) -> None:
        self._entry = entry
        self._player = player
        self._attr_unique_id = f"{entry.entry_id}_player"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            manufacturer=MANUFACTURER,
            name="音乐播放器",
            sw_version=VERSION,
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def state(self) -> MediaPlayerState:
        if self._player.playing:
            return MediaPlayerState.PLAYING
        if self._player.active:
            return MediaPlayerState.PAUSED
        return MediaPlayerState.IDLE

    @property
    def media_content_type(self) -> MediaType:
        return MediaType.MUSIC

    @property
    def media_title(self) -> str | None:
        t = self._player.track()
        return t["title"] if t else None

    @property
    def media_artist(self) -> str | None:
        t = self._player.track()
        return (t.get("artist") or None) if t else None

    @property
    def media_album_name(self) -> str | None:
        t = self._player.track()
        return (t.get("album") or None) if t else None

    @property
    def media_duration(self) -> int | None:
        t = self._player.track()
        dur = self._player.duration or (t.get("duration") if t else 0) or 0
        return int(dur) if dur else None

    @property
    def media_position(self) -> int | None:
        return int(self._player.position)

    @property
    def media_position_updated_at(self):
        return self._player.position_updated

    @property
    def volume_level(self) -> float:
        return self._player.volume

    @property
    def shuffle(self) -> bool:
        return self._player.shuffle

    @property
    def repeat(self) -> RepeatMode:
        return REPEAT_TO_HA.get(self._player.repeat, RepeatMode.OFF)

    @property
    def source(self) -> str | None:
        return self._player.source

    @property
    def source_list(self) -> list[str]:
        return self._player.sources()

    async def async_get_media_image(self) -> tuple[bytes | None, str | None]:
        t = self._player.track()
        if not t or not t.get("has_cover"):
            return None, None
        data, mime = await self.hass.async_add_executor_job(self._player.library.cover, t["id"])
        return data, mime

    async def async_media_play(self) -> None:
        await self._player.play()

    async def async_media_pause(self) -> None:
        await self._player.pause()

    async def async_media_stop(self) -> None:
        await self._player.stop()

    async def async_media_next_track(self) -> None:
        await self._player.next()

    async def async_media_previous_track(self) -> None:
        await self._player.prev()

    async def async_media_seek(self, position: float) -> None:
        await self._player.seek(position)

    async def async_set_volume_level(self, volume: float) -> None:
        await self._player.set_volume(volume)

    async def async_set_shuffle(self, shuffle: bool) -> None:
        await self._player.set_shuffle(shuffle)

    async def async_set_repeat(self, repeat: RepeatMode) -> None:
        await self._player.set_repeat(HA_TO_REPEAT.get(repeat, "off"))

    async def async_select_source(self, source: str) -> None:
        await self._player.set_source(source)

    async def async_play_media(self, media_type: str, media_id: str, **kwargs) -> None:
        if media_id.startswith("folder:"):
            return
        for i, t in enumerate(self._player.library.tracks):
            if t["id"] == media_id:
                await self._player.play_index(i)
                return

    async def async_browse_media(self, media_content_type: str | None = None, media_content_id: str | None = None) -> BrowseMedia:
        lib = self._player.library
        tracks = lib.public_tracks()
        if not media_content_id or media_content_id == "root":
            seen: list[str] = []
            children = []
            for t in tracks:
                folder = t.get("folder") or "Music"
                if folder in seen:
                    continue
                seen.append(folder)
                children.append(
                    BrowseMedia(
                        title=folder,
                        media_class=MediaClass.DIRECTORY,
                        media_content_id="folder:" + folder,
                        media_content_type="directory",
                        can_play=False,
                        can_expand=True,
                    )
                )
            return BrowseMedia(
                title="音乐播放器",
                media_class=MediaClass.DIRECTORY,
                media_content_id="root",
                media_content_type="directory",
                can_play=False,
                can_expand=True,
                children=children,
            )
        if media_content_id.startswith("folder:"):
            folder = media_content_id[7:]
            children = []
            for t in tracks:
                if (t.get("folder") or "Music") != folder:
                    continue
                thumb = None
                if t.get("has_cover"):
                    thumb = f"/api/ha_music_player/cover/{t['id']}?key={lib.session_key}"
                children.append(
                    BrowseMedia(
                        title=t["title"],
                        media_class=MediaClass.TRACK,
                        media_content_id=t["id"],
                        media_content_type=MediaType.MUSIC,
                        can_play=True,
                        can_expand=False,
                        thumbnail=thumb,
                    )
                )
            return BrowseMedia(
                title=folder,
                media_class=MediaClass.DIRECTORY,
                media_content_id=media_content_id,
                media_content_type="directory",
                can_play=False,
                can_expand=True,
                children=children,
            )
        raise BrowseError("Unknown media")
