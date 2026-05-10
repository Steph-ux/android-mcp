"""
Android MCP — Serveur MCP (server.py)
======================================
7 outils catégoriels couvrant l'ensemble du contrôle Android.

    android_device     → gestion des devices (connexion, sélection, info)
    android_screen     → capture, OCR, stream, template matching
    android_interact   → touch, clavier, navigation UI (find, wait, scroll)
    android_app        → applications, intents, settings
    android_files      → push/pull de fichiers
    android_system     → shell, logs, batterie, réseau, capteurs, SMS, contacts
    android_automation → macros et batch

Convention d'appel :
    android_xxx(action="nom_action", params={"param1": val1, ...}, device_id="serial")

Tous les `device_id` sont optionnels (utilise le device sélectionné par défaut).
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional, Union

from mcp.server import FastMCP
from mcp.types import ImageContent, TextContent

# ─── Config ───────────────────────────────────────────────────────────────────
_ROOT = Path(__file__).parent
_env_file = _ROOT / ".env"
if _env_file.exists():
    with open(_env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

mcp = FastMCP("android-mcp")

from device_manager import get_manager
_dm = get_manager()

# ─── Macros ───────────────────────────────────────────────────────────────────
_MACROS_FILE = _ROOT / "macros.json"
_macros: dict[str, list[dict]] = {}
_current_macro: list[dict] = []
_current_macro_name: Optional[str] = None


def _load_macros():
    global _macros
    if _MACROS_FILE.exists():
        try:
            _macros = json.loads(_MACROS_FILE.read_text(encoding="utf-8"))
        except Exception:
            _macros = {}


def _save_macros():
    _MACROS_FILE.write_text(
        json.dumps(_macros, ensure_ascii=False, indent=2), encoding="utf-8"
    )


_load_macros()

# ─── Helpers ──────────────────────────────────────────────────────────────────

def _b(device_id: Optional[str] = None):
    return _dm.get_backend(device_id)


def _ok(**kw) -> str:
    return json.dumps({"success": True, **kw}, ensure_ascii=False)


def _err(msg: str) -> str:
    return json.dumps({"success": False, "error": msg}, ensure_ascii=False)


def _p(params: Optional[dict], *keys):
    """Extrait plusieurs clés d'un dict params (retourne None si absent)."""
    d = params or {}
    if len(keys) == 1:
        return d.get(keys[0])
    return tuple(d.get(k) for k in keys)


# ══════════════════════════════════════════════════════════════════════════════
# OUTIL 1 — android_device
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
async def android_device(
    action: str,
    params: Optional[dict] = None,
    device_id: Optional[str] = None,
) -> str:
    """Gestion des devices Android (connexion, sélection, informations).

    Actions disponibles :

    • list
        Retourne tous les devices connectés (USB, WiFi ADB, émulateurs, companion).
        params: {}

    • select
        Sélectionne le device cible par défaut pour les commandes suivantes.
        params: {"serial": "emulator-5554" | "192.168.1.10:5555" | "R9JN4..."}

    • connect
        Connecte un device via WiFi ADB (adb connect host:port).
        params: {"host": "192.168.1.10", "port": 5555}

    • disconnect
        Déconnecte un device WiFi ADB.
        params: {"host": "192.168.1.10", "port": 5555}  (vide = device sélectionné)

    • info
        Modèle, version Android, résolution, densité, transport.
        params: {}

    • status
        Vérifie si le device est connecté et prêt.
        params: {}

    • setup
        Configuration automatique : initialise l'agent ATX (uiautomator2),
        désactive les animations, active stay-awake.
        params: {}
    """
    p = params or {}
    try:
        if action == "list":
            devices = _dm.list_devices()
            return json.dumps({"success": True, "devices": devices, "count": len(devices)})

        if action == "select":
            serial = p.get("serial", "")
            if not serial:
                return _err("params.serial requis")
            return _ok(**_dm.select_device(serial))

        if action == "connect":
            host = p.get("host", "")
            if not host:
                return _err("params.host requis")
            return json.dumps(_dm.connect_wifi_adb(host, int(p.get("port", 5555))))

        if action == "disconnect":
            host = p.get("host", "")
            if host:
                return json.dumps(_dm.disconnect_wifi_adb(host, int(p.get("port", 5555))))
            serial = _dm.get_selected_serial()
            if ":" in serial:
                ip, port = serial.rsplit(":", 1)
                return json.dumps(_dm.disconnect_wifi_adb(ip, int(port)))
            return _err("Aucun device WiFi sélectionné")

        if action == "info":
            return json.dumps({"success": True, "data": _dm.get_device_info(device_id)})

        if action == "status":
            info = _dm.get_device_info(device_id)
            return json.dumps({"success": True, "connected": "error" not in info, "data": info})

        if action == "setup":
            b = _b(device_id)
            steps = await b.auto_setup()
            return json.dumps({"success": all(s.get("ok") for s in steps), "steps": steps})

        return _err(f"Action inconnue : '{action}'. Valides : list, select, connect, disconnect, info, status, setup")

    except Exception as e:
        return _err(str(e))


