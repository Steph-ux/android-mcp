"""
tests/test_server_unit.py
=========================
Tests unitaires pour server.py — 7 outils catégoriels (nouvelle API).
Aucun device requis : tout est mocké via conftest.mock_backend.
"""

import json
import pytest
from mcp.types import ImageContent, TextContent


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def ok(raw) -> dict:
    d = json.loads(raw)
    assert d.get("success") is True, f"Attendu success=True, reçu : {d}"
    return d


def err(raw) -> dict:
    d = json.loads(raw)
    assert d.get("success") is False, f"Attendu success=False, reçu : {d}"
    return d


def is_image(raw) -> bool:
    return isinstance(raw, list) and any(isinstance(r, ImageContent) for r in raw)


# ══════════════════════════════════════════════════════════════════════════════
# OUTIL 1 — android_device
# ══════════════════════════════════════════════════════════════════════════════

class TestAndroidDevice:

    @pytest.mark.asyncio
    async def test_list(self, mock_backend, mock_dm):
        from server import android_device
        r = ok(await android_device("list"))
        assert "devices" in r

    @pytest.mark.asyncio
    async def test_select(self, mock_backend, mock_dm):
        from server import android_device
        r = ok(await android_device("select", {"serial": "emulator-5554"}))
        assert "selected" in r

    @pytest.mark.asyncio
    async def test_select_missing_serial(self, mock_backend, mock_dm):
        from server import android_device
        err(await android_device("select", {}))

    @pytest.mark.asyncio
    async def test_info(self, mock_backend, mock_dm):
        from server import android_device
        r = ok(await android_device("info"))
        assert "data" in r

    @pytest.mark.asyncio
    async def test_status(self, mock_backend, mock_dm):
        from server import android_device
        r = ok(await android_device("status"))
        assert "connected" in r

    @pytest.mark.asyncio
    async def test_setup(self, mock_backend, mock_dm):
        from server import android_device
        r = ok(await android_device("setup"))
        assert "steps" in r

    @pytest.mark.asyncio
    async def test_connect(self, mock_backend, mock_dm):
        from server import android_device
        r = ok(await android_device("connect", {"host": "192.168.1.10", "port": 5555}))

    @pytest.mark.asyncio
    async def test_connect_missing_host(self, mock_backend, mock_dm):
        from server import android_device
        err(await android_device("connect", {}))

    @pytest.mark.asyncio
    async def test_unknown_action(self, mock_backend, mock_dm):
        from server import android_device
        d = err(await android_device("inexistant"))
        assert "Action inconnue" in d["error"]


# ══════════════════════════════════════════════════════════════════════════════
# OUTIL 2 — android_screen
# ══════════════════════════════════════════════════════════════════════════════

class TestAndroidScreen:

    @pytest.mark.asyncio
    async def test_screenshot_returns_image(self, mock_backend):
        from server import android_screen
        result = await android_screen("screenshot")
        assert is_image(result), "screenshot doit retourner une ImageContent"

    @pytest.mark.asyncio
    async def test_region_returns_image(self, mock_backend):
        from server import android_screen
        result = await android_screen("region", {"x": 0, "y": 0, "width": 200, "height": 200})
        assert is_image(result)

    @pytest.mark.asyncio
    async def test_size(self, mock_backend):
        from server import android_screen
        r = ok(await android_screen("size"))
        assert "data" in r

    @pytest.mark.asyncio
    async def test_is_on(self, mock_backend):
        from server import android_screen
        r = ok(await android_screen("is_on"))
        assert r["data"] is True

    @pytest.mark.asyncio
    async def test_wake(self, mock_backend):
        from server import android_screen
        ok(await android_screen("wake"))
        mock_backend.wake_screen.assert_called_once()

    @pytest.mark.asyncio
    async def test_ocr(self, mock_backend):
        from server import android_screen
        r = ok(await android_screen("ocr", {"lang": "fra+eng"}))
        assert r["data"] == "Hello World"
        mock_backend.ocr_screen.assert_called_with("fra+eng")

    @pytest.mark.asyncio
    async def test_ocr_default_lang(self, mock_backend):
        from server import android_screen
        await android_screen("ocr")
        mock_backend.ocr_screen.assert_called_with("fra+eng")

    @pytest.mark.asyncio
    async def test_find_image_missing_template(self, mock_backend):
        from server import android_screen
        err(await android_screen("find_image", {}))

    @pytest.mark.asyncio
    async def test_find_image_success(self, mock_backend):
        from server import android_screen
        r = json.loads(await android_screen("find_image", {"template_b64": "AAAA"}))
        assert r["found"] is True

    @pytest.mark.asyncio
    async def test_viewer_launches_process(self, mock_backend, mocker, tmp_path):
        from server import android_screen
        fake_proc = MagicMock()
        fake_proc.pid = 9999
        mocker.patch("server.subprocess.Popen", return_value=fake_proc)
        viewer_py = tmp_path / "viewer.py"
        viewer_py.write_text("")
        mocker.patch("server._ROOT", tmp_path)
        r = ok(await android_screen("viewer"))
        assert r["pid"] == 9999

    @pytest.mark.asyncio
    async def test_unknown_action(self, mock_backend):
        from server import android_screen
        d = err(await android_screen("inexistant"))
        assert "Action inconnue" in d["error"]


