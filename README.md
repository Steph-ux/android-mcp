# Android MCP

> **Full Android control from any AI agent** — Claude, OpenCode, Windsurf, Cursor…
> 7 categorical MCP tools · 90fps live viewer · WiFi ADB · zero app to install

---

## Quick demo

```python
android_screen(action="screenshot")                          # PNG capture
android_screen(action="ocr")                                 # visible text
android_interact(action="tap", params={"x": 540, "y": 960}) # tap
android_interact(action="find", params={"text": "Send"})     # find + tap
android_system(action="battery")                             # battery info
android_screen(action="viewer")                              # 90fps interactive window on PC
```

---

## Architecture

```
AI Agent (Claude / OpenCode / Windsurf / Cursor…)
        ↓  MCP Protocol (stdio)
    server.py          ← 7 categorical tools
        ↓
    device_manager.py  ← device selection, multi-device
        ↓
    backends/
        ├── adb_backend.py       ← PRIMARY  : uiautomator2 + direct ADB
        └── companion_backend.py ← FALLBACK : Flutter app WebSocket
        ↓
    N Android phones / emulators
```

**ADB backend (primary)** — works on any device with developer mode enabled.
Nothing to install on the phone. Uses `uiautomator2` + ADB commands.

**Companion backend (fallback)** — optional Flutter app when ADB is unavailable on the network.

---

## Requirements

- **Python 3.10+**
- **ADB** in PATH (`winget install Google.PlatformTools`)
- **Android**: Developer mode + USB debugging (or WiFi debugging)

---

## Installation

```bash
git clone https://github.com/Steph-ux/android-mcp
cd android-mcp
pip install -r requirements.txt

# Initialize uiautomator2 (once per device)
python -m uiautomator2 init
```

### Live viewer 90fps (optional)

```bash
winget install Genymobile.scrcpy
python viewer.py
```

---

## MCP Configuration

```bash
# Generate the correct JSON for your AI client
python mcp_config.py --client claude     # Claude Desktop
python mcp_config.py --client opencode  # OpenCode
python mcp_config.py --client windsurf  # Windsurf
python mcp_config.py --client cursor    # Cursor
python mcp_config.py --write            # write directly to config files
```