# ══════════════════════════════════════════════════════════════════════════════
# OUTIL 2 — android_screen
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
async def android_screen(
    action: str,
    params: Optional[dict] = None,
    device_id: Optional[str] = None,
) -> Union[str, list]:
    """Capture d'écran, OCR, stream vidéo et recherche visuelle.

    Actions disponibles :

    • screenshot
        Capture l'écran complet en PNG (bypass FLAG_SECURE via ADB).
        params: {}
        → retourne une image PNG

    • region
        Capture une zone précise de l'écran.
        params: {"x": int, "y": int, "width": int, "height": int}
        → retourne une image PNG

    • size
        Résolution de l'écran (largeur × hauteur).
        params: {}

    • is_on
        Vérifie si l'écran est allumé.
        params: {}

    • wake
        Allume l'écran s'il est éteint.
        params: {}

    • start_stream
        Démarre le stream live (ADB bypass, ~16fps).
        params: {}

    • stop_stream
        Arrête le stream live.
        params: {}

    • live_frame
        Retourne le dernier frame du stream (ou capture one-shot).
        params: {}
        → retourne une image PNG/JPEG

    • ocr
        Extrait tout le texte visible via Tesseract OCR.
        params: {"lang": "fra+eng"}  (défaut: "fra+eng")

    • find_image
        Cherche une image (template) dans l'écran via template matching OpenCV.
        params: {"template_b64": "<PNG base64>", "threshold": 0.8}
        → retourne {"found": bool, "x": int, "y": int, "w": int, "h": int, "score": float}

    • viewer
        Lance le viewer live scrcpy (fenêtre interactive 90fps sur le PC).
        Clic = tap, glisser = swipe, clic droit = BACK, scroll = scroll.
        params: {"fps": 90, "bitrate": "8M", "no_control": false}
    """
    p = params or {}
    try:
        b = _b(device_id)

        if action == "screenshot":
            raw = await b.screenshot()
            return [ImageContent(type="image", data=base64.b64encode(raw).decode(), mimeType="image/png")]

        if action == "region":
            x, y = int(p.get("x", 0)), int(p.get("y", 0))
            w, h = int(p.get("width", 200)), int(p.get("height", 200))
            raw = await b.screenshot_region(x, y, w, h)
            return [ImageContent(type="image", data=base64.b64encode(raw).decode(), mimeType="image/png")]

        if action == "size":
            return _ok(data=await b.get_screen_size())

        if action == "is_on":
            return _ok(data=await b.is_screen_on())

        if action == "wake":
            await b.wake_screen()
            return _ok()

        if action == "start_stream":
            return json.dumps(await b.start_stream())

        if action == "stop_stream":
            await b.stop_stream()
            return _ok()

        if action == "live_frame":
            result = await b.get_live_frame()
            if result.get("success") and result.get("data"):
                mime = result.get("mime", "image/png")
                return [ImageContent(type="image", data=result["data"], mimeType=mime)]
            return [TextContent(type="text", text=json.dumps(result))]

        if action == "ocr":
            text = await b.ocr_screen(p.get("lang", "fra+eng"))
            return _ok(data=text)

        if action == "find_image":
            tpl = p.get("template_b64", "")
            if not tpl:
                return _err("params.template_b64 requis")
            match = await b.find_by_image(tpl, float(p.get("threshold", 0.8)))
            return json.dumps({"success": match.get("found", False), **match})

        if action == "viewer":
            viewer_py = _ROOT / "viewer.py"
            if not viewer_py.exists():
                return _err("viewer.py introuvable — vérifie l'installation d'android-mcp")
            cmd = [sys.executable, str(viewer_py)]
            fps = p.get("fps", 90)
            bitrate = p.get("bitrate", "8M")
            if fps != 90:
                cmd += ["--fps", str(fps)]
            if bitrate != "8M":
                cmd += ["--bitrate", str(bitrate)]
            if p.get("no_control"):
                cmd += ["--no-control"]
            if device_id:
                cmd += ["--device", device_id]
            proc = subprocess.Popen(cmd)
            return _ok(pid=proc.pid, fps=fps, bitrate=bitrate,
                       message=f"Viewer lancé (PID {proc.pid}) — ferme la fenêtre scrcpy pour arrêter")

        return _err(
            f"Action inconnue : '{action}'. "
            "Valides : screenshot, region, size, is_on, wake, start_stream, stop_stream, live_frame, ocr, find_image, viewer"
        )

    except Exception as e:
        if action in ("screenshot", "region", "live_frame"):
            return [TextContent(type="text", text=_err(str(e)))]
        return _err(str(e))