# ══════════════════════════════════════════════════════════════════════════════
# OUTIL 3 — android_interact
# ══════════════════════════════════════════════════════════════════════════════

class TestAndroidInteract:

    @pytest.mark.asyncio
    async def test_tap(self, mock_backend):
        from server import android_interact
        ok(await android_interact("tap", {"x": 540, "y": 960}))
        mock_backend.tap.assert_called_with(540.0, 960.0)

    @pytest.mark.asyncio
    async def test_double_tap(self, mock_backend):
        from server import android_interact
        ok(await android_interact("double_tap", {"x": 100, "y": 200}))
        mock_backend.double_tap.assert_called_once()

    @pytest.mark.asyncio
    async def test_long_press_default_duration(self, mock_backend):
        from server import android_interact
        await android_interact("long_press", {"x": 100, "y": 200})
        mock_backend.long_press.assert_called_with(100.0, 200.0, 800)

    @pytest.mark.asyncio
    async def test_swipe(self, mock_backend):
        from server import android_interact
        ok(await android_interact("swipe", {"x1": 0, "y1": 500, "x2": 1000, "y2": 500}))
        mock_backend.swipe.assert_called_with(0.0, 500.0, 1000.0, 500.0, 300)

    @pytest.mark.asyncio
    async def test_drag(self, mock_backend):
        from server import android_interact
        ok(await android_interact("drag", {"x1": 0, "y1": 0, "x2": 500, "y2": 500}))

    @pytest.mark.asyncio
    async def test_pinch(self, mock_backend):
        from server import android_interact
        ok(await android_interact("pinch", {"x": 540, "y": 960, "scale": 2.0}))
        mock_backend.pinch_zoom.assert_called_with(540.0, 960.0, 2.0, 500)

    @pytest.mark.asyncio
    async def test_type(self, mock_backend):
        from server import android_interact
        ok(await android_interact("type", {"text": "hello"}))
        mock_backend.input_text.assert_called_with("hello")

    @pytest.mark.asyncio
    async def test_type_missing_text(self, mock_backend):
        from server import android_interact
        err(await android_interact("type", {}))

    @pytest.mark.asyncio
    async def test_clear(self, mock_backend):
        from server import android_interact
        ok(await android_interact("clear"))
        mock_backend.clear_field.assert_called_once()

    @pytest.mark.asyncio
    async def test_submit(self, mock_backend):
        from server import android_interact
        ok(await android_interact("submit", {"text": "search query"}))
        mock_backend.type_and_submit.assert_called_with("search query")

    @pytest.mark.asyncio
    async def test_key(self, mock_backend):
        from server import android_interact
        ok(await android_interact("key", {"key": "BACK"}))
        mock_backend.press_key.assert_called_with("BACK")

    @pytest.mark.asyncio
    async def test_key_missing(self, mock_backend):
        from server import android_interact
        err(await android_interact("key", {}))

    @pytest.mark.asyncio
    async def test_combo(self, mock_backend):
        from server import android_interact
        ok(await android_interact("combo", {"keys": [24, 25]}))
        mock_backend.key_combo.assert_called_with([24, 25])

    @pytest.mark.asyncio
    async def test_hierarchy(self, mock_backend, sample_ui_xml):
        from server import android_interact
        r = ok(await android_interact("hierarchy"))
        assert "data" in r

    @pytest.mark.asyncio
    async def test_find(self, mock_backend):
        from server import android_interact
        r = json.loads(await android_interact("find", {"text": "Start"}))
        assert r["found"] is True

    @pytest.mark.asyncio
    async def test_find_missing_text(self, mock_backend):
        from server import android_interact
        err(await android_interact("find", {}))

    @pytest.mark.asyncio
    async def test_wait(self, mock_backend):
        from server import android_interact
        r = json.loads(await android_interact("wait", {"text": "Start", "timeout": 5}))
        assert r["found"] is True
        mock_backend.wait_for_element.assert_called_with("Start", 5, True)

    @pytest.mark.asyncio
    async def test_scroll(self, mock_backend):
        from server import android_interact
        json.loads(await android_interact("scroll", {"text": "Item", "direction": "down"}))
        mock_backend.scroll_to_element.assert_called_with("Item", "down", 5)

    @pytest.mark.asyncio
    async def test_assert_visible(self, mock_backend):
        from server import android_interact
        r = json.loads(await android_interact("assert", {"text": "Start"}))
        assert r["visible"] is True

    @pytest.mark.asyncio
    async def test_unknown_action(self, mock_backend):
        from server import android_interact
        d = err(await android_interact("fly"))
        assert "Action inconnue" in d["error"]


