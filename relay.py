"""
Android MCP — Relay Daemon (relay.py)
======================================
⚠️  LEGACY — conservé uniquement pour le backend Companion (AppCompagnon Flutter).

Pour un usage normal via ADB direct, utiliser server.py + backends/adb_backend.py.
relay.py n'est utile que si :
  - l'app compagnon Flutter est installée sur le téléphone
  - ADB n'est pas disponible (réseau sans accès ADB direct)

Architecture companion (fallback uniquement) :
  téléphone ←→ WebSocket :8765 ←→ relay.py ←→ HTTP :8090/command ←→ server.py

Architecture principale (recommandée) :
  server.py → device_manager → backends/adb_backend.py → ADB → téléphone

Mode stream ADB (bypass FLAG_SECURE — jeux protégés) :
  relay.py → adb exec-out screencap -p → SurfaceFlinger kernel → frames PNG
  Viewer live : python viewer.py (scrcpy 90fps, nettement plus performant)
"""

import asyncio
import base64
import json
import logging
import logging.handlers
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

import websockets
from aiohttp import web

# ─── Config via .env ──────────────────────────────────────────────────────────
_ROOT = Path(__file__).parent

# Charger .env si présent
_env_file = _ROOT / ".env"
if _env_file.exists():
    with open(_env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

RELAY_PORT        = int(os.environ.get("RELAY_WS_PORT",   8765))
STREAM_RELAY_PORT = int(os.environ.get("STREAM_PORT",     8766))
HTTP_PORT         = int(os.environ.get("RELAY_HTTP_PORT", 8090))
BEACON_PORT       = int(os.environ.get("BEACON_PORT",     8764))
AUTH_TOKEN        = os.environ.get("ANDROID_MCP_TOKEN", "mcp-shared-secret-2026")
PROTOCOL_VERSION  = "1.0"
_LOG_LEVEL        = os.environ.get("LOG_LEVEL", "WARNING").upper()

# ─── Logging avec rotation ─────────────────────────────────────────────────────
_log_file     = _ROOT / "relay.log"
_err_log_file = _ROOT / "relay_err.log"

_rotating_handler = logging.handlers.RotatingFileHandler(
    _log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
)
_err_handler = logging.handlers.RotatingFileHandler(
    _err_log_file, maxBytes=10 * 1024 * 1024, backupCount=3, encoding="utf-8"
)
_err_handler.setLevel(logging.ERROR)

logging.basicConfig(
    level=getattr(logging, _LOG_LEVEL, logging.WARNING),
    format="%(asctime)s [relay] %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stderr), _rotating_handler, _err_handler],
)
logger = logging.getLogger("relay")

# ─── OCR & Vision (optionnel) ─────────────────────────────────────────────────
try:
    import pytesseract
    from PIL import Image
    import io as _io
    _OCR_AVAILABLE = True
    logger.info("Tesseract OCR disponible")
except ImportError:
    _OCR_AVAILABLE = False
    logger.warning("pytesseract/Pillow non installé — ocr_screen désactivé")

try:
    import cv2
    import numpy as np
    _CV2_AVAILABLE = True
    logger.info("OpenCV disponible")
except ImportError:
    _CV2_AVAILABLE = False
    logger.warning("opencv-python-headless non installé — find_by_image désactivé")

# FPS adaptatif pour ADB stream
_TARGET_FPS = 16
_MIN_SLEEP  = 0.02
_MAX_SLEEP  = 0.15

# ─── State global ──────────────────────────────────────────────────────────────
_latest_frame: bytes | None = None
_latest_frame_time: float   = 0.0
_latest_frame_mime: str     = "image/jpeg"
_stream_active: bool        = False
_viewer_ws_clients: set     = set()

_macros: dict[str, list[dict]] = {}
_current_macro: list[dict]     = []
_current_macro_name: str | None = None

_auto_reconnect_enabled = False

# ─── Persistance macros ────────────────────────────────────────────────────────
_MACROS_FILE = _ROOT / "macros.json"

def _load_macros():
    global _macros
    if _MACROS_FILE.exists():
        try:
            with open(_MACROS_FILE, "r", encoding="utf-8") as f:
                _macros = json.load(f)
            logger.info("Macros chargées depuis disque (%d macros)", len(_macros))
        except Exception as e:
            logger.error("Erreur chargement macros : %s", e)
            _macros = {}

def _save_macros():
    try:
        with open(_MACROS_FILE, "w", encoding="utf-8") as f:
            json.dump(_macros, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("Erreur sauvegarde macros : %s", e)

# ─── ADB Screen Capture (bypass FLAG_SECURE) ──────────────────────────────────
_adb_stream_active: bool         = False
_adb_stream_task: asyncio.Task | None = None


def _adb_available() -> bool:
    try:
        r = subprocess.run(["adb", "get-state"], capture_output=True, text=True, timeout=3)
        return "device" in r.stdout
    except Exception:
        return False


async def _adb_capture_frame() -> bytes | None:
    try:
        proc = await asyncio.create_subprocess_exec(
            "adb", "exec-out", "screencap", "-p",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
        if proc.returncode == 0 and stdout and len(stdout) > 200:
            return stdout
        return None
    except asyncio.TimeoutError:
        logger.warning("ADB capture timeout")
        return None
    except Exception as e:
        logger.error("ADB capture erreur: %s", e)
        return None


async def _adb_stream_loop():
    global _latest_frame, _latest_frame_time, _latest_frame_mime
    global _stream_active, _adb_stream_active
    logger.info("ADB stream démarré — FLAG_SECURE bypassé, %d fps cible", _TARGET_FPS)
    target_interval = 1.0 / _TARGET_FPS
    try:
        next_frame_task: asyncio.Task | None = None
        while _adb_stream_active:
            t0 = time.time()
            if next_frame_task and next_frame_task.done():
                frame = next_frame_task.result()
                next_frame_task = None
            else:
                frame = await _adb_capture_frame()

            if frame:
                _latest_frame = frame
                _latest_frame_time = time.time()
                _latest_frame_mime = "image/png"
                dead = set()
                for ws_client in list(_viewer_ws_clients):
                    try:
                        await ws_client.send_bytes(frame)
                    except Exception:
                        dead.add(ws_client)
                _viewer_ws_clients.difference_update(dead)

            if _adb_stream_active and not next_frame_task:
                next_frame_task = asyncio.create_task(_adb_capture_frame())

            elapsed = time.time() - t0
            sleep_time = max(_MIN_SLEEP, target_interval - elapsed)
            await asyncio.sleep(sleep_time)
    except asyncio.CancelledError:
        if next_frame_task and not next_frame_task.done():
            next_frame_task.cancel()
    finally:
        _adb_stream_active = False
        _stream_active = False
        logger.info("ADB stream arrêté")


async def _start_adb_stream() -> bool:
    global _adb_stream_task, _adb_stream_active, _stream_active
    if _adb_stream_active:
        return True
    if not _adb_available():
        return False
    _adb_stream_active = True
    _stream_active = True
    _adb_stream_task = asyncio.create_task(_adb_stream_loop())
    return True


async def _stop_adb_stream():
    global _adb_stream_task, _adb_stream_active, _stream_active
    _adb_stream_active = False
    if _adb_stream_task:
        _adb_stream_task.cancel()
        try:
            await _adb_stream_task
        except asyncio.CancelledError:
            pass
        _adb_stream_task = None
    _stream_active = False


# ─── ADB helpers ──────────────────────────────────────────────────────────────

def _adb_shell(cmd: str, timeout: int = 10) -> str:
    """Exécute une commande ADB shell et retourne la sortie."""
    try:
        r = subprocess.run(
            ["adb", "shell", cmd],
            capture_output=True, text=True, timeout=timeout,
        )
        return (r.stdout or "").strip()
    except Exception as e:
        return f"ERROR: {e}"


# ─── Connexion téléphone ──────────────────────────────────────────────────────


class DeviceConnection:
    def __init__(self):
        self.ws = None
        self.connected = False
        self.device_ip = None
        self._lock = asyncio.Lock()

    async def on_app_connected(self, websocket) -> bool:
        self.ws = websocket
        try:
            raw = await asyncio.wait_for(websocket.recv(), timeout=5)
            welcome = json.loads(raw)
            if welcome.get("version") != PROTOCOL_VERSION:
                await websocket.close(1003, "Protocol version mismatch")
                return False
            if welcome.get("auth_token") != AUTH_TOKEN:
                await websocket.close(1008, "Invalid auth token")
                return False
            self.device_ip = welcome.get("device_ip", "?")
            self.connected = True
            logger.info("Telephone authentifie — IP %s", self.device_ip)
            return True
        except Exception as e:
            logger.error("Erreur auth : %s", e)
            await websocket.close(1011, "Authentication error")
            return False

    def on_app_disconnected(self, websocket):
        if self.ws is websocket:
            self.ws = None
            self.connected = False
            self.device_ip = None
            logger.info("Telephone deconnecte")

    async def send_command(self, command: dict) -> dict:
        if not self.connected or not self.ws:
            raise ConnectionError("Téléphone non connecté.")
        async with self._lock:
            ws = self.ws
            try:
                await ws.send(json.dumps(command))
                response = await asyncio.wait_for(ws.recv(), timeout=30)
                return json.loads(response)
            except asyncio.TimeoutError:
                self.connected = False
                self.ws = None
                asyncio.create_task(ws.close(1011, "Command timeout"))
                raise TimeoutError("Pas de réponse du téléphone (30s).")
            except Exception as e:
                self.connected = False
                self.ws = None
                asyncio.create_task(ws.close(1011, "Communication error"))
                raise ConnectionError(f"Erreur comm : {e}")

    async def disconnect(self):
        if self.ws:
            await self.ws.close()
        self.on_app_disconnected(self.ws)


device = DeviceConnection()


# ─── WebSocket relay ──────────────────────────────────────────────────────────


async def relay_handler(websocket):
    ok = await device.on_app_connected(websocket)
    if not ok:
        return
    try:
        await websocket.wait_closed()
    except websockets.exceptions.ConnectionClosed:
        pass
    except Exception as e:
        logger.error("WebSocket error : %s", e)
    finally:
        device.on_app_disconnected(websocket)


async def stream_relay_handler(websocket):
    global _latest_frame, _latest_frame_time, _latest_frame_mime, _stream_active
    _stream_active = True
    logger.info("Stream MediaProjection connecté (Kotlin ForegroundService)")
    try:
        async for message in websocket:
            if not isinstance(message, bytes):
                continue
            _latest_frame = message
            _latest_frame_time = time.time()
            _latest_frame_mime = "image/jpeg"
            dead = set()
            for ws_client in list(_viewer_ws_clients):
                try:
                    await ws_client.send_bytes(_latest_frame)
                except Exception:
                    dead.add(ws_client)
            _viewer_ws_clients.difference_update(dead)
    finally:
        _stream_active = False
        logger.info("Stream MediaProjection déconnecté")


# ─── Vision helpers ───────────────────────────────────────────────────────────

async def _get_screen_png() -> bytes | None:
    """Récupère un PNG de l'écran via ADB (préféré) ou le dernier frame."""
    frame = await _adb_capture_frame()
    if frame:
        return frame
    if _latest_frame:
        return _latest_frame
    return None


def _ocr_image(img_bytes: bytes, lang: str = "fra+eng") -> str:
    """OCR sur une image PNG/JPEG. Retourne le texte détecté."""
    if not _OCR_AVAILABLE:
        return "ERROR: pytesseract non installé"
    try:
        img = Image.open(_io.BytesIO(img_bytes))
        return pytesseract.image_to_string(img, lang=lang).strip()
    except Exception as e:
        return f"ERROR: {e}"


def _find_template(haystack_bytes: bytes, needle_bytes: bytes, threshold: float = 0.8) -> dict | None:
    """Cherche needle dans haystack. Retourne {x, y, w, h, score} ou None."""
    if not _CV2_AVAILABLE:
        return None
    try:
        hay_arr = np.frombuffer(haystack_bytes, np.uint8)
        ndl_arr = np.frombuffer(needle_bytes, np.uint8)
        haystack = cv2.imdecode(hay_arr, cv2.IMREAD_COLOR)
        needle   = cv2.imdecode(ndl_arr, cv2.IMREAD_COLOR)
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
    except Exception as e:
        logger.error("find_template error: %s", e)
        return None


def _crop_image(img_bytes: bytes, x: int, y: int, w: int, h: int) -> bytes | None:
    """Recadre une image PNG."""
    if not _CV2_AVAILABLE:
        # Fallback PIL
        if not _OCR_AVAILABLE:
            return None
        try:
            img = Image.open(_io.BytesIO(img_bytes))
            cropped = img.crop((x, y, x + w, y + h))
            buf = _io.BytesIO()
            cropped.save(buf, format="PNG")
            return buf.getvalue()
        except Exception:
            return None
    try:
        arr = np.frombuffer(img_bytes, np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            return None
        region = img[y:y+h, x:x+w]
        _, enc = cv2.imencode(".png", region)
        return enc.tobytes()
    except Exception as e:
        logger.error("crop_image error: %s", e)
        return None


# ─── HTTP server ──────────────────────────────────────────────────────────────

_VIEWER_HTML = """\
<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Android Live — MCP</title>
<style>
  *{margin:0;padding:0;box-sizing:border-box}
  body{background:#0a0a0a;display:flex;flex-direction:column;align-items:center;
       justify-content:center;height:100vh;font-family:monospace;color:#0f0}
  #bar{position:fixed;top:0;left:0;right:0;background:rgba(0,0,0,.8);
       padding:6px 12px;font-size:12px;display:flex;gap:16px;z-index:9;
       border-bottom:1px solid #1a1a1a}
  #screen{max-height:95vh;max-width:100vw;border:1px solid #1a3a1a;display:none}
  #offline{color:#f55;font-size:18px}
  .dot{width:8px;height:8px;border-radius:50%;background:#f55;display:inline-block;margin-right:6px}
  .dot.live{background:#0f0;animation:pulse 1s infinite}
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
</style></head><body>
<div id="bar">
  <span><span id="dot" class="dot"></span>Android Live Stream — MCP v2</span>
  <span id="fps">-- fps</span>
  <span id="size">-- KB/s</span>
  <span id="mode">--</span>
  <span id="status">Connecting...</span>
</div>
<canvas id="screen"></canvas>
<div id="offline">Stream déconnecté — en attente...</div>
<script>
const canvas=document.getElementById('screen'),ctx=canvas.getContext('2d');
const fpsEl=document.getElementById('fps'),sizeEl=document.getElementById('size');
const statusEl=document.getElementById('status'),offline=document.getElementById('offline');
const modeEl=document.getElementById('mode'),dot=document.getElementById('dot');
let frames=0,totalBytes=0,lastMime='image/jpeg';
setInterval(()=>{
  fpsEl.textContent=frames+' fps';
  sizeEl.textContent=(totalBytes/1024).toFixed(1)+' KB/s';
  frames=0;totalBytes=0;
},1000);
function connect(){
  const ws=new WebSocket('ws://'+location.hostname+':'+location.port+'/ws');
  ws.binaryType='arraybuffer';
  ws.onopen=()=>{
    statusEl.textContent='Live';
    offline.style.display='none';
    canvas.style.display='block';
    dot.classList.add('live');
  };
  ws.onclose=()=>{
    statusEl.textContent='Déconnecté';
    offline.style.display='block';
    canvas.style.display='none';
    dot.classList.remove('live');
    setTimeout(connect,1500);
  };
  ws.onerror=()=>ws.close();
  ws.onmessage=(e)=>{
    totalBytes+=e.data.byteLength;
    const arr=new Uint8Array(e.data,0,4);
    const mime=(arr[0]===0x89&&arr[1]===0x50)?'image/png':'image/jpeg';
    if(mime!==lastMime){
      lastMime=mime;
      modeEl.textContent=mime==='image/png'?'[ADB bypass]':'[MediaProjection]';
    }
    const blob=new Blob([e.data],{type:mime});
    const url=URL.createObjectURL(blob);
    const img=new Image();
    img.onload=()=>{
      canvas.width=img.width;canvas.height=img.height;
      ctx.drawImage(img,0,0);
      URL.revokeObjectURL(url);
      frames++;
    };
    img.src=url;
  };
}
connect();
</script></body></html>
"""


async def health_handler(request):
    return web.json_response({
        "status": "ok" if device.connected else "disconnected",
        "device_ip": device.device_ip,
        "protocol_version": PROTOCOL_VERSION,
        "stream_active": _stream_active,
        "adb_stream": _adb_stream_active,
        "ocr_available": _OCR_AVAILABLE,
        "cv2_available": _CV2_AVAILABLE,
        "macros_count": len(_macros),
    })


async def command_handler(request):
    global _latest_frame, _latest_frame_time, _latest_frame_mime
    global _current_macro, _current_macro_name, _macros

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"success": False, "error": "JSON invalide"}, status=400)

    action = body.get("action", "")

    # ── Macros (persistées sur disque) ────────────────────────────────────────
    if action == "macro_start":
        _current_macro = []
        _current_macro_name = body.get("name")
        return web.json_response({"success": True})

    if action == "macro_stop":
        if not _current_macro_name:
            return web.json_response({"success": False, "error": "Pas d'enregistrement en cours"})
        name = _current_macro_name
        _macros[name] = _current_macro.copy()
        _current_macro = []
        _current_macro_name = None
        _save_macros()  # ← persistance disque
        return web.json_response({"success": True, "data": {"name": name, "count": len(_macros[name])}})

    if action == "macro_record":
        if _current_macro_name is None:
            return web.json_response({"success": False, "error": "Pas d'enregistrement en cours"})
        _current_macro.append({"action": body.get("cmd"), "params": body.get("params", {})})
        return web.json_response({"success": True, "data": len(_current_macro)})

    if action == "macro_replay":
        name = body.get("name")
        delay_ms = body.get("delay_ms", 500)
        if name not in _macros:
            return web.json_response({"success": False, "error": f"Macro '{name}' introuvable"})
        for i, act in enumerate(_macros[name]):
            try:
                await device.send_command({"action": act["action"], **act.get("params", {})})
            except Exception as e:
                return web.json_response({"success": False, "error": f"Action {i+1} échouée: {e}"})
            if i < len(_macros[name]) - 1:
                await asyncio.sleep(delay_ms / 1000)
        return web.json_response({"success": True, "data": len(_macros[name])})

    if action == "macro_list":
        return web.json_response({"success": True, "data": {k: len(v) for k, v in _macros.items()}})

    if action == "macro_delete":
        _macros.pop(body.get("name"), None)
        _save_macros()
        return web.json_response({"success": True})

    # ── get_live_frame ────────────────────────────────────────────────────────
    if action == "get_live_frame":
        frame_age = time.time() - _latest_frame_time if _latest_frame else 999
        if _latest_frame is None or frame_age > 5:
            adb_frame = await _adb_capture_frame()
            if adb_frame:
                _latest_frame = adb_frame
                _latest_frame_time = time.time()
                _latest_frame_mime = "image/png"
                frame_age = 0

        if _latest_frame is None:
            return web.json_response({"success": False, "error": "Aucun frame disponible"})

        frame_age = time.time() - _latest_frame_time
        return web.json_response({
            "success": True,
            "data": base64.b64encode(_latest_frame).decode(),
            "mime": _latest_frame_mime,
            "stream_active": _stream_active or _adb_stream_active,
            "adb_mode": _adb_stream_active,
            "frame_age_ms": int(frame_age * 1000),
        })

    # ── OCR screen ────────────────────────────────────────────────────────────
    if action == "ocr_screen":
        if not _OCR_AVAILABLE:
            return web.json_response({"success": False, "error": "pytesseract non installé. Lance: pip install pytesseract Pillow"})
        lang = body.get("lang", "fra+eng")
        frame = await _get_screen_png()
        if frame is None:
            return web.json_response({"success": False, "error": "Impossible de capturer l'écran"})
        loop = asyncio.get_event_loop()
        text = await loop.run_in_executor(None, _ocr_image, frame, lang)
        return web.json_response({"success": True, "data": text})

    # ── Screenshot région ─────────────────────────────────────────────────────
    if action == "screenshot_region":
        x = body.get("x", 0)
        y = body.get("y", 0)
        w = body.get("width", 200)
        h = body.get("height", 200)
        frame = await _get_screen_png()
        if frame is None:
            return web.json_response({"success": False, "error": "Impossible de capturer l'écran"})
        cropped = _crop_image(frame, x, y, w, h)
        if cropped is None:
            return web.json_response({"success": False, "error": "Recadrage impossible — installer opencv ou Pillow"})
        return web.json_response({
            "success": True,
            "data": base64.b64encode(cropped).decode(),
            "mime": "image/png",
            "region": {"x": x, "y": y, "w": w, "h": h},
        })

    # ── Find by image (template matching) ────────────────────────────────────
    if action == "find_by_image":
        if not _CV2_AVAILABLE:
            return web.json_response({"success": False, "error": "opencv-python-headless non installé"})
        needle_b64 = body.get("template")
        if not needle_b64:
            return web.json_response({"success": False, "error": "Paramètre 'template' (base64 PNG) requis"})
        threshold = float(body.get("threshold", 0.8))
        frame = await _get_screen_png()
        if frame is None:
            return web.json_response({"success": False, "error": "Impossible de capturer l'écran"})
        try:
            needle_bytes = base64.b64decode(needle_b64)
        except Exception:
            return web.json_response({"success": False, "error": "Template base64 invalide"})
        loop = asyncio.get_event_loop()
        match = await loop.run_in_executor(None, _find_template, frame, needle_bytes, threshold)
        if match is None:
            return web.json_response({"success": False, "found": False, "error": "Template non trouvé"})
        return web.json_response({"success": True, "found": True, "x": match["x"], "y": match["y"],
                                  "w": match["w"], "h": match["h"], "score": match["score"]})

    # ── Mobile data ───────────────────────────────────────────────────────────
    if action == "enable_mobile_data":
        enabled = body.get("enabled", True)
        state = "enable" if enabled else "disable"
        out = _adb_shell(f"svc data {state}")
        return web.json_response({"success": True, "data": out or f"Mobile data {'activé' if enabled else 'désactivé'}"})

    # ── WiFi list ─────────────────────────────────────────────────────────────
    if action == "get_wifi_list":
        if not _adb_available():
            # Déléguer au téléphone
            try:
                result = await device.send_command({"action": "get_wifi_list"})
                return web.json_response(result)
            except Exception as e:
                return web.json_response({"success": False, "error": str(e)}, status=503)
        out = _adb_shell("cmd wifi list-networks")
        networks = []
        for line in out.splitlines():
            line = line.strip()
            if line and not line.startswith("Id") and not line.startswith("---"):
                networks.append(line)
        return web.json_response({"success": True, "data": networks})

    # ── Connect WiFi ──────────────────────────────────────────────────────────
    if action == "connect_wifi":
        ssid     = body.get("ssid", "")
        password = body.get("password", "")
        if not ssid:
            return web.json_response({"success": False, "error": "ssid requis"})
        if not _adb_available():
            try:
                result = await device.send_command({"action": "connect_wifi", "ssid": ssid, "password": password})
                return web.json_response(result)
            except Exception as e:
                return web.json_response({"success": False, "error": str(e)}, status=503)
        if password:
            cmd = f'cmd wifi connect-network \"{ssid}\" wpa2 \"{password}\"'
        else:
            cmd = f'cmd wifi connect-network \"{ssid}\" open'
        out = _adb_shell(cmd, timeout=15)
        success = "successfully" in out.lower() or out == ""
        return web.json_response({"success": success, "data": out})

    # ── Contacts ──────────────────────────────────────────────────────────────
    if action == "get_contacts":
        if not _adb_available():
            try:
                result = await device.send_command({"action": "get_contacts"})
                return web.json_response(result)
            except Exception as e:
                return web.json_response({"success": False, "error": str(e)}, status=503)
        limit  = int(body.get("limit", 20))
        search = body.get("search", "")
        where  = f' WHERE display_name LIKE \"%{search}%\"' if search else ""
        query = f"content query --uri content://contacts/phones --projection display_name:number{where} --sort display_name LIMIT {limit}"
        out = _adb_shell(query, timeout=10)
        contacts = []
        for line in out.splitlines():
            if "display_name=" in line:
                m_name = re.search(r"display_name=([^,\n]+)", line)
                m_num  = re.search(r"number=([^,\n]+)", line)
                if m_name and m_num:
                    contacts.append({"name": m_name.group(1).strip(), "number": m_num.group(1).strip()})
        return web.json_response({"success": True, "data": contacts, "count": len(contacts)})

    # ── Send SMS ──────────────────────────────────────────────────────────────
    if action == "send_sms":
        to  = body.get("to", "")
        msg = body.get("message", "")
        if not to or not msg:
            return web.json_response({"success": False, "error": "Paramètres 'to' et 'message' requis"})
        if not _adb_available():
            try:
                result = await device.send_command({"action": "send_sms", "to": to, "message": msg})
                return web.json_response(result)
            except Exception as e:
                return web.json_response({"success": False, "error": str(e)}, status=503)
        cmd = f'am start -a android.intent.action.SENDTO -d sms:{to} --es sms_body "{msg}" --ez exit_on_sent true'
        _adb_shell(cmd)
        return web.json_response({"success": True, "data": f"SMS ouvert vers {to} — confirme l'envoi sur le téléphone"})

    # ── Key combo (raccourcis clavier) ────────────────────────────────────────
    if action == "key_combo":
        keys = body.get("keys", [])
        if not keys:
            return web.json_response({"success": False, "error": "Paramètre 'keys' requis (liste de keycodes)"})
        if not _adb_available():
            try:
                result = await device.send_command({"action": "key_combo", "keys": keys})
                return web.json_response(result)
            except Exception as e:
                return web.json_response({"success": False, "error": str(e)}, status=503)
        for key in keys:
            _adb_shell(f"input keyevent {key}")
        return web.json_response({"success": True, "data": f"Key combo {keys} envoyé"})

    # ── Multi-touch ───────────────────────────────────────────────────────────
    if action == "multi_touch":
        points = body.get("points", [])  # [{x, y, start_ms, end_ms}]
        if not points:
            return web.json_response({"success": False, "error": "Paramètre 'points' requis"})
        try:
            result = await device.send_command({"action": "multi_touch", "points": points})
            return web.json_response(result)
        except Exception as e:
            return web.json_response({"success": False, "error": str(e)}, status=503)

    # ── Sensor data ───────────────────────────────────────────────────────────
    if action == "get_sensor_data":
        sensor = body.get("sensor", "all")
        if not _adb_available():
            try:
                result = await device.send_command({"action": "get_sensor_data", "sensor": sensor})
                return web.json_response(result)
            except Exception as e:
                return web.json_response({"success": False, "error": str(e)}, status=503)
        out = _adb_shell(f"dumpsys sensorservice | grep -i {sensor}", timeout=5)
        return web.json_response({"success": True, "data": out})

    # ── Stream ────────────────────────────────────────────────────────────────
    if action == "start_stream":
        if not _adb_stream_active:
            adb_ok = await _start_adb_stream()
            if adb_ok:
                return web.json_response({"success": True, "mode": "adb_bypass",
                                          "message": "Stream ADB actif — FLAG_SECURE bypassé"})
        if _adb_stream_active:
            return web.json_response({"success": True, "mode": "adb_bypass"})
        try:
            result = await device.send_command(body)
            return web.json_response(result)
        except Exception as e:
            return web.json_response({"success": False, "error": str(e)}, status=503)

    if action == "stop_stream":
        await _stop_adb_stream()
        if device.connected:
            try:
                await device.send_command({"action": "stop_stream"})
            except Exception:
                pass
        return web.json_response({"success": True})

    # ── ADB screenshot one-shot ───────────────────────────────────────────────
    if action == "adb_screenshot":
        frame = await _adb_capture_frame()
        if frame:
            return web.json_response({"success": True, "data": base64.b64encode(frame).decode(), "mime": "image/png"})
        return web.json_response({"success": False, "error": "ADB capture échouée"})

    # ── Disconnect ────────────────────────────────────────────────────────────
    if action == "disconnect":
        await device.disconnect()
        return web.json_response({"success": True})

    # ── Auto-reconnect ────────────────────────────────────────────────────────
    if action == "auto_reconnect_enable":
        global _auto_reconnect_enabled
        _auto_reconnect_enabled = True
        return web.json_response({"success": True})

    if action == "auto_reconnect_disable":
        _auto_reconnect_enabled = False
        return web.json_response({"success": True})

    if action == "auto_reconnect_status":
        return web.json_response({"success": True, "data": _auto_reconnect_enabled})

    # ── Relay status ──────────────────────────────────────────────────────────
    if action == "relay_status":
        return web.json_response({"success": True, "connected": device.connected, "device_ip": device.device_ip})

    # ── Toutes les autres commandes → téléphone ───────────────────────────────
    try:
        result = await device.send_command(body)
        return web.json_response(result)
    except ConnectionError as e:
        return web.json_response({"success": False, "error": str(e)}, status=503)
    except TimeoutError as e:
        return web.json_response({"success": False, "error": str(e)}, status=504)
    except Exception as e:
        return web.json_response({"success": False, "error": str(e)}, status=500)


async def viewer_html_handler(request):
    return web.Response(text=_VIEWER_HTML, content_type="text/html")


async def viewer_ws_handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    _viewer_ws_clients.add(ws)
    if _latest_frame:
        try:
            await ws.send_bytes(_latest_frame)
        except Exception:
            pass
    try:
        async for _ in ws:
            pass
    finally:
        _viewer_ws_clients.discard(ws)
    return ws


async def setup_handler(request):
    steps = []
    pkg = "com.androidmcp.companion"

    if not _adb_available():
        return web.json_response(
            {"success": False, "error": "ADB non disponible — connecte le téléphone en USB."},
            status=503,
        )

    # 1. Accessibility Service
    try:
        r = subprocess.run(
            ["adb", "shell", "settings", "put", "secure", "enabled_accessibility_services",
             f"{pkg}/.MCPAccessibilityService"],
            capture_output=True, text=True, timeout=5,
        )
        steps.append({"desc": "Accessibility Service activé", "ok": r.returncode == 0})
    except Exception as e:
        steps.append({"desc": f"Accessibility Service : {e}", "ok": False})

    # 2. Accessibilité globale
    try:
        r = subprocess.run(
            ["adb", "shell", "settings", "put", "secure", "accessibility_enabled", "1"],
            capture_output=True, text=True, timeout=5,
        )
        steps.append({"desc": "Accessibilité globale activée", "ok": r.returncode == 0})
    except Exception as e:
        steps.append({"desc": f"Accessibilité globale : {e}", "ok": False})

    # 3. Permissions runtime
    permissions = [
        "android.permission.READ_EXTERNAL_STORAGE",
        "android.permission.WRITE_EXTERNAL_STORAGE",
        "android.permission.POST_NOTIFICATIONS",
        "android.permission.ACCESS_FINE_LOCATION",
        "android.permission.RECORD_AUDIO",
        "android.permission.READ_CONTACTS",
        "android.permission.SEND_SMS",
        "android.permission.READ_SMS",
        "android.permission.ACCESS_WIFI_STATE",
        "android.permission.CHANGE_WIFI_STATE",
        "android.permission.CHANGE_NETWORK_STATE",
    ]
    for perm in permissions:
        try:
            r = subprocess.run(
                ["adb", "shell", "pm", "grant", pkg, perm],
                capture_output=True, text=True, timeout=5,
            )
            short_name = perm.split(".")[-1]
            steps.append({"desc": f"Permission {short_name}", "ok": r.returncode == 0})
        except Exception as e:
            steps.append({"desc": f"Permission {perm}: {e}", "ok": False})

    # 4. Désactiver restriction batterie
    try:
        r = subprocess.run(
            ["adb", "shell", "cmd", "appops", "set", pkg, "RUN_IN_BACKGROUND", "allow"],
            capture_output=True, text=True, timeout=5,
        )
        steps.append({"desc": "Restriction batterie désactivée", "ok": r.returncode == 0})
    except Exception as e:
        steps.append({"desc": f"Restriction batterie : {e}", "ok": False})

    # 5. Désactiver optimisation batterie
    try:
        r = subprocess.run(
            ["adb", "shell", "dumpsys", "deviceidle", "whitelist", f"+{pkg}"],
            capture_output=True, text=True, timeout=5,
        )
        steps.append({"desc": "Optimisation batterie désactivée", "ok": r.returncode == 0})
    except Exception as e:
        steps.append({"desc": f"Optimisation batterie : {e}", "ok": False})

    all_ok = all(s["ok"] for s in steps)
    return web.json_response({"success": all_ok, "steps": steps})


async def batch_handler(request):
    """POST /batch { "actions": [...] } — Exécute N commandes séquentiellement."""
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"success": False, "error": "JSON invalide"}, status=400)

    actions = body.get("actions", [])
    if not isinstance(actions, list):
        return web.json_response({"success": False, "error": "actions doit être une liste"}, status=400)

    results = []
    stop_on_error = body.get("stop_on_error", False)
    for act in actions:
        action_name = act.get("action", "")
        params = {k: v for k, v in act.items() if k != "action"}
        try:
            result = await device.send_command({"action": action_name, **params})
            results.append(result)
            if stop_on_error and not result.get("success", True):
                break
        except Exception as e:
            results.append({"success": False, "error": str(e)})
            if stop_on_error:
                break

    return web.json_response({"success": True, "results": results, "count": len(results)})