# ══════════════════════════════════════════════════════════════════════════════
# OUTIL 3 — android_interact
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
async def android_interact(
    action: str,
    params: Optional[dict] = None,
    device_id: Optional[str] = None,
) -> str:
    """Interactions tactiles, saisie clavier et navigation UI.

    ── TOUCH ──────────────────────────────────────────────────────────────────
    • tap
        params: {"x": float, "y": float}

    • double_tap
        params: {"x": float, "y": float}

    • long_press
        params: {"x": float, "y": float, "duration_ms": 800}

    • swipe
        params: {"x1": float, "y1": float, "x2": float, "y2": float, "duration_ms": 300}

    • drag
        params: {"x1": float, "y1": float, "x2": float, "y2": float, "duration_ms": 1000}

    • pinch
        Zoom avant (scale > 1) ou arrière (scale < 1).
        params: {"x": float, "y": float, "scale": float, "duration_ms": 500}

    • multi_touch
        Gestes multi-doigts simultanés.
        params: {"points": [{"x": int, "y": int, "start_ms": int, "end_ms": int}, ...]}

    ── CLAVIER ────────────────────────────────────────────────────────────────
    • type
        Saisit du texte dans le champ actif.
        params: {"text": str}

    • clear
        Efface le contenu du champ actif (Ctrl+A + Suppr).
        params: {}

    • submit
        Saisit du texte et appuie sur Entrée.
        params: {"text": str}

    • key
        Appuie sur une touche système.
        params: {"key": "BACK" | "HOME" | "RECENTS" | "VOLUME_UP" | "VOLUME_DOWN" |
                        "ENTER" | "DEL" | "TAB" | "NOTIFICATIONS" | <keycode int>}

    • combo
        Envoie une séquence de keycodes Android.
        params: {"keys": [int, ...]}

    ── NAVIGATION UI (uiautomator2) ───────────────────────────────────────────
    • hierarchy
        Retourne le XML complet de l'interface (IDs, textes, positions).
        params: {}

    • find
        Cherche un élément par texte et le tape.
        params: {"text": str, "partial_match": true}

    • wait
        Attend qu'un élément UI apparaisse.
        params: {"text": str, "timeout": 10, "partial_match": true}

    • scroll
        Scrolle jusqu'à ce qu'un élément soit visible.
        params: {"text": str, "direction": "down" | "up", "max_swipes": 5}

    • assert
        Vérifie qu'un texte est visible à l'écran.
        params: {"text": str, "partial_match": true}
    """
    p = params or {}
    try:
        b = _b(device_id)

        # ── Touch ──
        if action == "tap":
            await b.tap(float(p.get("x", 0)), float(p.get("y", 0)))
            return _ok()

        if action == "double_tap":
            await b.double_tap(float(p.get("x", 0)), float(p.get("y", 0)))
            return _ok()

        if action == "long_press":
            await b.long_press(float(p.get("x", 0)), float(p.get("y", 0)), int(p.get("duration_ms", 800)))
            return _ok()

        if action == "swipe":
            await b.swipe(
                float(p.get("x1", 0)), float(p.get("y1", 0)),
                float(p.get("x2", 0)), float(p.get("y2", 0)),
                int(p.get("duration_ms", 300)),
            )
            return _ok()

        if action == "drag":
            await b.drag_and_drop(
                float(p.get("x1", 0)), float(p.get("y1", 0)),
                float(p.get("x2", 0)), float(p.get("y2", 0)),
                int(p.get("duration_ms", 1000)),
            )
            return _ok()

        if action == "pinch":
            await b.pinch_zoom(
                float(p.get("x", 0)), float(p.get("y", 0)),
                float(p.get("scale", 1.5)), int(p.get("duration_ms", 500)),
            )
            return _ok()

        if action == "multi_touch":
            points = p.get("points", [])
            if not points:
                return _err("params.points requis")
            await b.multi_touch(points)
            return _ok()

        # ── Clavier ──
        if action == "type":
            text = p.get("text", "")
            if text == "":
                return _err("params.text requis")
            await b.input_text(text)
            return _ok()

        if action == "clear":
            await b.clear_field()
            return _ok()

        if action == "submit":
            text = p.get("text", "")
            if text == "":
                return _err("params.text requis")
            await b.type_and_submit(text)
            return _ok()

        if action == "key":
            key = p.get("key", "")
            if not key:
                return _err("params.key requis (ex: 'BACK', 'HOME', 'ENTER')")
            await b.press_key(str(key))
            return _ok()

        if action == "combo":
            keys = p.get("keys", [])
            if not keys:
                return _err("params.keys requis (liste de keycodes)")
            await b.key_combo(keys)
            return _ok()

        # ── Navigation UI ──
        if action == "hierarchy":
            xml = await b.get_ui_hierarchy()
            return _ok(data=xml)

        if action == "find":
            text = p.get("text", "")
            if not text:
                return _err("params.text requis")
            found = await b.find_and_tap(text, bool(p.get("partial_match", True)))
            return json.dumps({"success": True, "found": found})

        if action == "wait":
            text = p.get("text", "")
            if not text:
                return _err("params.text requis")
            found = await b.wait_for_element(
                text, int(p.get("timeout", 10)), bool(p.get("partial_match", True))
            )
            return json.dumps({"success": True, "found": found})

        if action == "scroll":
            text = p.get("text", "")
            if not text:
                return _err("params.text requis")
            found = await b.scroll_to_element(
                text, p.get("direction", "down"), int(p.get("max_swipes", 5))
            )
            return json.dumps({"success": True, "found": found})

        if action == "assert":
            text = p.get("text", "")
            if not text:
                return _err("params.text requis")
            visible = await b.assert_visible(text, bool(p.get("partial_match", True)))
            return json.dumps({"success": True, "visible": visible})

        return _err(
            f"Action inconnue : '{action}'. "
            "Valides : tap, double_tap, long_press, swipe, drag, pinch, multi_touch, "
            "type, clear, submit, key, combo, hierarchy, find, wait, scroll, assert"
        )

    except Exception as e:
        return _err(str(e))


