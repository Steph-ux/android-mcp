"""
mcp_config.py — Générateur de configuration MCP pour android-mcp
=================================================================
Lance ce script pour obtenir les blocs JSON à copier dans ton client IA.

Usage :
    python mcp_config.py              # affiche tout
    python mcp_config.py --client claude
    python mcp_config.py --client opencode
    python mcp_config.py --client windsurf
    python mcp_config.py --client cursor
    python mcp_config.py --write       # écrit les fichiers de config directement
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT    = Path(__file__).parent.resolve()
PYTHON  = sys.executable
SERVER  = ROOT / "server.py"


# ─── Blocs de config ─────────────────────────────────────────────────────────

def _block() -> dict:
    return {
        "command": PYTHON,
        "args": [str(SERVER)],
        "type": "stdio",
    }


def config_claude_desktop() -> dict:
    return {"mcpServers": {"android-mcp": _block()}}


def config_opencode() -> dict:
    return {"android-mcp": _block()}


def config_windsurf() -> dict:
    return {"mcpServers": {"android-mcp": _block()}}


def config_cursor() -> dict:
    return {"mcpServers": {"android-mcp": _block()}}


# ─── Chemins des fichiers de config ──────────────────────────────────────────

def _config_paths() -> dict[str, Path]:
    home = Path.home()
    appdata = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
    localdata = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
    return {
        "claude":    appdata / "Claude" / "claude_desktop_config.json",
        "opencode":  home / ".config" / "opencode" / "config.json",
        "windsurf":  appdata / "Windsurf" / "User" / "settings.json",
        "cursor":    appdata / "Cursor" / "User" / "settings.json",
    }


# ─── Helpers ─────────────────────────────────────────────────────────────────

_CLIENTS = {
    "claude":   ("Claude Desktop",  config_claude_desktop),
    "opencode": ("OpenCode",        config_opencode),
    "windsurf": ("Windsurf",        config_windsurf),
    "cursor":   ("Cursor",          config_cursor),
}


def _print_config(name: str, data: dict):
    print(f"\n{'─'*60}")
    print(f"  {name}")
    print(f"{'─'*60}")
    print(json.dumps(data, indent=2, ensure_ascii=False))


def _write_config(client_key: str, config_path: Path, data: dict):
    """Fusionne la config android-mcp dans le fichier existant."""
    existing = {}
    if config_path.exists():
        try:
            existing = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    # Fusion
    if "mcpServers" in data:
        existing.setdefault("mcpServers", {}).update(data["mcpServers"])
    else:
        existing.update(data)

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  ✅ Écrit : {config_path}")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Générateur de config MCP android-mcp")
    parser.add_argument("--client", "-c", choices=list(_CLIENTS.keys()),
                        help="Client IA cible (défaut : tous)")
    parser.add_argument("--write", "-w", action="store_true",
                        help="Écrire directement dans les fichiers de config")
    args = parser.parse_args()

    targets = {args.client: _CLIENTS[args.client]} if args.client else _CLIENTS
    paths   = _config_paths()

    print(f"\n{'='*60}")
    print(f"  Android MCP — Configuration")
    print(f"  Python  : {PYTHON}")
    print(f"  Server  : {SERVER}")
    print(f"{'='*60}")

    for key, (label, fn) in targets.items():
        data = fn()
        _print_config(label, data)
        if args.write:
            _write_config(key, paths[key], data)

    if not args.write:
        print(f"\n{'─'*60}")
        print("  💡 Copie le bloc correspondant à ton client IA.")
        print("  💡 Ou relance avec --write pour écrire automatiquement.")
        print(f"{'─'*60}\n")


if __name__ == "__main__":
    main()
