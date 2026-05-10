# Android MCP

> **Contrôle total d'Android depuis n'importe quel agent IA** — Claude, OpenCode, Windsurf, Cursor…
> 7 outils MCP catégoriels · viewer 90fps · WiFi ADB · zéro app à installer

---

## Démo rapide

```python
android_screen(action="screenshot")                          # capture PNG
android_screen(action="ocr")                                 # texte visible
android_interact(action="tap", params={"x": 540, "y": 960}) # tap
android_interact(action="find", params={"text": "Envoyer"}) # chercher + taper
android_system(action="battery")                             # batterie
android_screen(action="viewer")                              # viewer 90fps sur le PC
```

---

## Architecture

```
Agent IA (Claude / OpenCode / Windsurf / Cursor…)
        ↓  MCP Protocol (stdio)
    server.py          ← 7 outils catégoriels
        ↓
    device_manager.py  ← sélection device, multi-device
        ↓
    backends/
        ├── adb_backend.py       ← PRIMARY  : uiautomator2 + ADB direct
        └── companion_backend.py ← FALLBACK : app Flutter WebSocket
        ↓
    N téléphones Android / émulateurs
```

**Backend ADB (principal)** — fonctionne sur tout device en mode développeur.
Zéro app à installer sur le téléphone. Utilise `uiautomator2` + commandes ADB.

**Backend Companion (fallback)** — app Flutter optionnelle si ADB n'est pas disponible sur le réseau.

---

## Prérequis

- **Python 3.10+**
- **ADB** dans le PATH (`winget install Google.PlatformTools`)
- **Android** : Mode développeur + Débogage USB (ou WiFi)

---

## Installation

```bash
git clone https://github.com/ton-user/android-mcp
cd android-mcp
pip install -r requirements.txt

# Initialiser uiautomator2 (une fois par device)
python -m uiautomator2 init
```

### Viewer live 90fps (optionnel)

```bash
winget install Genymobile.scrcpy
python viewer.py
```

---

## Configuration MCP

```bash
# Génère le bon JSON pour ton client IA
python mcp_config.py --client claude     # Claude Desktop
python mcp_config.py --client opencode  # OpenCode
python mcp_config.py --client windsurf  # Windsurf
python mcp_config.py --client cursor    # Cursor
python mcp_config.py --write            # écrire directement dans les fichiers
```

Exemple Claude Desktop (`claude_desktop_config.json`) :

```json
{
  "mcpServers": {
    "android-mcp": {
      "command": "C:/Python312/python.exe",
      "args": ["D:/chemin/vers/android-mcp/server.py"],
      "type": "stdio"
    }
  }
}
```

---

## Connexion WiFi sans câble (Android 11+)

```bash
# Sur le téléphone : Paramètres → Options dev → Débogage sans fil → Associer
adb pair 192.168.1.42:38765    # code affiché sur le téléphone
adb connect 192.168.1.42:5555
```

Guide complet → [WIFI_PAIRING.md](WIFI_PAIRING.md)

---

## Les 7 outils MCP

Convention d'appel : `android_xxx(action="...", params={...}, device_id="serial")`
Le `device_id` est toujours optionnel (utilise le device sélectionné par défaut).

---

### `android_device` — Gestion des devices

| Action | Params | Description |
|--------|--------|-------------|
| `list` | — | Tous les devices connectés (USB, WiFi, émulateurs) |
| `select` | `serial` | Sélectionne le device par défaut |
| `connect` | `host`, `port` | Connexion WiFi ADB |
| `disconnect` | — | Déconnecte le device WiFi actuel |
| `info` | — | Modèle, OS, résolution, densité |
| `status` | — | Device connecté et prêt ? |
| `setup` | — | Configure animations, stay-awake, ATX |

---

### `android_screen` — Capture & Stream

| Action | Params | Description |
|--------|--------|-------------|
| `screenshot` | — | Capture PNG (bypass FLAG_SECURE) → image |
| `region` | `x y width height` | Capture d'une zone → image |
| `size` | — | `{width, height}` |
| `is_on` | — | Écran allumé ? |
| `wake` | — | Allume l'écran |
| `start_stream` | — | Stream ADB (~16fps) |
| `stop_stream` | — | Arrête le stream |
| `live_frame` | — | Dernier frame → image |
| `ocr` | `lang` | Texte visible (Tesseract) |
| `find_image` | `template_b64 threshold` | Template matching OpenCV |
| `viewer` | `fps bitrate no_control` | Lance scrcpy 90fps sur le PC |

---

### `android_interact` — Touch, Clavier, UI

| Action | Params | Description |
|--------|--------|-------------|
| `tap` | `x y` | Tap |
| `double_tap` | `x y` | Double tap |
| `long_press` | `x y duration_ms` | Appui long |
| `swipe` | `x1 y1 x2 y2 duration_ms` | Swipe |
| `drag` | `x1 y1 x2 y2 duration_ms` | Drag & drop |
| `pinch` | `x y scale duration_ms` | Pinch zoom |
| `multi_touch` | `points` | Gestes multi-doigts |
| `type` | `text` | Saisie de texte |
| `clear` | — | Efface le champ actif |
| `submit` | `text` | Saisit + Entrée |
| `key` | `key` | HOME, BACK, ENTER, VOLUME_UP… |
| `combo` | `keys` | Combinaison de keycodes |
| `hierarchy` | — | XML complet de l'UI |
| `find` | `text partial_match` | Cherche et tape un élément |
| `wait` | `text timeout partial_match` | Attend un élément |
| `scroll` | `text direction max_swipes` | Scrolle vers un élément |
| `assert` | `text partial_match` | Vérifie qu'un texte est visible |