# ══════════════════════════════════════════════════════════════════════════════
# OUTIL 4 — android_app
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
async def android_app(
    action: str,
    params: Optional[dict] = None,
    device_id: Optional[str] = None,
) -> str:
    """Gestion des applications Android : lancement, installation, intents, paramètres.

    Actions disponibles :

    • launch
        Lance une application par son package.
        params: {"package": "com.whatsapp"}

    • close
        Force-stop une application.
        params: {"package": "com.whatsapp"}

    • list
        Liste les applications installées.
        params: {"include_system": false}

    • install
        Installe un APK depuis le PC.
        params: {"apk_path": "C:/chemin/vers/app.apk"}

    • uninstall
        Désinstalle une application.
        params: {"package": "com.example.app"}

    • current
        Retourne le package de l'application au premier plan.
        params: {}

    • url
        Ouvre une URL dans le navigateur ou l'app appropriée.
        params: {"url": "https://example.com" | "tel:+33612345678"}

    • intent
        Envoie un Intent Android personnalisé.
        params: {"action": "android.intent.action.VIEW",
                 "uri": "...",          (optionnel)
                 "package": "...",      (optionnel)
                 "extras": {"key": val} (optionnel)}

    • settings
        Ouvre les paramètres système.
        params: {"section": "main" | "wifi" | "bluetooth" | "display" |
                             "sound" | "apps" | "accessibility" | "battery" |
                             "storage" | "developer"}
    """
    p = params or {}
    try:
        b = _b(device_id)

        if action == "launch":
            pkg = p.get("package", "")
            if not pkg:
                return _err("params.package requis")
            await b.launch_app(pkg)
            return _ok()

        if action == "close":
            pkg = p.get("package", "")
            if not pkg:
                return _err("params.package requis")
            await b.close_app(pkg)
            return _ok()

        if action == "list":
            apps = await b.list_apps(bool(p.get("include_system", False)))
            return _ok(data=apps, count=len(apps))

        if action == "install":
            apk = p.get("apk_path", "")
            if not apk:
                return _err("params.apk_path requis")
            return json.dumps(await b.install_app(apk))

        if action == "uninstall":
            pkg = p.get("package", "")
            if not pkg:
                return _err("params.package requis")
            return json.dumps(await b.uninstall_app(pkg))

        if action == "current":
            return _ok(data=await b.get_current_app())

        if action == "url":
            url = p.get("url", "")
            if not url:
                return _err("params.url requis")
            await b.open_url(url)
            return _ok()

        if action == "intent":
            act = p.get("action", "")
            if not act:
                return _err("params.action requis")
            await b.send_intent(act, p.get("uri", ""), p.get("package", ""), p.get("extras"))
            return _ok()

        if action == "settings":
            await b.open_settings(p.get("section", "main"))
            return _ok()

        return _err(
            f"Action inconnue : '{action}'. "
            "Valides : launch, close, list, install, uninstall, current, url, intent, settings"
        )

    except Exception as e:
        return _err(str(e))