Claude Desktop example (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "android-mcp": {
      "command": "C:/Python312/python.exe",
      "args": ["D:/path/to/android-mcp/server.py"],
      "type": "stdio"
    }
  }
}
```

---

## WiFi connection without USB (Android 11+)

```bash
# On the phone: Settings → Developer options → Wireless debugging → Pair device
adb pair 192.168.1.42:38765    # enter the code shown on the phone
adb connect 192.168.1.42:5555
```

Full guide → [WIFI_PAIRING.md](WIFI_PAIRING.md)

---

## The 7 MCP tools

Call convention: `android_xxx(action="...", params={...}, device_id="serial")`
`device_id` is always optional (uses the currently selected device).

---

### `android_device` — Device management

| Action | Params | Description |
|--------|--------|-------------|
| `list` | — | All connected devices (USB, WiFi, emulators) |
| `select` | `serial` | Set default device |
| `connect` | `host`, `port` | WiFi ADB connection |
| `disconnect` | — | Disconnect current WiFi device |
| `info` | — | Model, OS, resolution, density |
| `status` | — | Is device connected and ready? |
| `setup` | — | Configure animations, stay-awake, ATX agent |

---

### `android_screen` — Capture & Stream

| Action | Params | Description |
|--------|--------|-------------|
| `screenshot` | — | PNG capture (bypasses FLAG_SECURE) → image |
| `region` | `x y width height` | Capture a specific area → image |
| `size` | — | `{width, height}` |
| `is_on` | — | Is the screen on? |
| `wake` | — | Wake the screen |
| `start_stream` | — | Start ADB stream (~16fps) |
| `stop_stream` | — | Stop stream |
| `live_frame` | — | Latest stream frame → image |
| `ocr` | `lang` | Extract visible text (Tesseract) |
| `find_image` | `template_b64 threshold` | Template matching (OpenCV) |
| `viewer` | `fps bitrate no_control` | Launch scrcpy 90fps window on PC |

---

### `android_interact` — Touch, Keyboard, UI

| Action | Params | Description |
|--------|--------|-------------|
| `tap` | `x y` | Tap |
| `double_tap` | `x y` | Double tap |
| `long_press` | `x y duration_ms` | Long press |
| `swipe` | `x1 y1 x2 y2 duration_ms` | Swipe |
| `drag` | `x1 y1 x2 y2 duration_ms` | Drag & drop |
| `pinch` | `x y scale duration_ms` | Pinch zoom |
| `multi_touch` | `points` | Multi-finger gestures |
| `type` | `text` | Type text |
| `clear` | — | Clear active field |
| `submit` | `text` | Type + Enter |
| `key` | `key` | System key (HOME, BACK, ENTER, VOLUME_UP…) |
| `combo` | `keys` | Key combination (keycodes) |
| `hierarchy` | — | Full UI XML tree (uiautomator2) |
| `find` | `text partial_match` | Find element and tap it |
| `wait` | `text timeout partial_match` | Wait for element |
| `scroll` | `text direction max_swipes` | Scroll to element |
| `assert` | `text partial_match` | Assert text is visible |

---

### `android_app` — Applications

| Action | Params | Description |
|--------|--------|-------------|
| `launch` | `package` | Launch an app |
| `close` | `package` | Force-stop an app |
| `list` | `include_system` | List installed apps |
| `install` | `apk_path` | Install APK from PC |
| `uninstall` | `package` | Uninstall app |
| `current` | — | Foreground app package |
| `url` | `url` | Open a URL |
| `intent` | `action uri package extras` | Send Android intent |
| `settings` | `section` | Open system settings (`main wifi bluetooth display…`) |

---

### `android_files` — Files

| Action | Params | Description |
|--------|--------|-------------|
| `push` | `local_path remote_path` | PC → phone |
| `push_b64` | `remote_path data` | Base64 → phone |
| `pull` | `remote_path local_path` | Phone → PC |
| `pull_b64` | `remote_path` | Phone → base64 |
| `list` | `directory` | List directory contents |

---

### `android_system` — System & Network

| Action | Params | Description |
|--------|--------|-------------|
| `shell` | `command` | ADB shell command |
| `logs` | `lines package` | Logcat |
| `battery` | — | Battery level and charging state |
| `clipboard_get` | — | Read clipboard |
| `clipboard_set` | `text` | Write to clipboard |
| `volume` | `level stream` | Set volume |
| `rotation` | `rotation` | Screen rotation (0-3) |
| `wifi` | `enabled` | WiFi on/off |
| `bluetooth` | `enabled` | Bluetooth on/off |
| `mobile_data` | `enabled` | Mobile data on/off |
| `notifications` | — | Active notifications |
| `gps` | `lat lng` | Mock GPS location |
| `sensors` | `sensor` | Accelerometer, gyro, light… |
| `wifi_list` | — | Available WiFi networks |
| `wifi_connect` | `ssid password` | Connect to WiFi |
| `contacts` | `search limit` | Read contacts |
| `sms` | `to message` | Send SMS (requires confirmation on phone) |

---

### `android_automation` — Batch & Macros

| Action | Params | Description |
|--------|--------|-------------|
| `batch` | `actions stop_on_error` | Run N actions in one call |
| `macro_start` | `name` | Start recording a macro |
| `macro_record` | `action …params` | Add action to macro |
| `macro_stop` | — | Save macro |
| `macro_list` | — | List saved macros |
| `macro_replay` | `name delay_ms` | Replay a macro |
| `macro_delete` | `name` | Delete a macro |

---

## Live viewer — scrcpy 90fps

```bash
python viewer.py                  # auto-detect device, 90fps, interactive
python viewer.py --fps 60         # 60fps
python viewer.py --record         # record to .mp4
python viewer.py --record out.mp4 # named output file
python viewer.py --multi          # one viewer per connected device
python viewer.py --no-control     # read-only mode
```

| Control | Action |
|---------|--------|
| Left click | Tap |
| Drag | Swipe |
| Right click | BACK |
| Scroll | Scroll |
| `Alt+H` | HOME |
| `Alt+S` | Screenshot → PC clipboard |
| `Alt+F` | Fullscreen |
| `Alt+R` | Rotation |

---

## Tests

```bash
# Unit tests (no device required)
pytest tests/test_server_unit.py -v      # 94 tests

# Integration tests (ADB device required)
pytest tests/test_integration.py -v
```

---

## Project structure

```
android-mcp/
├── server.py              # MCP server — 7 tools
├── viewer.py              # scrcpy 90fps interactive viewer
├── mcp_config.py          # JSON config generator
├── device_manager.py      # Multi-device management
├── relay.py               # ⚠️ LEGACY — companion fallback only
├── requirements.txt
├── pyproject.toml
├── WIFI_PAIRING.md
├── backends/
│   ├── adb_backend.py     # Primary backend (uiautomator2 + ADB)
│   └── companion_backend.py  # Fallback backend (Flutter app)
├── examples/
│   ├── agent_loop.py      # Autonomous automation loop
│   └── whatsapp_auto.py   # WhatsApp automation example
└── tests/
    ├── conftest.py
    ├── test_server_unit.py   # 94 unit tests
    └── test_integration.py   # Real device tests
```

---

## Examples

```python
# WhatsApp — send a message
await android_app("launch", {"package": "com.whatsapp"})
await android_interact("find", {"text": "Alice"})
await android_interact("type", {"text": "Hello!"})
await android_interact("key",  {"key": "ENTER"})

# Batch in a single call
await android_automation("batch", {"actions": [
    {"action": "key",  "key": "HOME"},
    {"action": "tap",  "x": 540, "y": 200},
    {"action": "type", "text": "search query"},
    {"action": "key",  "key": "ENTER"},
]})

# Macro: record + replay
await android_automation("macro_start",  {"name": "login"})
await android_automation("macro_record", {"action": "tap",  "x": 540, "y": 400})
await android_automation("macro_record", {"action": "type", "text": "password"})
await android_automation("macro_stop")
await android_automation("macro_replay", {"name": "login"})
```

See `examples/whatsapp_auto.py` and `examples/agent_loop.py` for full use cases.

---

## License

MIT
