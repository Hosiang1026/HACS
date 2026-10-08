import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

TESTS = Path(__file__).resolve().parent
INTEGRATION = TESTS.parent
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

if "honor_cloud" not in sys.modules:
    stub = types.ModuleType("honor_cloud")
    stub.__file__ = str(INTEGRATION / "__init__.py")
    sys.modules["honor_cloud"] = stub


def _pkg(name: str) -> types.ModuleType:
    mod = types.ModuleType(name)
    mod.__path__ = []
    return mod


ha = _pkg("homeassistant")
ha_const = _pkg("homeassistant.const")


class _Platform:
    DEVICE_TRACKER = "device_tracker"
    SENSOR = "sensor"
    BUTTON = "button"
    TEXT = "text"


ha_const.Platform = _Platform
ha.config_entries = MagicMock()
ha.core = MagicMock()
ha.exceptions = MagicMock()
ha.components = _pkg("homeassistant.components")
ha.components.persistent_notification = MagicMock()
ha.helpers = _pkg("homeassistant.helpers")
ha.helpers.update_coordinator = MagicMock()
ha.helpers.update_coordinator.UpdateFailed = Exception
ha.helpers.aiohttp_client = MagicMock()
ha.helpers.device_registry = MagicMock()
ha.helpers.entity_platform = MagicMock()
ha.helpers.event = MagicMock()
ha.helpers.restore_state = MagicMock()
ha.util = _pkg("homeassistant.util")
ha.util.dt = MagicMock()
ha.data_entry_flow = MagicMock()

sys.modules["homeassistant"] = ha
sys.modules["homeassistant.const"] = ha_const
sys.modules["homeassistant.config_entries"] = ha.config_entries
sys.modules["homeassistant.core"] = ha.core
sys.modules["homeassistant.exceptions"] = ha.exceptions
sys.modules["homeassistant.components"] = ha.components
sys.modules["homeassistant.components.persistent_notification"] = ha.components.persistent_notification
sys.modules["homeassistant.helpers"] = ha.helpers
sys.modules["homeassistant.helpers.update_coordinator"] = ha.helpers.update_coordinator
sys.modules["homeassistant.helpers.aiohttp_client"] = ha.helpers.aiohttp_client
sys.modules["homeassistant.helpers.device_registry"] = ha.helpers.device_registry
sys.modules["homeassistant.helpers.entity_platform"] = ha.helpers.entity_platform
sys.modules["homeassistant.helpers.event"] = ha.helpers.event
sys.modules["homeassistant.helpers.restore_state"] = ha.helpers.restore_state
sys.modules["homeassistant.util"] = ha.util
sys.modules["homeassistant.util.dt"] = ha.util.dt
sys.modules["homeassistant.data_entry_flow"] = ha.data_entry_flow
