"""
backends/companion_backend.py — Backend App Compagnon Flutter (fallback)
=========================================================================
Wrapping de la connexion WebSocket à l'app compagnon Flutter.
Utilisé comme fallback quand ADB n'est pas disponible.

L'app compagnon se connecte à relay.py (WebSocket :8765).
Ce backend parle à relay.py via HTTP POST /command (port 8090).
"""

from __future__ import annotations

import asyncio
import base64
from typing import Any, Optional

import aiohttp


_RELAY_URL = "http://127.0.0.1:8090"
_TIMEOUT = 35


class CompanionBackend:
    """
    Backend fallback qui délègue les commandes à relay.py → app Flutter.
    Interface identique à AdbBackend pour un remplacement transparent.
    """

    def __init__(self, relay_url: str = _RELAY_URL):
        self._url = relay_url
        self._session: Optional[aiohttp.ClientSession] = None
        self.connected: bool = False
        self.device_ip: Optional[str] = None

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def _cmd(self, action: str, **kwargs) -> dict:
        session = await self._ensure_session()
        payload = {"action": action, **kwargs}
        try:
            async with session.post(
                f"{self._url}/command",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=_TIMEOUT),
            ) as resp:
                return await resp.json()
        except aiohttp.ClientConnectorError:
            raise ConnectionError("relay.py non disponible sur :8090 — lance : python relay.py")
        except asyncio.TimeoutError:
            raise TimeoutError(f"Pas de réponse de l'app compagnon ({_TIMEOUT}s)")

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    # ── Délégation générique ──────────────────────────────────────────────────

    async def screenshot(self) -> bytes:
        r = await self._cmd("screenshot")
        if not r.get("success"):
            raise RuntimeError(r.get("error", "Screenshot échouée"))
        return base64.b64decode(r["data"])

    async def screenshot_region(self, x: int, y: int, width: int, height: int) -> bytes:
        r = await self._cmd("screenshot_region", x=x, y=y, width=width, height=height)
        if not r.get("success"):
            raise RuntimeError(r.get("error", "screenshot_region échouée"))
        return base64.b64decode(r["data"])

    async def get_live_frame(self) -> dict:
        return await self._cmd("get_live_frame")

    async def start_stream(self) -> dict:
        return await self._cmd("start_stream")

    async def stop_stream(self) -> None:
        await self._cmd("stop_stream")

    async def is_screen_on(self) -> bool:
        r = await self._cmd("is_screen_on")
        return bool(r.get("data", False))

    async def wake_screen(self) -> None:
        await self._cmd("wake_screen")

    async def get_screen_size(self) -> dict:
        r = await self._cmd("get_screen_size")
        return r.get("data", {"width": 0, "height": 0})

    async def tap(self, x: float, y: float) -> None:
        await self._cmd("tap", x=x, y=y)

    async def double_tap(self, x: float, y: float) -> None:
        await self._cmd("double_tap", x=x, y=y)

    async def long_press(self, x: float, y: float, duration_ms: int = 800) -> None:
        await self._cmd("long_press", x=x, y=y, duration_ms=duration_ms)

    async def swipe(self, x1: float, y1: float, x2: float, y2: float, duration_ms: int = 300) -> None:
        await self._cmd("swipe", x1=x1, y1=y1, x2=x2, y2=y2, duration_ms=duration_ms)

    async def drag_and_drop(self, x1: float, y1: float, x2: float, y2: float, duration_ms: int = 1000) -> None:
        await self._cmd("drag_and_drop", x1=x1, y1=y1, x2=x2, y2=y2, duration_ms=duration_ms)

    async def pinch_zoom(self, x: float, y: float, scale: float, duration_ms: int = 500) -> None:
        await self._cmd("pinch_zoom", x=x, y=y, scale=scale, duration_ms=duration_ms)

    async def multi_touch(self, points: list[dict]) -> None:
        await self._cmd("multi_touch", points=points)

    async def input_text(self, text: str) -> None:
        await self._cmd("input_text", text=text)

    async def clear_field(self) -> None:
        await self._cmd("clear_field")

    async def type_and_submit(self, text: str) -> None:
        await self._cmd("type_and_submit", text=text)

    async def press_key(self, key: str) -> None:
        await self._cmd("press_key", key=key)

    async def key_combo(self, keys: list[int]) -> None:
        await self._cmd("key_combo", keys=keys)

    async def get_ui_hierarchy(self) -> str:
        r = await self._cmd("get_ui_hierarchy")
        return str(r.get("data", ""))

    async def find_and_tap(self, text: str, partial_match: bool = True) -> bool:
        r = await self._cmd("find_and_tap", text=text, partial_match=partial_match)
        return bool(r.get("found", False))

    async def wait_for_element(self, text: str, timeout: int = 10, partial_match: bool = True) -> bool:
        r = await self._cmd("wait_for_element", text=text, timeout=timeout, partial_match=partial_match)
        return bool(r.get("found", False))

    async def scroll_to_element(self, text: str, direction: str = "down", max_swipes: int = 5) -> bool:
        r = await self._cmd("scroll_to_element", text=text, direction=direction, max_swipes=max_swipes)
        return bool(r.get("success", False))

    async def assert_visible(self, text: str, partial_match: bool = True) -> bool:
        r = await self._cmd("assert_visible", text=text, partial_match=partial_match)
        return bool(r.get("visible", False))

    async def launch_app(self, package: str) -> None:
        r = await self._cmd("launch_app", package=package)
        if not r.get("success"):
            raise RuntimeError(r.get("error", f"Impossible de lancer {package}"))

    async def close_app(self, package: str) -> None:
        await self._cmd("close_app", package=package)

    async def list_apps(self, include_system: bool = False) -> list[dict]:
        r = await self._cmd("list_apps", include_system=include_system)
        return r.get("data", [])

    async def install_app(self, apk_path: str) -> dict:
        r = await self._cmd("install_apk", source=apk_path)
        return {"success": r.get("success", False), "output": r.get("message", r.get("error", ""))}

    async def uninstall_app(self, package: str) -> dict:
        r = await self._cmd("uninstall_app", package=package)
        return {"success": r.get("success", False)}

    async def get_current_app(self) -> str:
        r = await self._cmd("get_current_app")
        return str(r.get("data", ""))

    async def open_url(self, url: str) -> None:
        await self._cmd("open_url", url=url)

    async def send_intent(self, action: str, uri: str = "", package: str = "", extras: Optional[dict] = None) -> None:
        await self._cmd("send_intent", action=action, uri=uri, package=package, extras=extras or {})

    async def open_settings(self, section: str = "main") -> None:
        await self._cmd("open_settings", section=section)

    async def push_file(self, local_path: str, remote_path: str) -> dict:
        import pathlib
        data_b64 = base64.b64encode(pathlib.Path(local_path).read_bytes()).decode()
        r = await self._cmd("push_file", path=remote_path, data=data_b64)
        return {"success": r.get("success", False)}

    async def pull_file(self, remote_path: str, local_path: str) -> dict:
        r = await self._cmd("pull_file", path=remote_path)
        if r.get("success") and r.get("data"):
            import pathlib
            pathlib.Path(local_path).write_bytes(base64.b64decode(r["data"]))
        return {"success": r.get("success", False)}

    async def pull_file_b64(self, remote_path: str) -> str:
        r = await self._cmd("pull_file", path=remote_path)
        if not r.get("success"):
            raise RuntimeError(r.get("error", f"Impossible de lire {remote_path}"))
        return r.get("data", "")

    async def push_file_b64(self, remote_path: str, data_b64: str) -> None:
        r = await self._cmd("push_file", path=remote_path, data=data_b64)
        if not r.get("success"):
            raise RuntimeError(r.get("error", "Push échoué"))

    async def list_files(self, directory: str) -> list[dict]:
        r = await self._cmd("list_files", directory=directory)
        return r.get("data", [])

    async def shell_exec(self, command: str, timeout: int = 30) -> str:
        r = await self._cmd("shell_exec", command=command)
        return str(r.get("data", r.get("error", "")))

    async def get_logs(self, lines: int = 100, package: str = "") -> str:
        r = await self._cmd("get_logs", lines=lines, package=package)
        return str(r.get("data", ""))

    async def get_battery(self) -> dict:
        r = await self._cmd("get_battery")
        return r.get("data", {})

    async def get_clipboard(self) -> str:
        r = await self._cmd("get_clipboard")
        return str(r.get("data", ""))

    async def set_clipboard(self, text: str) -> None:
        await self._cmd("set_clipboard", text=text)

    async def set_volume(self, level: int, stream: str = "music") -> None:
        await self._cmd("set_volume", level=level, stream=stream)

    async def set_rotation(self, rotation: int) -> None:
        await self._cmd("set_rotation", rotation=rotation)

    async def toggle_wifi(self, enabled: bool) -> None:
        await self._cmd("toggle_wifi", enabled=enabled)

    async def toggle_bluetooth(self, enabled: bool) -> None:
        await self._cmd("toggle_bluetooth", enabled=enabled)

    async def enable_mobile_data(self, enabled: bool = True) -> None:
        await self._cmd("enable_mobile_data", enabled=enabled)

    async def read_notifications(self) -> list[dict]:
        r = await self._cmd("read_notifications")
        data = r.get("data", [])
        return data if isinstance(data, list) else []

    async def mock_gps(self, lat: float, lng: float) -> None:
        await self._cmd("mock_gps", lat=lat, lng=lng)

    async def get_sensor_data(self, sensor: str = "all") -> str:
        r = await self._cmd("get_sensor_data", sensor=sensor)
        return str(r.get("data", ""))

    async def get_wifi_list(self) -> list[str]:
        r = await self._cmd("get_wifi_list")
        data = r.get("data", [])
        return data if isinstance(data, list) else []

    async def connect_wifi(self, ssid: str, password: str = "") -> dict:
        return await self._cmd("connect_wifi", ssid=ssid, password=password)

    async def get_contacts(self, search: str = "", limit: int = 20) -> list[dict]:
        r = await self._cmd("get_contacts", search=search, limit=limit)
        return r.get("data", [])

    async def send_sms(self, to: str, message: str) -> str:
        r = await self._cmd("send_sms", to=to, message=message)
        return str(r.get("data", "SMS envoyé"))

    async def ocr_screen(self, lang: str = "fra+eng") -> str:
        r = await self._cmd("ocr_screen", lang=lang)
        if not r.get("success"):
            raise RuntimeError(r.get("error", "OCR échouée"))
        return str(r.get("data", ""))

    async def find_by_image(self, template_b64: str, threshold: float = 0.8) -> dict:
        r = await self._cmd("find_by_image", template=template_b64, threshold=threshold)
        return r

    async def auto_setup(self) -> list[dict]:
        r = await self._cmd("auto_setup")
        return r.get("steps", [{"desc": "auto_setup via companion", "ok": r.get("success", False)}])
