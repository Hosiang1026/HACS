from __future__ import annotations

from homeassistant.helpers.entity import Entity

from .account import XiaomiAccount


class XiaomiAccountEntity(Entity):
    _account: XiaomiAccount

    @property
    def available(self) -> bool:
        return self._account.available
