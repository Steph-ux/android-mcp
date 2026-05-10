"""
tests/test_integration.py
=========================
Tests d'intégration — nécessitent un device ADB connecté (USB ou WiFi).
Skippés automatiquement si aucun device n'est disponible.
"""

import asyncio
import json
import pytest
from pathlib import Path

ROOT = Path(__file__).parent.parent

# ─── Skip si pas de device ───────────────────────────────────────────────────

def _first_device() -> str | None:
    import sys
    sys.path.insert(0, str(ROOT))
    try:
        from device_manager import get_manager
        devices = [d for d in get_manager().list_devices() if d.get("ready")]
        return devices[0]["serial"] if devices else None
    except Exception:
        return None


DEVICE = _first_device()
skip_no_device = pytest.mark.skipif(DEVICE is None, reason="Aucun device ADB connecté")


@pytest.fixture(scope="module", autouse=True)
def select_device():
    if DEVICE:
        import sys
        sys.path.insert(0, str(ROOT))
        from device_manager import get_manager
        get_manager().select_device(DEVICE)


# ─── Tests d'intégration ─────────────────────────────────────────────────────


@skip_no_device
class TestDeviceIntegration:

    @pytest.mark.asyncio
    async def test_device_info_has_model(self):
        from server import android_device
        r = json.loads(await android_device("info", device_id=DEVICE))
        assert r["success"]
        assert "model" in r["data"]

    @pytest.mark.asyncio
    async def test_device_status_ready(self):
        from server import android_device
        r = json.loads(await android_device("status", device_id=DEVICE))
        assert r["connected"] is True


@skip_no_device
class TestScreenIntegration:

    @pytest.mark.asyncio
    async def test_screenshot_is_png(self):
        from server import android_screen
        from mcp.types import ImageContent
        result = await android_screen("screenshot", device_id=DEVICE)
        assert isinstance(result, list)
        assert isinstance(result[0], ImageContent)
        import base64
        raw = base64.b64decode(result[0].data)
        assert raw[:4] == b"\x89PNG"

    @pytest.mark.asyncio
    async def test_size_returns_resolution(self):
        from server import android_screen
        r = json.loads(await android_screen("size", device_id=DEVICE))
        assert r["success"]
        data = r["data"]
        assert data.get("width", 0) > 0
        assert data.get("height", 0) > 0

    @pytest.mark.asyncio
    async def test_is_on_returns_bool(self):
        from server import android_screen
        r = json.loads(await android_screen("is_on", device_id=DEVICE))
        assert isinstance(r["data"], bool)


@skip_no_device
class TestInteractIntegration:

    @pytest.mark.asyncio
    async def test_hierarchy_returns_xml(self):
        from server import android_interact
        r = json.loads(await android_interact("hierarchy", device_id=DEVICE))
        assert r["success"]
        assert "<node" in r["data"] or len(r["data"]) > 0

    @pytest.mark.asyncio
    async def test_key_home_succeeds(self):
        from server import android_interact
        r = json.loads(await android_interact("key", {"key": "HOME"}, DEVICE))
        assert r["success"]


@skip_no_device
class TestSystemIntegration:

    @pytest.mark.asyncio
    async def test_battery_level_range(self):
        from server import android_system
        r = json.loads(await android_system("battery", device_id=DEVICE))
        assert r["success"]
        level = r["data"]["level"]
        assert 0 <= level <= 100

    @pytest.mark.asyncio
    async def test_shell_echo(self):
        from server import android_system
        r = json.loads(await android_system("shell", {"command": "echo test_mcp"}, DEVICE))
        assert r["success"]
        assert "test_mcp" in r["data"]


@skip_no_device
class TestAppIntegration:

    @pytest.mark.asyncio
    async def test_current_app_nonempty(self):
        from server import android_app
        r = json.loads(await android_app("current", device_id=DEVICE))
        assert r["success"]
        assert len(r["data"]) > 0

    @pytest.mark.asyncio
    async def test_list_apps_nonempty(self):
        from server import android_app
        r = json.loads(await android_app("list", {"include_system": False}, DEVICE))
        assert r["success"]
        assert r["count"] > 0


@skip_no_device
class TestFilesIntegration:

    @pytest.mark.asyncio
    async def test_list_sdcard(self):
        from server import android_files
        r = json.loads(await android_files("list", {"directory": "/sdcard"}, DEVICE))
        assert r["success"]
        assert r["count"] > 0

    @pytest.mark.asyncio
    async def test_push_pull_roundtrip(self, tmp_path):
        from server import android_files
        f = tmp_path / "mcp_test.txt"
        f.write_text("android-mcp integration test", encoding="utf-8")

        push = json.loads(await android_files("push", {
            "local_path": str(f),
            "remote_path": "/sdcard/Download/__mcp_intg_test.txt",
        }, DEVICE))
        assert push["success"]

        r = json.loads(await android_files("pull_b64", {
            "remote_path": "/sdcard/Download/__mcp_intg_test.txt",
        }, DEVICE))
        assert r["success"]
        import base64
        content = base64.b64decode(r["data"]).decode("utf-8")
        assert "android-mcp integration test" in content