# ══════════════════════════════════════════════════════════════════════════════
# OUTIL 5 — android_files
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
async def android_files(
    action: str,
    params: Optional[dict] = None,
    device_id: Optional[str] = None,
) -> str:
    """Transfert et liste de fichiers entre le PC et le téléphone.

    Actions disponibles :

    • push
        Envoie un fichier du PC vers le téléphone.
        params: {"local_path": "C:/fichier.txt", "remote_path": "/sdcard/Download/fichier.txt"}

    • push_b64
        Envoie un fichier encodé en base64 vers le téléphone.
        params: {"remote_path": "/sdcard/Download/fichier.txt", "data": "<base64>"}

    • pull
        Récupère un fichier du téléphone vers le PC.
        params: {"remote_path": "/sdcard/Download/fichier.txt", "local_path": "C:/dest.txt"}

    • pull_b64
        Récupère un fichier du téléphone (retourne le contenu en base64).
        params: {"remote_path": "/sdcard/Download/fichier.txt"}

    • list
        Liste le contenu d'un répertoire sur le téléphone.
        params: {"directory": "/sdcard/Download"}
    """
    p = params or {}
    try:
        b = _b(device_id)

        if action == "push":
            lp, rp = p.get("local_path", ""), p.get("remote_path", "")
            if not lp or not rp:
                return _err("params.local_path et params.remote_path requis")
            return json.dumps(await b.push_file(lp, rp))

        if action == "push_b64":
            rp, data = p.get("remote_path", ""), p.get("data", "")
            if not rp or not data:
                return _err("params.remote_path et params.data requis")
            await b.push_file_b64(rp, data)
            return _ok()

        if action == "pull":
            rp, lp = p.get("remote_path", ""), p.get("local_path", "")
            if not rp or not lp:
                return _err("params.remote_path et params.local_path requis")
            return json.dumps(await b.pull_file(rp, lp))

        if action == "pull_b64":
            rp = p.get("remote_path", "")
            if not rp:
                return _err("params.remote_path requis")
            return _ok(data=await b.pull_file_b64(rp))

        if action == "list":
            directory = p.get("directory", "/sdcard")
            entries = await b.list_files(directory)
            return _ok(data=entries, count=len(entries))

        return _err(
            f"Action inconnue : '{action}'. Valides : push, push_b64, pull, pull_b64, list"
        )

    except Exception as e:
        return _err(str(e))


