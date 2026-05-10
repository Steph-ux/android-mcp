"""
backends/adb_backend.py — Backend ADB + uiautomator2
=====================================================
Backend principal du framework Android MCP.

Contrôle n'importe quel téléphone/émulateur Android via :
  - uiautomator2 : tap, swipe, input, get_ui_hierarchy, find_element, wait_for...
  - ADB brut     : screenshot, shell, install, logs, fichiers, système...

Prérequis :
  pip install uiautomator2 adbutils
  python -m uiautomator2 init   ← installe l'agent ATX sur le device (une fois)
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Optional

# ── uiautomator2 (optionnel au démarrage) ─────────────────────────────────────
try:
    import uiautomator2 as u2
    _U2_AVAILABLE = True
except ImportError:
    _U2_AVAILABLE = False

# ── OCR & Vision ──────────────────────────────────────────────────────────────
try:
    import pytesseract
    from PIL import Image
    _OCR_AVAILABLE = True
except ImportError:
    _OCR_AVAILABLE = False

try:
    import cv2
    import numpy as np
    _CV2_AVAILABLE = True
except ImportError:
    _CV2_AVAILABLE = False


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _adb(*args: str, serial: str = "", timeout: int = 15) -> tuple[int, str, str]:
    cmd = ["adb"]
    if serial:
        cmd += ["-s", serial]
    cmd += list(args)
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
        )
        return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()
    except FileNotFoundError:
        return -1, "", "adb non trouvé dans le PATH"
    except subprocess.TimeoutExpired:
        return -2, "", f"timeout ({timeout}s)"
    except Exception as e:
        return -3, "", str(e)


def _adb_shell(cmd: str, serial: str = "", timeout: int = 15) -> str:
    _, out, err = _adb("shell", cmd, serial=serial, timeout=timeout)
    return out or err


async def _adb_async(*args: str, serial: str = "", timeout: int = 15) -> tuple[int, bytes, bytes]:
    cmd = ["adb"]
    if serial:
        cmd += ["-s", serial]
    cmd += list(args)
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return proc.returncode or 0, stdout, stderr
    except asyncio.TimeoutError:
        return -2, b"", b"timeout"
    except Exception as e:
        return -3, b"", str(e).encode()


# ─── AdbBackend ────────────────────────────────────────────────────────────────

class AdbBackend:
    """
    Backend de contrôle Android via ADB + uiautomator2.
    Toutes les méthodes sont async pour compatibilité avec server.py (FastMCP).
    """

    def __init__(self, serial: str = ""):
        self._serial = serial
        self._d = None          # uiautomator2 device handle
        self._stream_active = False
        self._stream_task: Optional[asyncio.Task] = None
        self._latest_frame: Optional[bytes] = None
        self._latest_frame_time: float = 0.0
        self._stream_clients: set = set()

    @property
    def connected(self) -> bool:
        """Vérifie si le device répond à ADB."""
        rc, out, _ = _adb("get-state", serial=self._serial, timeout=3)
        return rc == 0 and "device" in out

    def set_serial(self, serial: str) -> None:
        if serial != self._serial:
            self._serial = serial
            self._d = None  # reset uiautomator2 handle

    def _s(self) -> str:
        return self._serial

    def _check_device(self) -> None:
        """Lève une erreur claire si le device est offline/introuvable."""
        rc, out, err = _adb("get-state", serial=self._serial, timeout=4)
        if rc != 0 or "device" not in out:
            serial_hint = f" ({self._serial})" if self._serial else ""
            raise ConnectionError(
                f"Device ADB{serial_hint} non disponible (état : {out or err or 'inconnu'}). "
                "Vérifie : adb devices"
            )

    # ── uiautomator2 handle ───────────────────────────────────────────────────

    def _get_u2(self):
        if not _U2_AVAILABLE:
            raise RuntimeError(
                "uiautomator2 non installé. Lance : pip install uiautomator2 && python -m uiautomator2 init"
            )
        if self._d is None:
            if self._serial:
                self._d = u2.connect(self._serial)
            else:
                self._d = u2.connect()
        return self._d

    # ── Screenshot ────────────────────────────────────────────────────────────

    async def screenshot(self, _retries: int = 2) -> bytes:
        """Capture PNG via ADB (bypass FLAG_SECURE). Retry automatique."""
        last_err = "erreur inconnue"
        for attempt in range(1, _retries + 2):
            rc, stdout, stderr = await _adb_async(
                "exec-out", "screencap", "-p", serial=self._s(), timeout=10
            )
            if rc == 0 and stdout and len(stdout) > 200:
                return stdout
            err_msg = stderr.decode(errors="replace").strip() if isinstance(stderr, bytes) else str(stderr)
            last_err = err_msg or f"rc={rc}, stdout={len(stdout) if stdout else 0} bytes"
            if attempt <= _retries:
                await asyncio.sleep(0.3 * attempt)
        serial_hint = f" device={self._s()!r}" if self._s() else ""
        raise RuntimeError(f"Screenshot ADB échouée{serial_hint} après {_retries+1} essais : {last_err}")

    async def screenshot_region(self, x: int, y: int, width: int, height: int) -> bytes:
        raw = await self.screenshot()
        if _CV2_AVAILABLE:
            arr = np.frombuffer(raw, np.uint8)
            img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if img is not None:
                region = img[y:y+height, x:x+width]
                _, enc = cv2.imencode(".png", region)
                return enc.tobytes()
        if _OCR_AVAILABLE:
            img = Image.open(io.BytesIO(raw))
            cropped = img.crop((x, y, x + width, y + height))
            buf = io.BytesIO()
            cropped.save(buf, format="PNG")
            return buf.getvalue()
        raise RuntimeError("Installer opencv-python-headless ou Pillow pour screenshot_region")

    # ── Stream ────────────────────────────────────────────────────────────────

    async def start_stream(self) -> dict:
        if self._stream_active:
            return {"success": True, "mode": "adb_bypass", "already_active": True}
        self._stream_active = True
        self._stream_task = asyncio.create_task(self._stream_loop())
        return {"success": True, "mode": "adb_bypass", "viewer": "http://localhost:8090"}

    async def stop_stream(self) -> None:
        self._stream_active = False
        if self._stream_task:
            self._stream_task.cancel()
            try:
                await self._stream_task
            except asyncio.CancelledError:
                pass
            self._stream_task = None

    async def _stream_loop(self):
        while self._stream_active:
            t0 = time.time()
            try:
                frame = await self.screenshot()
                self._latest_frame = frame
                self._latest_frame_time = time.time()
            except Exception:
                pass
            elapsed = time.time() - t0
            await asyncio.sleep(max(0.05, 0.0625 - elapsed))  # ~16fps target

    async def get_live_frame(self) -> dict:
        age = time.time() - self._latest_frame_time if self._latest_frame else 999
        if self._latest_frame is None or age > 3:
            try:
                frame = await self.screenshot()
                self._latest_frame = frame
                self._latest_frame_time = time.time()
            except Exception as e:
                return {"success": False, "error": str(e)}
        age = time.time() - self._latest_frame_time
        return {
            "success": True,
            "data": base64.b64encode(self._latest_frame).decode(),
            "mime": "image/png",
            "frame_age_ms": int(age * 1000),
            "stream_active": self._stream_active,
        }

    # ── Screen state ──────────────────────────────────────────────────────────

    async def is_screen_on(self) -> bool:
        out = _adb_shell("dumpsys power | grep 'mWakefulness'", serial=self._s())
        return "Awake" in out

    async def wake_screen(self) -> None:
        _adb_shell("input keyevent 26", serial=self._s())  # POWER toggle
        await asyncio.sleep(0.3)
        if not await self.is_screen_on():
            _adb_shell("input keyevent 82", serial=self._s())  # MENU unlock

    async def get_screen_size(self) -> dict:
        out = _adb_shell("wm size", serial=self._s())
        match = re.search(r"(\d+)x(\d+)", out)
        if match:
            return {"width": int(match.group(1)), "height": int(match.group(2))}
        return {"width": 0, "height": 0, "raw": out}

    # ── Interactions tactiles ─────────────────────────────────────────────────

    async def tap(self, x: float, y: float) -> None:
        _adb_shell(f"input tap {int(x)} {int(y)}", serial=self._s())

    async def double_tap(self, x: float, y: float) -> None:
        _adb_shell(f"input tap {int(x)} {int(y)}", serial=self._s())
        await asyncio.sleep(0.1)
        _adb_shell(f"input tap {int(x)} {int(y)}", serial=self._s())

    async def long_press(self, x: float, y: float, duration_ms: int = 800) -> None:
        _adb_shell(
            f"input swipe {int(x)} {int(y)} {int(x)} {int(y)} {duration_ms}",
            serial=self._s(),
        )

    async def swipe(self, x1: float, y1: float, x2: float, y2: float, duration_ms: int = 300) -> None:
        _adb_shell(
            f"input swipe {int(x1)} {int(y1)} {int(x2)} {int(y2)} {duration_ms}",
            serial=self._s(),
        )

    async def drag_and_drop(self, x1: float, y1: float, x2: float, y2: float, duration_ms: int = 1000) -> None:
        _adb_shell(
            f"input draganddrop {int(x1)} {int(y1)} {int(x2)} {int(y2)} {duration_ms}",
            serial=self._s(),
        )

    async def pinch_zoom(self, x: float, y: float, scale: float, duration_ms: int = 500) -> None:
        d = self._get_u2()
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: d.gesture(
            [(x - 100, y), (x + 100, y)],
            [(x - int(100 * scale), y), (x + int(100 * scale), y)],
            steps=max(10, duration_ms // 16),
        ))

    async def multi_touch(self, points: list[dict]) -> None:
        """points: [{x, y, start_ms, end_ms}, ...]"""
        try:
            d = self._get_u2()
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: d.touch.start_gesture().up(*[(p["x"], p["y"]) for p in points]).perform()
            )
        except Exception:
            # Fallback: taps séquentiels
            for p in points:
                await self.tap(p["x"], p["y"])

    # ── Texte ─────────────────────────────────────────────────────────────────

    async def input_text(self, text: str) -> None:
        escaped = text.replace("'", r"\'").replace(" ", "%s").replace("&", r"\&")
        _adb_shell(f"input text '{escaped}'", serial=self._s())

    async def clear_field(self) -> None:
        _adb_shell("input keyevent KEYCODE_CTRL_A", serial=self._s())
        await asyncio.sleep(0.1)
        _adb_shell("input keyevent KEYCODE_DEL", serial=self._s())

    async def type_and_submit(self, text: str) -> None:
        await self.input_text(text)
        await asyncio.sleep(0.1)
        _adb_shell("input keyevent 66", serial=self._s())  # ENTER

    # ── Touches système ───────────────────────────────────────────────────────

    _KEY_MAP = {
        "BACK": "4", "HOME": "3", "RECENTS": "187",
        "NOTIFICATIONS": "83", "POWER_DIALOG": "26",
        "VOLUME_UP": "24", "VOLUME_DOWN": "25",
        "ENTER": "66", "DEL": "67", "TAB": "61",
    }

    async def press_key(self, key: str) -> None:
        keycode = self._KEY_MAP.get(key.upper(), key)
        _adb_shell(f"input keyevent {keycode}", serial=self._s())

    async def key_combo(self, keys: list[int]) -> None:
        for k in keys:
            _adb_shell(f"input keyevent {k}", serial=self._s())

    # ── UI Hierarchy & Navigation ─────────────────────────────────────────────

    async def get_ui_hierarchy(self) -> str:
        """Retourne le XML complet de l'UI via uiautomator dump."""
        loop = asyncio.get_event_loop()
        try:
            d = self._get_u2()
            xml = await loop.run_in_executor(None, lambda: d.dump_hierarchy())
            return xml
        except Exception:
            # Fallback ADB
            _adb_shell("uiautomator dump /sdcard/ui.xml", serial=self._s(), timeout=10)
            rc, out, _ = _adb("pull", "/sdcard/ui.xml", "-", serial=self._s(), timeout=10)
            if rc == 0:
                return out
            raise RuntimeError("get_ui_hierarchy échouée — uiautomator2 non initialisé ?")

    async def find_and_tap(self, text: str, partial_match: bool = True) -> bool:
        try:
            d = self._get_u2()
            loop = asyncio.get_event_loop()
            if partial_match:
                el = await loop.run_in_executor(None, lambda: d(textContains=text))
            else:
                el = await loop.run_in_executor(None, lambda: d(text=text))
            exists = await loop.run_in_executor(None, lambda: el.exists(timeout=3))
            if exists:
                await loop.run_in_executor(None, el.click)
                return True
            return False
        except Exception as e:
            raise RuntimeError(f"find_and_tap échouée : {e}")

    async def wait_for_element(self, text: str, timeout: int = 10, partial_match: bool = True) -> bool:
        try:
            d = self._get_u2()
            loop = asyncio.get_event_loop()
            if partial_match:
                el = await loop.run_in_executor(None, lambda: d(textContains=text))
            else:
                el = await loop.run_in_executor(None, lambda: d(text=text))
            exists = await loop.run_in_executor(None, lambda: el.exists(timeout=timeout))
            return exists
        except Exception:
            return False

    async def scroll_to_element(self, text: str, direction: str = "down", max_swipes: int = 5) -> bool:
        try:
            d = self._get_u2()
            loop = asyncio.get_event_loop()
            forward = direction.lower() != "up"
            found = await loop.run_in_executor(
                None,
                lambda: d(scrollable=True).scroll.to(textContains=text) if forward
                else d(scrollable=True).scroll.to(textContains=text),
            )
            return found
        except Exception:
            return False

    async def assert_visible(self, text: str, partial_match: bool = True) -> bool:
        return await self.wait_for_element(text, timeout=3, partial_match=partial_match)

    # ── Applications ──────────────────────────────────────────────────────────

    async def launch_app(self, package: str) -> None:
        out = _adb_shell(f"monkey -p {package} -c android.intent.category.LAUNCHER 1", serial=self._s())
        if "error" in out.lower() and "monkey" not in out.lower():
            raise RuntimeError(f"Impossible de lancer {package} : {out}")

    async def close_app(self, package: str) -> None:
        _adb_shell(f"am force-stop {package}", serial=self._s())

    async def list_apps(self, include_system: bool = False) -> list[dict]:
        flag = "" if include_system else "-3"  # -3 = only third-party
        out = _adb_shell(f"pm list packages {flag} -f", serial=self._s())
        apps = []
        for line in out.splitlines():
            m = re.match(r"package:(.+)=(.+)", line.strip())
            if m:
                apps.append({"apk": m.group(1), "package": m.group(2)})
        return apps

    async def install_app(self, apk_path: str) -> dict:
        path = Path(apk_path)
        if not path.exists():
            raise FileNotFoundError(f"APK introuvable : {apk_path}")
        rc, out, err = _adb("install", "-r", str(path), serial=self._s(), timeout=120)
        success = rc == 0 and "Success" in out
        return {"success": success, "output": out or err}

    async def uninstall_app(self, package: str) -> dict:
        rc, out, err = _adb("uninstall", package, serial=self._s(), timeout=30)
        success = rc == 0 and "Success" in out
        return {"success": success, "output": out or err}

    async def get_current_app(self) -> str:
        out = _adb_shell(
            "dumpsys activity activities | grep -E 'mCurrentFocus|mFocusedApp' | head -1",
            serial=self._s(),
        )
        m = re.search(r"([a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+)", out)
        return m.group(1) if m else out

    async def open_url(self, url: str) -> None:
        _adb_shell(f"am start -a android.intent.action.VIEW -d '{url}'", serial=self._s())

    async def send_intent(self, action: str, uri: str = "", package: str = "", extras: Optional[dict] = None) -> None:
        cmd = f"am start -a {action}"
        if uri:
            cmd += f" -d '{uri}'"
        if package:
            cmd += f" -n {package}"
        if extras:
            for k, v in extras.items():
                if isinstance(v, bool):
                    cmd += f" --ez {k} {str(v).lower()}"
                elif isinstance(v, int):
                    cmd += f" --ei {k} {v}"
                else:
                    cmd += f" --es {k} '{v}'"
        _adb_shell(cmd, serial=self._s())

    async def open_settings(self, section: str = "main") -> None:
        actions = {
            "main":          "android.settings.SETTINGS",
            "wifi":          "android.settings.WIFI_SETTINGS",
            "bluetooth":     "android.settings.BLUETOOTH_SETTINGS",
            "display":       "android.settings.DISPLAY_SETTINGS",
            "sound":         "android.settings.SOUND_SETTINGS",
            "apps":          "android.settings.APPLICATION_SETTINGS",
            "accessibility": "android.settings.ACCESSIBILITY_SETTINGS",
            "battery":       "android.settings.BATTERY_SAVER_SETTINGS",
            "storage":       "android.settings.INTERNAL_STORAGE_SETTINGS",
            "developer":     "android.settings.APPLICATION_DEVELOPMENT_SETTINGS",
        }
        action = actions.get(section.lower(), actions["main"])
        _adb_shell(f"am start -a {action}", serial=self._s())

    # ── Fichiers ──────────────────────────────────────────────────────────────

    async def push_file(self, local_path: str, remote_path: str) -> dict:
        rc, out, err = _adb("push", local_path, remote_path, serial=self._s(), timeout=60)
        return {"success": rc == 0, "output": out or err}

    async def pull_file(self, remote_path: str, local_path: str) -> dict:
        rc, out, err = _adb("pull", remote_path, local_path, serial=self._s(), timeout=60)
        return {"success": rc == 0, "output": out or err}

    async def pull_file_b64(self, remote_path: str) -> str:
        """Pull un fichier et retourne son contenu en base64."""
        rc, stdout, stderr = await _adb_async(
            "exec-out", f"cat {remote_path}", serial=self._s(), timeout=30
        )
        if rc != 0:
            raise RuntimeError(f"Impossible de lire {remote_path} : {stderr.decode()}")
        return base64.b64encode(stdout).decode()

    async def push_file_b64(self, remote_path: str, data_b64: str) -> None:
        """Push un fichier depuis son contenu en base64."""
        data = base64.b64decode(data_b64)
        import tempfile, os
        with tempfile.NamedTemporaryFile(delete=False, suffix=Path(remote_path).suffix) as tf:
            tf.write(data)
            tmp_path = tf.name
        try:
            rc, out, err = _adb("push", tmp_path, remote_path, serial=self._s(), timeout=60)
            if rc != 0:
                raise RuntimeError(f"Push échoué : {err}")
        finally:
            os.unlink(tmp_path)

    async def list_files(self, directory: str) -> list[dict]:
        out = _adb_shell(f"ls -la {directory}", serial=self._s())
        entries = []
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 8:
                perms = parts[0]
                size = parts[4] if len(parts) > 4 else "0"
                name = parts[-1]
                entries.append({
                    "name": name,
                    "type": "dir" if perms.startswith("d") else "file",
                    "size": size,
                    "permissions": perms,
                })
        return entries

    # ── Système ───────────────────────────────────────────────────────────────

    async def shell_exec(self, command: str, timeout: int = 30) -> str:
        return _adb_shell(command, serial=self._s(), timeout=timeout)

    async def get_logs(self, lines: int = 100, package: str = "") -> str:
        if package:
            pid_out = _adb_shell(f"pidof {package}", serial=self._s())
            pid = pid_out.strip().split()[0] if pid_out.strip() else ""
            cmd = f"logcat -d --pid={pid} -t {lines}" if pid else f"logcat -d -t {lines}"
        else:
            cmd = f"logcat -d -t {lines}"
        return _adb_shell(cmd, serial=self._s(), timeout=30)

    async def get_battery(self) -> dict:
        out = _adb_shell("dumpsys battery", serial=self._s())
        level_m = re.search(r"level:\s*(\d+)", out)
        status_m = re.search(r"status:\s*(\d+)", out)
        plugged_m = re.search(r"plugged:\s*(\d+)", out)
        status_map = {"1": "unknown", "2": "charging", "3": "discharging", "4": "not charging", "5": "full"}
        return {
            "level": int(level_m.group(1)) if level_m else -1,
            "status": status_map.get(status_m.group(1) if status_m else "1", "unknown"),
            "plugged": (plugged_m.group(1) if plugged_m else "0") != "0",
        }

    async def get_clipboard(self) -> str:
        return _adb_shell("cmd clipboard get", serial=self._s()) or ""

    async def set_clipboard(self, text: str) -> None:
        escaped = text.replace("'", r"\'")
        _adb_shell(f"cmd clipboard set '{escaped}'", serial=self._s())

    async def set_volume(self, level: int, stream: str = "music") -> None:
        stream_map = {"music": 3, "ring": 2, "alarm": 4, "notification": 5}
        stream_id = stream_map.get(stream.lower(), 3)
        _adb_shell(f"cmd media_session volume --set {level} --stream {stream_id}", serial=self._s())

    async def set_rotation(self, rotation: int) -> None:
        _adb_shell("content insert --uri content://settings/system --bind name:s:accelerometer_rotation --bind value:i:0", serial=self._s())
        _adb_shell(f"content insert --uri content://settings/system --bind name:s:user_rotation --bind value:i:{rotation}", serial=self._s())

    async def toggle_wifi(self, enabled: bool) -> None:
        state = "enable" if enabled else "disable"
        _adb_shell(f"svc wifi {state}", serial=self._s())

    async def toggle_bluetooth(self, enabled: bool) -> None:
        state = "enable" if enabled else "disable"
        _adb_shell(f"svc bluetooth {state}", serial=self._s())

    async def enable_mobile_data(self, enabled: bool = True) -> None:
        state = "enable" if enabled else "disable"
        _adb_shell(f"svc data {state}", serial=self._s())

    async def read_notifications(self) -> list[dict]:
        out = _adb_shell("dumpsys notification | grep -A5 'NotificationRecord'", serial=self._s())
        notifs = []
        current: dict = {}
        for line in out.splitlines():
            line = line.strip()
            if "pkg=" in line:
                if current:
                    notifs.append(current)
                current = {}
                m = re.search(r"pkg=(\S+)", line)
                if m:
                    current["package"] = m.group(1)
            elif "title=" in line and current:
                m = re.search(r"title=(.+)", line)
                if m:
                    current["title"] = m.group(1).strip()
            elif "text=" in line and current:
                m = re.search(r"text=(.+)", line)
                if m:
                    current["text"] = m.group(1).strip()
        if current:
            notifs.append(current)
        return notifs[:20]

    # ── Localisation & Capteurs ───────────────────────────────────────────────

    async def mock_gps(self, lat: float, lng: float) -> None:
        _adb_shell("appops set com.android.shell android:mock_location allow", serial=self._s())
        _adb_shell(
            f"am start -n com.android.shell/.MockLocationProvider --el lat {lat} --el lng {lng}",
            serial=self._s(),
        )

    async def get_sensor_data(self, sensor: str = "all") -> str:
        if sensor.lower() == "all":
            cmd = "dumpsys sensorservice | head -100"
        else:
            cmd = f"dumpsys sensorservice | grep -i -A3 '{sensor}' | head -40"
        return _adb_shell(cmd, serial=self._s(), timeout=10)

    async def get_wifi_list(self) -> list[str]:
        out = _adb_shell("cmd wifi list-networks", serial=self._s())
        networks = []
        for line in out.splitlines():
            line = line.strip()
            if line and not line.startswith("Id") and not line.startswith("---") and line:
                networks.append(line)
        return networks

    async def connect_wifi(self, ssid: str, password: str = "") -> dict:
        if password:
            cmd = f'cmd wifi connect-network "{ssid}" wpa2 "{password}"'
        else:
            cmd = f'cmd wifi connect-network "{ssid}" open'
        out = _adb_shell(cmd, serial=self._s(), timeout=15)
        success = "successfully" in out.lower() or out == ""
        return {"success": success, "output": out}

    # ── Communication ─────────────────────────────────────────────────────────

    async def get_contacts(self, search: str = "", limit: int = 20) -> list[dict]:
        where = f' WHERE display_name LIKE "%{search}%"' if search else ""
        query = (
            f"content query --uri content://contacts/phones "
            f"--projection display_name:number{where} "
            f"--sort display_name LIMIT {limit}"
        )
        out = _adb_shell(query, serial=self._s(), timeout=10)
        contacts = []
        for line in out.splitlines():
            if "display_name=" in line:
                m_name = re.search(r"display_name=([^,\n]+)", line)
                m_num  = re.search(r"number=([^,\n]+)", line)
                if m_name and m_num:
                    contacts.append({
                        "name": m_name.group(1).strip(),
                        "number": m_num.group(1).strip(),
                    })
        return contacts

    async def send_sms(self, to: str, message: str) -> str:
        cmd = (
            f'am start -a android.intent.action.SENDTO -d sms:{to} '
            f'--es sms_body "{message}" --ez exit_on_sent true'
        )
        _adb_shell(cmd, serial=self._s())
        return f"SMS ouvert vers {to} — confirme l'envoi sur le téléphone"

    # ── OCR ───────────────────────────────────────────────────────────────────

    async def ocr_screen(self, lang: str = "fra+eng") -> str:
        if not _OCR_AVAILABLE:
            raise RuntimeError("pytesseract non installé. Lance : pip install pytesseract Pillow")
        raw = await self.screenshot()
        loop = asyncio.get_event_loop()
        def _do_ocr():
            img = Image.open(io.BytesIO(raw))
            return pytesseract.image_to_string(img, lang=lang).strip()
        return await loop.run_in_executor(None, _do_ocr)

    async def find_by_image(self, template_b64: str, threshold: float = 0.8) -> dict:
        if not _CV2_AVAILABLE:
            raise RuntimeError("opencv-python-headless non installé")
        needle_bytes = base64.b64decode(template_b64)
        haystack_bytes = await self.screenshot()
        loop = asyncio.get_event_loop()
        def _do_match():
            hay_arr = np.frombuffer(haystack_bytes, np.uint8)
            ndl_arr = np.frombuffer(needle_bytes, np.uint8)
            haystack = cv2.imdecode(hay_arr, cv2.IMREAD_COLOR)
            needle = cv2.imdecode(ndl_arr, cv2.IMREAD_COLOR)
            if haystack is None or needle is None:
                return None
            result = cv2.matchTemplate(haystack, needle, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)
            if max_val < threshold:
                return None
            h, w = needle.shape[:2]
            cx = max_loc[0] + w // 2
            cy = max_loc[1] + h // 2
            return {"x": cx, "y": cy, "w": w, "h": h, "score": float(max_val)}
        match = await loop.run_in_executor(None, _do_match)
        if match is None:
            return {"found": False, "error": "Template non trouvé"}
        return {"found": True, **match}

    # ── Auto setup (première utilisation) ─────────────────────────────────────

    async def auto_setup(self) -> list[dict]:
        """Configure automatiquement le device (permissions ADB)."""
        steps = []

        def _step(desc: str, cmd: str, timeout: int = 5) -> None:
            rc, out, err = _adb("shell", cmd, serial=self._s(), timeout=timeout)
            steps.append({"desc": desc, "ok": rc == 0, "output": out or err})

        # Initialisation uiautomator2
        if _U2_AVAILABLE:
            try:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, lambda: u2.connect(self._s()).healthcheck())
                steps.append({"desc": "uiautomator2 ATX agent", "ok": True})
            except Exception as e:
                steps.append({"desc": f"uiautomator2 ATX agent : {e}", "ok": False})
        else:
            steps.append({"desc": "uiautomator2 non installé — pip install uiautomator2", "ok": False})

        # Désactiver les animations (améliore fiabilité des tests)
        for anim_key in ["window_animation_scale", "transition_animation_scale", "animator_duration_scale"]:
            _step(
                f"Animation {anim_key} désactivée",
                f"settings put global {anim_key} 0",
            )

        # Stay awake
        _step("Stay awake activé", "settings put global stay_on_while_plugged_in 3")

        return steps