# ─── UDP Beacon ───────────────────────────────────────────────────────────────

async def _udp_beacon_loop():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.setblocking(False)

    def _get_local_ip() -> str:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    local_ip = _get_local_ip()
    beacon = json.dumps({
        "service": "android-mcp",
        "ip": local_ip,
        "ws_port": RELAY_PORT,
        "http_port": HTTP_PORT,
        "version": PROTOCOL_VERSION,
    }).encode()

    logger.info("UDP beacon actif — broadcasting sur port %d (IP: %s)", BEACON_PORT, local_ip)
    try:
        while True:
            try:
                sock.sendto(beacon, ("255.255.255.255", BEACON_PORT))
            except Exception:
                pass
            await asyncio.sleep(3)
    except asyncio.CancelledError:
        pass
    finally:
        sock.close()


# ─── Main ─────────────────────────────────────────────────────────────────────

async def main():
    # Charger les macros persistées
    _load_macros()

    logger.info("Relay daemon v2 démarré")
    logger.info("   WebSocket commandes  : ws://0.0.0.0:%d", RELAY_PORT)
    logger.info("   WebSocket stream     : ws://0.0.0.0:%d", STREAM_RELAY_PORT)
    logger.info("   HTTP viewer+cmd      : http://0.0.0.0:%d", HTTP_PORT)
    logger.info("   UDP beacon           : broadcast port %d", BEACON_PORT)
    logger.info("   ADB bypass           : %s", "disponible" if _adb_available() else "non disponible")
    logger.info("   OCR                  : %s", "disponible" if _OCR_AVAILABLE else "non disponible")
    logger.info("   Vision/OpenCV        : %s", "disponible" if _CV2_AVAILABLE else "non disponible")
    logger.info("   Macros persistées    : %d macros chargées", len(_macros))
    logger.info("   Token AUTH           : %s (ENV: ANDROID_MCP_TOKEN)", AUTH_TOKEN[:8] + "...")

    relay = await websockets.serve(
        relay_handler, "0.0.0.0", RELAY_PORT,
        reuse_address=False, max_size=20 * 1024 * 1024,
    )
    stream_relay = await websockets.serve(
        stream_relay_handler, "0.0.0.0", STREAM_RELAY_PORT,
        reuse_address=False, max_size=15 * 1024 * 1024,
    )

    web_app = web.Application()
    web_app.router.add_get("/", viewer_html_handler)
    web_app.router.add_get("/ws", viewer_ws_handler)
    web_app.router.add_get("/health", health_handler)
    web_app.router.add_post("/command", command_handler)
    web_app.router.add_post("/setup", setup_handler)
    web_app.router.add_post("/batch", batch_handler)

    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", HTTP_PORT)
    await site.start()

    asyncio.create_task(_udp_beacon_loop())

    logger.info("Relay prêt — en attente du téléphone...")
    await asyncio.Future()  # run forever


if __name__ == "__main__":
    asyncio.run(main())