# ══════════════════════════════════════════════════════════════════════════════
# OUTIL 4 — android_app
# ══════════════════════════════════════════════════════════════════════════════

class TestAndroidApp:

    @pytest.mark.asyncio
    async def test_launch(self, mock_backend):
        from server import android_app
        ok(await android_app("launch", {"package": "com.whatsapp"}))
        mock_backend.launch_app.assert_called_with("com.whatsapp")

    @pytest.mark.asyncio
    async def test_launch_missing_package(self, mock_backend):
        from server import android_app
        err(await android_app("launch", {}))

    @pytest.mark.asyncio
    async def test_close(self, mock_backend):
        from server import android_app
        ok(await android_app("close", {"package": "com.whatsapp"}))

    @pytest.mark.asyncio
    async def test_list_apps(self, mock_backend):
        from server import android_app
        r = ok(await android_app("list"))
        assert r["count"] == 1

    @pytest.mark.asyncio
    async def test_list_apps_include_system(self, mock_backend):
        from server import android_app
        await android_app("list", {"include_system": True})
        mock_backend.list_apps.assert_called_with(True)

    @pytest.mark.asyncio
    async def test_current(self, mock_backend):
        from server import android_app
        r = ok(await android_app("current"))
        assert "com.android.launcher" in r["data"]

    @pytest.mark.asyncio
    async def test_open_url(self, mock_backend):
        from server import android_app
        ok(await android_app("url", {"url": "https://google.com"}))
        mock_backend.open_url.assert_called_with("https://google.com")

    @pytest.mark.asyncio
    async def test_url_missing(self, mock_backend):
        from server import android_app
        err(await android_app("url", {}))

    @pytest.mark.asyncio
    async def test_intent(self, mock_backend):
        from server import android_app
        ok(await android_app("intent", {"action": "android.intent.action.VIEW"}))

    @pytest.mark.asyncio
    async def test_intent_missing_action(self, mock_backend):
        from server import android_app
        err(await android_app("intent", {}))

    @pytest.mark.asyncio
    async def test_settings(self, mock_backend):
        from server import android_app
        ok(await android_app("settings", {"section": "wifi"}))
        mock_backend.open_settings.assert_called_with("wifi")

    @pytest.mark.asyncio
    async def test_settings_default(self, mock_backend):
        from server import android_app
        await android_app("settings")
        mock_backend.open_settings.assert_called_with("main")

    @pytest.mark.asyncio
    async def test_unknown_action(self, mock_backend):
        from server import android_app
        err(await android_app("blah"))


# ══════════════════════════════════════════════════════════════════════════════
# OUTIL 5 — android_files
# ══════════════════════════════════════════════════════════════════════════════

class TestAndroidFiles:

    @pytest.mark.asyncio
    async def test_push(self, mock_backend):
        from server import android_files
        ok(await android_files("push", {"local_path": "/tmp/a.txt", "remote_path": "/sdcard/a.txt"}))

    @pytest.mark.asyncio
    async def test_push_missing_params(self, mock_backend):
        from server import android_files
        err(await android_files("push", {"local_path": "/tmp/a.txt"}))

    @pytest.mark.asyncio
    async def test_pull_b64(self, mock_backend):
        from server import android_files
        r = ok(await android_files("pull_b64", {"remote_path": "/sdcard/a.txt"}))
        assert "data" in r

    @pytest.mark.asyncio
    async def test_pull_b64_missing(self, mock_backend):
        from server import android_files
        err(await android_files("pull_b64", {}))

    @pytest.mark.asyncio
    async def test_list(self, mock_backend):
        from server import android_files
        r = ok(await android_files("list", {"directory": "/sdcard"}))
        assert r["count"] == 1

    @pytest.mark.asyncio
    async def test_list_default_dir(self, mock_backend):
        from server import android_files
        await android_files("list")
        mock_backend.list_files.assert_called_with("/sdcard")

    @pytest.mark.asyncio
    async def test_unknown_action(self, mock_backend):
        from server import android_files
        err(await android_files("write"))