# ══════════════════════════════════════════════════════════════════════════════
# OUTIL 6 — android_system
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
async def android_system(
    action: str,
    params: Optional[dict] = None,
    device_id: Optional[str] = None,
) -> str:
    """Système, capteurs, réseau, et communications du téléphone.

    ── SYSTÈME ────────────────────────────────────────────────────────────────
    • shell
        Exécute une commande shell sur le téléphone.
        params: {"command": "pm list packages", "timeout": 30}

    • logs
        Récupère les logs logcat.
        params: {"lines": 100, "package": "com.example.app"}

    • battery
        Niveau de batterie et état de charge.
        params: {}

    • clipboard_get
        Lit le presse-papier.
        params: {}

    • clipboard_set
        Définit le presse-papier.
        params: {"text": "contenu"}

    • volume
        Règle le volume.
        params: {"level": 50, "stream": "music" | "ring" | "alarm" | "notification"}

    • rotation
        Définit la rotation de l'écran.
        params: {"rotation": 0 | 1 | 2 | 3}
                (0=portrait, 1=paysage gauche, 2=portrait inversé, 3=paysage droit)

    • wifi
        Active/désactive le WiFi.
        params: {"enabled": true | false}

    • bluetooth
        Active/désactive le Bluetooth.
        params: {"enabled": true | false}

    • mobile_data
        Active/désactive la data mobile.
        params: {"enabled": true | false}

    • notifications
        Retourne les notifications actives.
        params: {}

    ── CAPTEURS & RÉSEAU ──────────────────────────────────────────────────────
    • gps
        Définit une position GPS fictive.
        params: {"lat": 48.8566, "lng": 2.3522}

    • sensors
        Lit les données des capteurs.
        params: {"sensor": "all" | "accelerometer" | "gyroscope" |
                            "proximity" | "light" | "pressure" | "magnetic"}

    • wifi_list
        Liste les réseaux WiFi disponibles.
        params: {}

    • wifi_connect
        Connecte le téléphone à un réseau WiFi.
        params: {"ssid": "MonReseau", "password": "motdepasse"}

    ── COMMUNICATIONS ─────────────────────────────────────────────────────────
    • contacts
        Lit les contacts du téléphone.
        params: {"search": "nom_filtre", "limit": 20}

    • sms
        Ouvre l'app SMS pré-remplie (l'envoi doit être confirmé sur le téléphone).
        params: {"to": "+33612345678", "message": "Bonjour !"}
    """
    p = params or {}
    try:
        b = _b(device_id)

        # ── Système ──
        if action == "shell":
            cmd = p.get("command", "")
            if not cmd:
                return _err("params.command requis")
            out = await b.shell_exec(cmd, int(p.get("timeout", 30)))
            return _ok(data=out)

        if action == "logs":
            logs = await b.get_logs(int(p.get("lines", 100)), p.get("package", ""))
            return _ok(data=logs)

        if action == "battery":
            return _ok(data=await b.get_battery())

        if action == "clipboard_get":
            return _ok(data=await b.get_clipboard())

        if action == "clipboard_set":
            text = p.get("text", "")
            if text == "":
                return _err("params.text requis")
            await b.set_clipboard(text)
            return _ok()

        if action == "volume":
            level = p.get("level")
            if level is None:
                return _err("params.level requis (0-100)")
            await b.set_volume(int(level), p.get("stream", "music"))
            return _ok()

        if action == "rotation":
            rotation = p.get("rotation")
            if rotation is None:
                return _err("params.rotation requis (0-3)")
            await b.set_rotation(int(rotation))
            return _ok()

        if action == "wifi":
            enabled = p.get("enabled")
            if enabled is None:
                return _err("params.enabled requis (true/false)")
            await b.toggle_wifi(bool(enabled))
            return _ok()

        if action == "bluetooth":
            enabled = p.get("enabled")
            if enabled is None:
                return _err("params.enabled requis (true/false)")
            await b.toggle_bluetooth(bool(enabled))
            return _ok()

        if action == "mobile_data":
            await b.enable_mobile_data(bool(p.get("enabled", True)))
            return _ok()

        if action == "notifications":
            notifs = await b.read_notifications()
            return _ok(data=notifs, count=len(notifs))

        # ── Capteurs & Réseau ──
        if action == "gps":
            lat, lng = p.get("lat"), p.get("lng")
            if lat is None or lng is None:
                return _err("params.lat et params.lng requis")
            await b.mock_gps(float(lat), float(lng))
            return _ok()

        if action == "sensors":
            data = await b.get_sensor_data(p.get("sensor", "all"))
            return _ok(data=data)

        if action == "wifi_list":
            networks = await b.get_wifi_list()
            return _ok(data=networks, count=len(networks))

        if action == "wifi_connect":
            ssid = p.get("ssid", "")
            if not ssid:
                return _err("params.ssid requis")
            return json.dumps(await b.connect_wifi(ssid, p.get("password", "")))

        # ── Communications ──
        if action == "contacts":
            contacts = await b.get_contacts(p.get("search", ""), int(p.get("limit", 20)))
            return _ok(data=contacts, count=len(contacts))

        if action == "sms":
            to, msg = p.get("to", ""), p.get("message", "")
            if not to or not msg:
                return _err("params.to et params.message requis")
            result = await b.send_sms(to, msg)
            return _ok(data=result)

        return _err(
            f"Action inconnue : '{action}'. "
            "Valides : shell, logs, battery, clipboard_get, clipboard_set, volume, rotation, "
            "wifi, bluetooth, mobile_data, notifications, gps, sensors, wifi_list, wifi_connect, "
            "contacts, sms"
        )

    except Exception as e:
        return _err(str(e))


