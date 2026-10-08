from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from homeassistant.config_entries import ConfigEntry


@dataclass
class HonorCloudRuntimeData:
    status_coordinator: Any
    sync_coordinator: Any
    timeout_count: int = 0
    last_timeout_traceback: bool = False
    fast_retry_count: int = 0
    fast_retry_task: Callable[..., Any] | None = None
    platforms_setup: bool = False
    lost_fields: dict[str, dict[str, str]] = field(default_factory=dict)


def get_runtime(entry: ConfigEntry) -> HonorCloudRuntimeData:
    runtime = entry.runtime_data
    if runtime is None:
        raise RuntimeError("Honor Cloud integration is not initialized")
    return runtime