# ══════════════════════════════════════════════════════════════════════════════
# OUTIL 6 — android_system
# ══════════════════════════════════════════════════════════════════════════════

class TestAndroidSystem:

    @pytest.mark.asyncio
    async def test_shell(self, mock_backend):
        from server import android_system
        r = ok(await android_system("shell", {"command": "uptime"}))
        assert r["data"] == "output shell"

    @pytest.mark.asyncio
    async def test_shell_missing_command(self, mock_backend):
        from server import android_system
        err(await android_system("shell", {}))

    @pytest.mark.asyncio
    async def test_logs(self, mock_backend):
        from server import android_system
        r = ok(await android_system("logs", {"lines": 10}))
        assert "logcat" in r["data"]

    @pytest.mark.asyncio
    async def test_battery(self, mock_backend):
        from server import android_system
        r = ok(await android_system("battery"))
        assert r["data"]["level"] == 85

    @pytest.mark.asyncio
    async def test_clipboard_get(self, mock_backend):
        from server import android_system
        r = ok(await android_system("clipboard_get"))
        assert r["data"] == "clipboard text"

    @pytest.mark.asyncio
    async def test_clipboard_set(self, mock_backend):
        from server import android_system
        ok(await android_system("clipboard_set", {"text": "new content"}))
        mock_backend.set_clipboard.assert_called_with("new content")

    @pytest.mark.asyncio
    async def test_clipboard_set_missing(self, mock_backend):
        from server import android_system
        err(await android_system("clipboard_set", {}))

    @pytest.mark.asyncio
    async def test_volume(self, mock_backend):
        from server import android_system
        ok(await android_system("volume", {"level": 50, "stream": "music"}))
        mock_backend.set_volume.assert_called_with(50, "music")

    @pytest.mark.asyncio
    async def test_volume_missing_level(self, mock_backend):
        from server import android_system
        err(await android_system("volume", {}))

    @pytest.mark.asyncio
    async def test_rotation(self, mock_backend):
        from server import android_system
        ok(await android_system("rotation", {"rotation": 1}))
        mock_backend.set_rotation.assert_called_with(1)

    @pytest.mark.asyncio
    async def test_wifi(self, mock_backend):
        from server import android_system
        ok(await android_system("wifi", {"enabled": True}))
        mock_backend.toggle_wifi.assert_called_with(True)

    @pytest.mark.asyncio
    async def test_wifi_missing(self, mock_backend):
        from server import android_system
        err(await android_system("wifi", {}))

    @pytest.mark.asyncio
    async def test_gps(self, mock_backend):
        from server import android_system
        ok(await android_system("gps", {"lat": 48.8566, "lng": 2.3522}))
        mock_backend.mock_gps.assert_called_with(48.8566, 2.3522)

    @pytest.mark.asyncio
    async def test_gps_missing(self, mock_backend):
        from server import android_system
        err(await android_system("gps", {"lat": 48.8566}))

    @pytest.mark.asyncio
    async def test_sensors(self, mock_backend):
        from server import android_system
        r = ok(await android_system("sensors", {"sensor": "light"}))
        assert r["data"]["light"] == 250

    @pytest.mark.asyncio
    async def test_wifi_list(self, mock_backend):
        from server import android_system
        r = ok(await android_system("wifi_list"))
        assert r["count"] == 1

    @pytest.mark.asyncio
    async def test_notifications(self, mock_backend):
        from server import android_system
        r = ok(await android_system("notifications"))
        assert r["count"] == 1

    @pytest.mark.asyncio
    async def test_contacts(self, mock_backend):
        from server import android_system
        r = ok(await android_system("contacts", {"search": "Alice"}))
        assert r["count"] == 1

    @pytest.mark.asyncio
    async def test_sms(self, mock_backend):
        from server import android_system
        ok(await android_system("sms", {"to": "+33612345678", "message": "Hello"}))

    @pytest.mark.asyncio
    async def test_sms_missing_params(self, mock_backend):
        from server import android_system
        err(await android_system("sms", {"to": "+33612345678"}))

    @pytest.mark.asyncio
    async def test_unknown_action(self, mock_backend):
        from server import android_system
        err(await android_system("reboot"))


