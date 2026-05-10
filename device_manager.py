"""
device_manager.py — Gestionnaire multi-device Android MCP
==========================================================
Gère la sélection, la connexion et le routage vers les devices Android.

Priorité backend :
  1. ADB (adb_backend) — si le device est visible via ADB
  2. Companion (companion_backend) — si l'app Flutter est connectée en WebSocket

Usage :
  from device_manager import DeviceManager
  dm = DeviceManager()
  devices = dm.list_devices()       # → [{"serial": "emulator-5554", ...}, ...]
  dm.select_device("emulator-5554") # → fixe le device par défaut
  backend = dm.get_backend()        # → AdbBackend ou CompanionBackend
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).parent

_env_file = _ROOT / ".env"
if _env_file.exists():
    with open(_env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                import os
                os.environ.setdefault(k.strip(), v.strip())

import os

DEFAULT_DEVICE_SERIAL = os.environ.get("ADB_DEFAULT_SERIAL", "")


# ─── Helpers ADB bas niveau ────────────────────────────────────────────────────

def _run_adb(*args: str, timeout: int = 10) -> tuple[int, str, str]:
    """Lance une commande adb et retourne (returncode, stdout, stderr)."""
    try:
        r = subprocess.run(
            ["adb", *args],
            capture_output=True, text=True, timeout=timeout,
        )
        return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()
    except FileNotFoundError:
        return -1, "", "adb non trouvé dans le PATH"
    except subprocess.TimeoutExpired:
        return -2, "", "timeout"
    except Exception as e:
        return -3, "", str(e)


def _run_adb_device(serial: str, *args: str, timeout: int = 10) -> tuple[int, str, str]:
    """Lance une commande adb ciblant un device spécifique."""
    return _run_adb("-s", serial, *args, timeout=timeout)


# ─── DeviceInfo ────────────────────────────────────────────────────────────────

class DeviceInfo:
    def __init__(self, serial: str, state: str, transport: str = "usb"):
        self.serial = serial
        self.state = state          # "device", "offline", "unauthorized"
        self.transport = transport  # "usb", "wifi", "emulator"
        self.model: str = ""
        self.android_version: str = ""

    def is_ready(self) -> bool:
        return self.state == "device"

    def to_dict(self) -> dict:
        return {
            "serial": self.serial,
            "state": self.state,
            "transport": self.transport,
            "model": self.model,
            "android_version": self.android_version,
            "ready": self.is_ready(),
        }


# ─── DeviceManager ─────────────────────────────────────────────────────────────

class DeviceManager:
    """
    Gère la sélection et le routage multi-device.
    Un seul DeviceManager partagé pour tout le serveur MCP.
    """

    def __init__(self):
        self._selected_serial: str = DEFAULT_DEVICE_SERIAL
        self._adb_backend = None
        self._companion_backend = None

    # ── ADB availability ───────────────────────────────────────────────────────

    def adb_available(self) -> bool:
        rc, out, _ = _run_adb("version", timeout=3)
        return rc == 0

    # ── Device listing ─────────────────────────────────────────────────────────

    def list_devices(self) -> list[dict]:
        """
        Retourne la liste de tous les devices ADB connectés.
        Inclut emulateurs, USB et WiFi ADB.
        """
        rc, out, err = _run_adb("devices", "-l")
        if rc != 0:
            return [{"error": f"ADB indisponible : {err}"}]

        devices: list[DeviceInfo] = []
        for line in out.splitlines()[1:]:  # skip "List of devices attached"
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            serial, state = parts[0], parts[1]

            transport = "wifi" if ":" in serial else ("emulator" if serial.startswith("emulator") else "usb")
            info = DeviceInfo(serial=serial, state=state, transport=transport)

            # Lire modèle et version si device ready
            if state == "device":
                _, model, _ = _run_adb_device(serial, "shell", "getprop", "ro.product.model")
                _, brand, _ = _run_adb_device(serial, "shell", "getprop", "ro.product.brand")
                _, ver, _ = _run_adb_device(serial, "shell", "getprop", "ro.build.version.release")
                info.model = f"{brand.capitalize()} {model}".strip()
                info.android_version = f"Android {ver}"

            devices.append(info)

        # Ajouter les devices companion non ADB si connectés
        if self._companion_backend and self._companion_backend.connected:
            comp_serial = f"companion:{self._companion_backend.device_ip}"
            if not any(d.serial == comp_serial for d in devices):
                info = DeviceInfo(serial=comp_serial, state="device", transport="companion")
                info.model = self._companion_backend.device_ip or "Companion App"
                devices.append(info)

        return [d.to_dict() for d in devices]

    # ── Device selection ───────────────────────────────────────────────────────

    def select_device(self, serial: str) -> dict:
        """Sélectionne le device cible par défaut."""
        self._selected_serial = serial
        return {"selected": serial}

    def get_selected_serial(self, device_id: Optional[str] = None) -> str:
        """Retourne le serial à utiliser (paramètre > sélection > premier disponible)."""
        if device_id:
            return device_id
        if self._selected_serial:
            return self._selected_serial
        # Auto-select premier device disponible
        devices = self.list_devices()
        for d in devices:
            if d.get("ready") and not d.get("error"):
                return d["serial"]
        return ""

    # ── WiFi ADB connect ───────────────────────────────────────────────────────

    def connect_wifi_adb(self, host: str, port: int = 5555) -> dict:
        """Connecte un device via WiFi ADB (adb connect host:port)."""
        rc, out, err = _run_adb("connect", f"{host}:{port}", timeout=15)
        success = rc == 0 and ("connected" in out.lower() or "already connected" in out.lower())
        if success:
            self._selected_serial = f"{host}:{port}"
        return {"success": success, "output": out or err, "serial": f"{host}:{port}" if success else None}

    def disconnect_wifi_adb(self, host: str, port: int = 5555) -> dict:
        """Déconnecte un device WiFi ADB."""
        rc, out, err = _run_adb("disconnect", f"{host}:{port}", timeout=10)
        return {"success": rc == 0, "output": out or err}

    # ── Backend routing ────────────────────────────────────────────────────────

    def get_backend(self, device_id: Optional[str] = None):
        """
        Retourne le backend approprié pour le device demandé.
        Priorité : ADB si disponible, companion en fallback.
        """
        serial = self.get_selected_serial(device_id)

        # Si le serial est un device companion
        if serial.startswith("companion:"):
            if self._companion_backend and self._companion_backend.connected:
                return self._companion_backend
            raise ConnectionError("App compagnon non connectée.")

        # Vérifier si le device ADB est disponible
        if serial and self._is_adb_device_ready(serial):
            if self._adb_backend is None:
                from backends.adb_backend import AdbBackend
                self._adb_backend = AdbBackend()
            self._adb_backend.set_serial(serial)
            return self._adb_backend

        # Fallback companion
        if self._companion_backend and self._companion_backend.connected:
            return self._companion_backend

        # Dernier recours : ADB sans device spécifique
        if self.adb_available():
            if self._adb_backend is None:
                from backends.adb_backend import AdbBackend
                self._adb_backend = AdbBackend()
            self._adb_backend.set_serial(serial)
            return self._adb_backend

        raise ConnectionError(
            "Aucun device disponible. "
            "Connecte un téléphone via ADB (USB ou WiFi) ou démarre l'app compagnon."
        )

    def _is_adb_device_ready(self, serial: str) -> bool:
        if not serial:
            return self.adb_available()
        rc, out, _ = _run_adb_device(serial, "get-state", timeout=3)
        return rc == 0 and "device" in out

    # ── Companion backend registration ─────────────────────────────────────────

    def register_companion(self, companion_backend) -> None:
        """Appelé par relay.py quand l'app compagnon se connecte."""
        self._companion_backend = companion_backend

    def unregister_companion(self) -> None:
        """Appelé par relay.py quand l'app compagnon se déconnecte."""
        self._companion_backend = None

    # ── Device info ────────────────────────────────────────────────────────────

    def get_device_info(self, device_id: Optional[str] = None) -> dict:
        serial = self.get_selected_serial(device_id)
        if not serial or not self._is_adb_device_ready(serial):
            if self._companion_backend and self._companion_backend.connected:
                return {"serial": "companion", "transport": "companion", "ready": True}
            return {"error": "Aucun device disponible"}

        _, model, _ = _run_adb_device(serial, "shell", "getprop", "ro.product.model")
        _, brand, _ = _run_adb_device(serial, "shell", "getprop", "ro.product.brand")
        _, ver, _ = _run_adb_device(serial, "shell", "getprop", "ro.build.version.release")
        _, sdk, _ = _run_adb_device(serial, "shell", "getprop", "ro.build.version.sdk")
        _, res, _ = _run_adb_device(serial, "shell", "wm", "size")
        _, dpi, _ = _run_adb_device(serial, "shell", "wm", "density")

        transport = "wifi" if ":" in serial else ("emulator" if serial.startswith("emulator") else "usb")

        return {
            "serial": serial,
            "transport": transport,
            "model": f"{brand.capitalize()} {model}".strip(),
            "android_version": f"Android {ver} (SDK {sdk})",
            "resolution": res.replace("Physical size:", "").strip(),
            "density": dpi.replace("Physical density:", "").strip(),
            "ready": True,
        }


# ─── Singleton global ──────────────────────────────────────────────────────────

_manager: Optional[DeviceManager] = None


def get_manager() -> DeviceManager:
    global _manager
    if _manager is None:
        _manager = DeviceManager()
    return _manager
