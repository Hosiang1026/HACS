from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_manifest_and_quality_scale() -> None:
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["config_flow"] is True
    assert manifest["codeowners"]
    assert manifest["integration_type"] == "hub"

    scale = (ROOT / "quality_scale.yaml").read_text(encoding="utf-8")
    assert "reauthentication-flow: done" in scale
    assert "test-coverage: done" in scale


def test_reauth_and_runtime_data_in_source() -> None:
    config_flow = (ROOT / "config_flow.py").read_text(encoding="utf-8")
    assert "async_step_reauth" in config_flow
    assert "async_update_reload_and_abort" in config_flow

    init_py = (ROOT / "__init__.py").read_text(encoding="utf-8")
    assert "entry.runtime_data = account" in init_py
    assert "await account.async_shutdown()" in init_py
    assert "await self._coordinator.async_shutdown()" in (
        ROOT / "account.py"
    ).read_text(encoding="utf-8")


def test_cloud_reachable_and_parallel_updates() -> None:
    coordinator = (ROOT / "DataUpdateCoordinator.py").read_text(encoding="utf-8")
    assert "cloud_reachable" in coordinator
    assert "_return_devices" in coordinator
    assert "async def async_shutdown" in coordinator

    for name in ("sensor.py", "button.py", "device_tracker.py", "text.py"):
        assert "PARALLEL_UPDATES = 1" in (ROOT / name).read_text(encoding="utf-8")


def test_entity_unavailable_and_keep_alive() -> None:
    account = (ROOT / "account.py").read_text(encoding="utf-8")
    assert "cloud_reachable" in account
    assert "_ensure_operational" in account
    assert "async def async_keep_alive" in account
    assert "self._ensure_operational()" in account

    entity = (ROOT / "entity.py").read_text(encoding="utf-8")
    assert "def available" in entity


def test_action_exceptions_and_translations() -> None:
    account = (ROOT / "account.py").read_text(encoding="utf-8")
    assert "ServiceValidationError" in account
    assert "update_failed" in account
    assert "connection_failed" in account

    en = json.loads((ROOT / "translations/en.json").read_text(encoding="utf-8"))
    zh = json.loads((ROOT / "translations/zh-Hans.json").read_text(encoding="utf-8"))
    for key in (
        "update_failed",
        "connection_failed",
        "service_failed",
        "authentication_required",
    ):
        assert key in en["exceptions"]
        assert key in zh["exceptions"]


def test_translation_key_parity() -> None:
    en = json.loads((ROOT / "translations/en.json").read_text(encoding="utf-8"))
    zh = json.loads((ROOT / "translations/zh-Hans.json").read_text(encoding="utf-8"))

    def flat_keys(obj, prefix=""):
        keys = set()
        if isinstance(obj, dict):
            for name, value in obj.items():
                path = f"{prefix}.{name}" if prefix else name
                keys.add(path)
                keys |= flat_keys(value, path)
        return keys

    assert flat_keys(en) == flat_keys(zh)


def test_readme_silver_docs() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "故障排查" in readme
    assert "卸载" in readme
    assert re.search(r"仓库 URL", readme)