# ══════════════════════════════════════════════════════════════════════════════
# OUTIL 7 — android_automation
# ══════════════════════════════════════════════════════════════════════════════

class TestAndroidAutomation:

    @pytest.mark.asyncio
    async def test_batch_tap(self, mock_backend):
        from server import android_automation
        r = ok(await android_automation("batch", {"actions": [{"action": "tap", "x": 100, "y": 200}]}))
        assert r["count"] == 1
        assert r["results"][0]["success"] is True

    @pytest.mark.asyncio
    async def test_batch_multiple(self, mock_backend):
        from server import android_automation
        r = ok(await android_automation("batch", {
            "actions": [
                {"action": "key", "key": "HOME"},
                {"action": "tap", "x": 540, "y": 960},
                {"action": "type", "text": "hello"},
            ]
        }))
        assert r["count"] == 3

    @pytest.mark.asyncio
    async def test_batch_unknown_action(self, mock_backend):
        from server import android_automation
        r = ok(await android_automation("batch", {"actions": [{"action": "fly"}]}))
        assert r["results"][0]["success"] is False

    @pytest.mark.asyncio
    async def test_batch_stop_on_error(self, mock_backend):
        from server import android_automation
        r = ok(await android_automation("batch", {
            "actions": [{"action": "fly"}, {"action": "tap", "x": 100, "y": 200}],
            "stop_on_error": True,
        }))
        assert r["count"] == 1  # stoppé après le premier échec

    @pytest.mark.asyncio
    async def test_batch_missing_actions(self, mock_backend):
        from server import android_automation
        err(await android_automation("batch", {}))

    @pytest.mark.asyncio
    async def test_macro_lifecycle(self, mock_backend):
        from server import android_automation

        # start
        r = ok(await android_automation("macro_start", {"name": "test_macro"}))
        assert r["recording"] == "test_macro"

        # record
        r = ok(await android_automation("macro_record", {"action": "tap", "x": 100, "y": 200}))
        assert r["recorded"] == 1

        r = ok(await android_automation("macro_record", {"action": "key", "key": "HOME"}))
        assert r["recorded"] == 2

        # stop
        r = ok(await android_automation("macro_stop"))
        assert r["name"] == "test_macro"
        assert r["count"] == 2

        # list
        r = ok(await android_automation("macro_list"))
        assert "test_macro" in r["data"]

        # replay
        r = ok(await android_automation("macro_replay", {"name": "test_macro", "delay_ms": 0}))
        assert r["executed"] == 2

        # delete
        r = ok(await android_automation("macro_delete", {"name": "test_macro"}))
        assert r["deleted"] == "test_macro"

        # list → vide
        r = ok(await android_automation("macro_list"))
        assert "test_macro" not in r["data"]

    @pytest.mark.asyncio
    async def test_macro_record_without_start(self, mock_backend):
        from server import android_automation
        # S'assurer qu'aucun enregistrement n'est en cours
        import server as srv
        srv._current_macro_name = None
        err(await android_automation("macro_record", {"action": "tap"}))

    @pytest.mark.asyncio
    async def test_macro_replay_not_found(self, mock_backend):
        from server import android_automation
        err(await android_automation("macro_replay", {"name": "ghost_macro"}))

    @pytest.mark.asyncio
    async def test_macro_delete_not_found(self, mock_backend):
        from server import android_automation
        err(await android_automation("macro_delete", {"name": "ghost"}))

    @pytest.mark.asyncio
    async def test_unknown_action(self, mock_backend):
        from server import android_automation
        err(await android_automation("schedule"))


# ══════════════════════════════════════════════════════════════════════════════
# Tests transversaux — MCP tool count
# ══════════════════════════════════════════════════════════════════════════════

class TestMcpTools:

    @pytest.mark.asyncio
    async def test_exactly_7_tools(self):
        from server import mcp
        tools = await mcp.list_tools()
        assert len(tools) == 7, f"Attendu 7 outils MCP, trouvé {len(tools)}"

    @pytest.mark.asyncio
    async def test_all_tool_names(self):
        from server import mcp
        tools = await mcp.list_tools()
        names = {t.name for t in tools}
        expected = {
            "android_device", "android_screen", "android_interact",
            "android_app", "android_files", "android_system", "android_automation",
        }
        assert names == expected

    @pytest.mark.asyncio
    async def test_all_tools_have_description(self):
        from server import mcp
        tools = await mcp.list_tools()
        for t in tools:
            assert t.description and len(t.description) > 20, \
                f"Outil {t.name} a une description trop courte"


# Import nécessaire pour le test viewer
from unittest.mock import MagicMock