# ══════════════════════════════════════════════════════════════════════════════
# OUTIL 7 — android_automation
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
async def android_automation(
    action: str,
    params: Optional[dict] = None,
    device_id: Optional[str] = None,
) -> str:
    """Automatisation : exécution en lot et macros enregistrables/rejouables.

    ── BATCH ──────────────────────────────────────────────────────────────────
    • batch
        Exécute N actions en un seul appel (réduit la latence).
        params: {
            "actions": [
                {"action": "tap",       "x": 100, "y": 200},
                {"action": "type",      "text": "hello"},
                {"action": "key",       "key": "ENTER"},
                {"action": "screenshot"},
                ...
            ],
            "stop_on_error": false
        }
        Les noms d'action correspondent aux actions de android_interact et android_screen.

    ── MACROS ─────────────────────────────────────────────────────────────────
    • macro_start
        Démarre l'enregistrement d'une nouvelle macro.
        params: {"name": "login_whatsapp"}

    • macro_record
        Ajoute une action à la macro en cours d'enregistrement.
        params: {"action": "tap", "x": 500, "y": 300}
        (ou n'importe quelle action avec ses params à plat)

    • macro_stop
        Arrête l'enregistrement et sauvegarde la macro sur disque.
        params: {}

    • macro_replay
        Rejoue une macro enregistrée.
        params: {"name": "login_whatsapp", "delay_ms": 500}

    • macro_list
        Liste toutes les macros sauvegardées.
        params: {}

    • macro_delete
        Supprime une macro.
        params: {"name": "login_whatsapp"}
    """
    global _current_macro, _current_macro_name, _macros
    p = params or {}

    try:
        if action == "batch":
            actions = p.get("actions", [])
            if not actions:
                return _err("params.actions requis (liste d'actions)")
            stop_on_error = bool(p.get("stop_on_error", False))
            b = _b(device_id)

            _dispatch = {
                "tap":          lambda a: b.tap(float(a.get("x", 0)), float(a.get("y", 0))),
                "double_tap":   lambda a: b.double_tap(float(a.get("x", 0)), float(a.get("y", 0))),
                "long_press":   lambda a: b.long_press(float(a.get("x", 0)), float(a.get("y", 0)), int(a.get("duration_ms", 800))),
                "swipe":        lambda a: b.swipe(float(a.get("x1", 0)), float(a.get("y1", 0)), float(a.get("x2", 0)), float(a.get("y2", 0)), int(a.get("duration_ms", 300))),
                "drag":         lambda a: b.drag_and_drop(float(a.get("x1", 0)), float(a.get("y1", 0)), float(a.get("x2", 0)), float(a.get("y2", 0)), int(a.get("duration_ms", 1000))),
                "type":         lambda a: b.input_text(a.get("text", "")),
                "clear":        lambda a: b.clear_field(),
                "submit":       lambda a: b.type_and_submit(a.get("text", "")),
                "key":          lambda a: b.press_key(str(a.get("key", "BACK"))),
                "combo":        lambda a: b.key_combo(a.get("keys", [])),
                "screenshot":   lambda a: b.screenshot(),
                "hierarchy":    lambda a: b.get_ui_hierarchy(),
                "find":         lambda a: b.find_and_tap(a.get("text", ""), bool(a.get("partial_match", True))),
                "wait":         lambda a: b.wait_for_element(a.get("text", ""), int(a.get("timeout", 10)), bool(a.get("partial_match", True))),
                "shell":        lambda a: b.shell_exec(a.get("command", "")),
                "launch":       lambda a: b.launch_app(a.get("package", "")),
                "close":        lambda a: b.close_app(a.get("package", "")),
            }

            results = []
            for i, act in enumerate(actions):
                act_name = act.get("action", "")
                try:
                    handler = _dispatch.get(act_name)
                    if handler is None:
                        res = {"success": False, "error": f"Action inconnue : {act_name}"}
                    else:
                        raw = await handler(act)
                        if isinstance(raw, bytes):
                            res = {"success": True, "data": base64.b64encode(raw).decode(), "mime": "image/png"}
                        elif isinstance(raw, bool):
                            res = {"success": True, "data": raw}
                        elif raw is None:
                            res = {"success": True}
                        else:
                            res = {"success": True, "data": raw if isinstance(raw, (dict, list)) else str(raw)}
                    results.append(res)
                    if stop_on_error and not res.get("success", True):
                        break
                except Exception as e:
                    results.append({"success": False, "error": str(e), "action": act_name})
                    if stop_on_error:
                        break

            return json.dumps({"success": True, "results": results, "count": len(results)})

        if action == "macro_start":
            name = p.get("name", "")
            if not name:
                return _err("params.name requis")
            _current_macro = []
            _current_macro_name = name
            return _ok(recording=name)

        if action == "macro_record":
            if _current_macro_name is None:
                return _err("Pas d'enregistrement en cours. Lance macro_start d'abord.")
            act_name = p.get("action", "")
            if not act_name:
                return _err("params.action requis")
            step_params = {k: v for k, v in p.items() if k != "action"}
            _current_macro.append({"action": act_name, "params": step_params})
            return _ok(recorded=len(_current_macro))

        if action == "macro_stop":
            if not _current_macro_name:
                return _err("Pas d'enregistrement en cours.")
            name = _current_macro_name
            _macros[name] = _current_macro.copy()
            _current_macro = []
            _current_macro_name = None
            _save_macros()
            return _ok(name=name, count=len(_macros[name]))

        if action == "macro_replay":
            name = p.get("name", "")
            if not name:
                return _err("params.name requis")
            if name not in _macros:
                return _err(f"Macro '{name}' introuvable. Disponibles : {list(_macros.keys())}")
            delay_ms = int(p.get("delay_ms", 500))
            steps = _macros[name]
            results = []
            for i, step in enumerate(steps):
                flat_action = {"action": step["action"], **step.get("params", {})}
                r = await android_automation(
                    "batch", {"actions": [flat_action], "stop_on_error": False}, device_id
                )
                parsed = json.loads(r)
                results.append(parsed.get("results", [{}])[0] if parsed.get("results") else parsed)
                if i < len(steps) - 1:
                    await asyncio.sleep(delay_ms / 1000)
            return _ok(name=name, executed=len(results), results=results)

        if action == "macro_list":
            return _ok(data={k: len(v) for k, v in _macros.items()}, count=len(_macros))

        if action == "macro_delete":
            name = p.get("name", "")
            if not name:
                return _err("params.name requis")
            if name not in _macros:
                return _err(f"Macro '{name}' introuvable.")
            _macros.pop(name)
            _save_macros()
            return _ok(deleted=name)

        return _err(
            f"Action inconnue : '{action}'. "
            "Valides : batch, macro_start, macro_record, macro_stop, macro_replay, macro_list, macro_delete"
        )

    except Exception as e:
        return _err(str(e))


# ── Point d'entrée ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