---

### `android_app` — Applications

| Action | Params | Description |
|--------|--------|-------------|
| `launch` | `package` | Lance une app |
| `close` | `package` | Force-stop |
| `list` | `include_system` | Apps installées |
| `install` | `apk_path` | Installe un APK depuis le PC |
| `uninstall` | `package` | Désinstalle |
| `current` | — | App au premier plan |
| `url` | `url` | Ouvre une URL |
| `intent` | `action uri package extras` | Intent Android |
| `settings` | `section` | Paramètres (`main wifi bluetooth display…`) |

---

### `android_files` — Fichiers

| Action | Params | Description |
|--------|--------|-------------|
| `push` | `local_path remote_path` | PC → téléphone |
| `push_b64` | `remote_path data` | Base64 → téléphone |
| `pull` | `remote_path local_path` | Téléphone → PC |
| `pull_b64` | `remote_path` | Téléphone → base64 |
| `list` | `directory` | Contenu d'un dossier |

---

### `android_system` — Système & Réseau

| Action | Params | Description |
|--------|--------|-------------|
| `shell` | `command` | Shell ADB |
| `logs` | `lines package` | Logcat |
| `battery` | — | Niveau et état de charge |
| `clipboard_get` | — | Lit le presse-papier |
| `clipboard_set` | `text` | Écrit dans le presse-papier |
| `volume` | `level stream` | Volume |
| `rotation` | `rotation` | Rotation écran (0-3) |
| `wifi` | `enabled` | WiFi on/off |
| `bluetooth` | `enabled` | Bluetooth on/off |
| `mobile_data` | `enabled` | Data mobile on/off |
| `notifications` | — | Notifications actives |
| `gps` | `lat lng` | GPS fictif |
| `sensors` | `sensor` | Accéléro, gyro, lumière… |
| `wifi_list` | — | Réseaux WiFi disponibles |
| `wifi_connect` | `ssid password` | Connexion WiFi |
| `contacts` | `search limit` | Contacts |
| `sms` | `to message` | SMS (confirmation sur le téléphone) |

---

### `android_automation` — Batch & Macros

| Action | Params | Description |
|--------|--------|-------------|
| `batch` | `actions stop_on_error` | N actions en un appel |
| `macro_start` | `name` | Démarre l'enregistrement |
| `macro_record` | `action …params` | Ajoute une action |
| `macro_stop` | — | Sauvegarde |
| `macro_list` | — | Liste les macros |
| `macro_replay` | `name delay_ms` | Rejoue |
| `macro_delete` | `name` | Supprime |

---

## Viewer live — scrcpy 90fps

```bash
python viewer.py                  # device auto-détecté, 90fps, interactif
python viewer.py --fps 60         # 60fps
python viewer.py --record         # enregistre en .mp4
python viewer.py --record out.mp4 # fichier nommé
python viewer.py --multi          # un viewer par device connecté
python viewer.py --no-control     # lecture seule
```

| Contrôle | Action |
|----------|--------|
| Clic gauche | Tap |
| Glisser | Swipe |
| Clic droit | BACK |
| Scroll | Scroll |
| `Alt+H` | HOME |
| `Alt+S` | Screenshot → clipboard PC |
| `Alt+F` | Fullscreen |
| `Alt+R` | Rotation |

---

## Tests

```bash
# Unitaires (aucun device requis)
pytest tests/test_server_unit.py -v      # 94 tests

# Intégration (device ADB requis)
pytest tests/test_integration.py -v
```

---

## Structure du projet

```
android-mcp/
├── server.py              # Serveur MCP — 7 outils
├── viewer.py              # Viewer scrcpy 90fps interactif
├── mcp_config.py          # Générateur de config JSON
├── device_manager.py      # Gestion multi-device
├── relay.py               # ⚠️ LEGACY — companion fallback uniquement
├── requirements.txt
├── pyproject.toml
├── WIFI_PAIRING.md
├── backends/
│   ├── adb_backend.py
│   └── companion_backend.py
├── AppCompagnon/          # App Flutter (ARCHIVED — fallback)
├── examples/
│   ├── agent_loop.py      # Automatisation autonome
│   └── whatsapp_auto.py   # Exemple WhatsApp
└── tests/
    ├── conftest.py
    ├── test_server_unit.py   # 94 tests unitaires
    └── test_integration.py
```

---

## Exemples

```python
# WhatsApp — envoyer un message
await android_app("launch", {"package": "com.whatsapp"})
await android_interact("find", {"text": "Alice"})
await android_interact("type", {"text": "Bonjour !"})
await android_interact("key",  {"key": "ENTER"})

# Batch en un seul appel
await android_automation("batch", {"actions": [
    {"action": "key",  "key": "HOME"},
    {"action": "tap",  "x": 540, "y": 200},
    {"action": "type", "text": "recherche"},
    {"action": "key",  "key": "ENTER"},
]})

# Macro : enregistrer + rejouer
await android_automation("macro_start",  {"name": "login"})
await android_automation("macro_record", {"action": "tap",  "x": 540, "y": 400})
await android_automation("macro_record", {"action": "type", "text": "password"})
await android_automation("macro_stop")
await android_automation("macro_replay", {"name": "login"})
```

Voir `examples/whatsapp_auto.py` et `examples/agent_loop.py` pour des cas complets.

---

## Licence

MIT
