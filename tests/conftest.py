"""
tests/conftest.py
=================
Fixtures partagées pour tous les tests android-mcp (nouvelle architecture 7 outils).
"""

import base64
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ─── Pytest asyncio ──────────────────────────────────────────────────────────

pytest_plugins = ("pytest_asyncio",)

# ─── Données de test ─────────────────────────────────────────────────────────

SAMPLE_UI_XML = """
<node index="0" text="Play" content-desc="Play button" bounds="[0,100][1080,200]"
      resource-id="com.example:id/play">
  <node index="0" text="Start" content-desc="Start game" bounds="[100,300][500,600]"
        resource-id="com.example:id/start" />
  <node index="1" text="Settings" bounds="[600,300][980,600]"
        resource-id="com.example:id/settings" />
</node>
"""

# PNG 1×1 pixel valide encodé en base64
FAKE_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
    "+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)
FAKE_PNG_BYTES = base64.b64decode(FAKE_PNG_B64)

DEVICE_SERIAL = "adb-TEST-DEVICE-ZXkkLe._adb-tls-connect._tcp"

DEVICE_INFO = {
    "serial": DEVICE_SERIAL,
    "transport": "wifi",
    "model": "Samsung SM-G996U1",
    "android_version": "Android 15 (SDK 35)",
    "resolution": "1080x2400",
    "density": "450",
    "ready": True,
}


# ─── Mock Backend ─────────────────────────────────────────────────────────────


def make_mock_backend() -> MagicMock:
    """Crée un mock de AdbBackend/CompanionBackend qui réussit toutes les opérations."""
    b = MagicMock()

    # Screen
    b.screenshot       = AsyncMock(return_value=FAKE_PNG_BYTES)
    b.screenshot_region= AsyncMock(return_value=FAKE_PNG_BYTES)
    b.get_screen_size  = AsyncMock(return_value={"width": 1080, "height": 2400})
    b.is_screen_on     = AsyncMock(return_value=True)
    b.wake_screen      = AsyncMock(return_value=None)
    b.start_stream     = AsyncMock(return_value={"success": True, "url": "http://localhost:8090"})
    b.stop_stream      = AsyncMock(return_value=None)
    b.get_live_frame   = AsyncMock(return_value={"success": True, "data": FAKE_PNG_B64, "mime": "image/png"})
    b.ocr_screen       = AsyncMock(return_value="Hello World")
    b.find_by_image    = AsyncMock(return_value={"found": True, "x": 100, "y": 200, "w": 50, "h": 50, "score": 0.95})

    # Touch
    b.tap              = AsyncMock(return_value=None)
    b.double_tap       = AsyncMock(return_value=None)
    b.long_press       = AsyncMock(return_value=None)
    b.swipe            = AsyncMock(return_value=None)
    b.drag_and_drop    = AsyncMock(return_value=None)
    b.pinch_zoom       = AsyncMock(return_value=None)
    b.multi_touch      = AsyncMock(return_value=None)

    # Keyboard
    b.input_text       = AsyncMock(return_value=None)
    b.clear_field      = AsyncMock(return_value=None)
    b.type_and_submit  = AsyncMock(return_value=None)
    b.press_key        = AsyncMock(return_value=None)
    b.key_combo        = AsyncMock(return_value=None)

    # UI
    b.get_ui_hierarchy = AsyncMock(return_value=SAMPLE_UI_XML)
    b.find_and_tap     = AsyncMock(return_value=True)
    b.wait_for_element = AsyncMock(return_value=True)
    b.scroll_to_element= AsyncMock(return_value=True)
    b.assert_visible   = AsyncMock(return_value=True)

    # Apps
    b.launch_app       = AsyncMock(return_value=None)
    b.close_app        = AsyncMock(return_value=None)
    b.list_apps        = AsyncMock(return_value=[{"name": "Chrome", "package": "com.android.chrome"}])
    b.install_app      = AsyncMock(return_value={"success": True})
    b.uninstall_app    = AsyncMock(return_value={"success": True})
    b.get_current_app  = AsyncMock(return_value="com.android.launcher3")
    b.open_url         = AsyncMock(return_value=None)
    b.send_intent      = AsyncMock(return_value=None)
    b.open_settings    = AsyncMock(return_value=None)

    # Files
    b.push_file        = AsyncMock(return_value={"success": True})
    b.push_file_b64    = AsyncMock(return_value=None)
    b.pull_file        = AsyncMock(return_value={"success": True})
    b.pull_file_b64    = AsyncMock(return_value=FAKE_PNG_B64)
    b.list_files       = AsyncMock(return_value=[{"name": "Download", "type": "dir"}])

    # System
    b.shell_exec       = AsyncMock(return_value="output shell")
    b.get_logs         = AsyncMock(return_value="logcat line 1\nlogcat line 2")
    b.get_battery      = AsyncMock(return_value={"level": 85, "charging": True})
    b.get_clipboard    = AsyncMock(return_value="clipboard text")
    b.set_clipboard    = AsyncMock(return_value=None)
    b.set_volume       = AsyncMock(return_value=None)
    b.set_rotation     = AsyncMock(return_value=None)
    b.toggle_wifi      = AsyncMock(return_value=None)
    b.toggle_bluetooth = AsyncMock(return_value=None)
    b.enable_mobile_data=AsyncMock(return_value=None)
    b.read_notifications=AsyncMock(return_value=[{"title": "Test", "text": "notif"}])
    b.mock_gps         = AsyncMock(return_value=None)
    b.get_sensor_data  = AsyncMock(return_value={"light": 250})
    b.get_wifi_list    = AsyncMock(return_value=[{"ssid": "MyNetwork", "level": -55}])
    b.connect_wifi     = AsyncMock(return_value={"success": True})
    b.get_contacts     = AsyncMock(return_value=[{"name": "Alice", "phone": "+33612345678"}])
    b.send_sms         = AsyncMock(return_value={"sent": False, "note": "confirmation required"})

    # Setup
    b.auto_setup       = AsyncMock(return_value=[{"step": "atx", "ok": True}])

    return b


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_backend(mocker) -> MagicMock:
    """Mock le backend ADB pour tous les tests — aucun device requis."""
    b = make_mock_backend()
    mocker.patch("server._b", return_value=b)
    return b


@pytest.fixture
def mock_dm(mocker) -> MagicMock:
    """Mock le device_manager."""
    dm = MagicMock()
    dm.list_devices.return_value = [DEVICE_INFO]
    dm.get_device_info.return_value = DEVICE_INFO
    dm.get_selected_serial.return_value = DEVICE_SERIAL
    dm.select_device.return_value = {"selected": DEVICE_SERIAL}
    dm.connect_wifi_adb.return_value = {"success": True}
    dm.disconnect_wifi_adb.return_value = {"success": True}
    mocker.patch("server._dm", dm)
    return dm


@pytest.fixture
def sample_ui_xml() -> str:
    return SAMPLE_UI_XML


@pytest.fixture
def fake_png_bytes() -> bytes:
    return FAKE_PNG_BYTES


@pytest.fixture
def device_serial() -> str:
    return DEVICE_SERIAL
