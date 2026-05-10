"""
examples/agent_loop.py — Boucle autonome de contrôle Android
=============================================================
Boucle Python qui utilise l'API android-mcp directement (7 outils).
Utile pour automatiser des actions répétitives sans passer par un LLM.

Usage :
    python examples/agent_loop.py --task scroll_feed
    python examples/agent_loop.py --task open_app --package com.instagram.android
    python examples/agent_loop.py --task screenshot_loop --interval 2
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from device_manager import get_manager
from server import (
    android_app,
    android_interact,
    android_screen,
    android_system,
    android_automation,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [agent] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("agent_loop")


# ─── Helpers ──────────────────────────────────────────────────────────────────

async def screenshot_to_file(path: str | Path, device_id: str | None = None):
    from mcp.types import ImageContent
    result = await android_screen("screenshot", device_id=device_id)
    if isinstance(result, list) and isinstance(result[0], ImageContent):
        raw = base64.b64decode(result[0].data)
        Path(path).write_bytes(raw)
        log.info("Screenshot → %s (%d bytes)", path, len(raw))
        return raw
    log.error("Screenshot failed: %s", result)
    return None


async def tap(x: float, y: float, device_id: str | None = None):
    import json
    r = json.loads(await android_interact("tap", {"x": x, "y": y}, device_id))
    return r.get("success", False)


async def swipe_up(device_id: str | None = None):
    import json
    r = json.loads(await android_interact(
        "swipe", {"x1": 540, "y1": 1600, "x2": 540, "y2": 800, "duration_ms": 400},
        device_id,
    ))
    return r.get("success", False)


async def press_home(device_id: str | None = None):
    import json
    await android_interact("key", {"key": "HOME"}, device_id)


# ─── Tâches ───────────────────────────────────────────────────────────────────

async def task_scroll_feed(device_id: str | None = None, count: int = 10):
    """Scrolle le fil d'actualité N fois."""
    log.info("Scroll feed — %d swipes", count)
    for i in range(count):
        await swipe_up(device_id)
        await asyncio.sleep(0.8)
        log.info("Swipe %d/%d", i + 1, count)


async def task_open_app(package: str, device_id: str | None = None):
    """Lance une application par son package."""
    import json
    log.info("Lancement de %s", package)
    r = json.loads(await android_app("launch", {"package": package}, device_id))
    if r.get("success"):
        log.info("✅ App lancée")
    else:
        log.error("❌ Échec : %s", r.get("error"))


async def task_screenshot_loop(interval: float = 2.0, count: int = 5, device_id: str | None = None):
    """Prend une capture d'écran toutes les N secondes."""
    out_dir = ROOT / "screenshots"
    out_dir.mkdir(exist_ok=True)
    log.info("Screenshot loop → %s (interval=%.1fs, count=%d)", out_dir, interval, count)
    for i in range(count):
        ts = int(time.time())
        await screenshot_to_file(out_dir / f"frame_{ts}.png", device_id)
        if i < count - 1:
            await asyncio.sleep(interval)


async def task_batch_demo(device_id: str | None = None):
    """Démonstration du batch — HOME + tap + screenshot en un appel."""
    import json
    log.info("Batch demo")
    r = json.loads(await android_automation("batch", {
        "actions": [
            {"action": "key",        "key": "HOME"},
            {"action": "tap",        "x": 540, "y": 960},
            {"action": "screenshot"},
        ]
    }, device_id))
    log.info("Batch : %d actions, succès : %s",
             r["count"], all(a.get("success") for a in r["results"]))


# ─── Main ─────────────────────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(description="Agent loop Android MCP")
    parser.add_argument("--task",     default="batch_demo",
                        choices=["scroll_feed", "open_app", "screenshot_loop", "batch_demo"])
    parser.add_argument("--device",   default=None, help="Serial ADB (optionnel)")
    parser.add_argument("--package",  default="com.instagram.android")
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("--count",    type=int, default=5)
    args = parser.parse_args()

    # Sélection device
    dm = get_manager()
    if args.device:
        dm.select_device(args.device)
    else:
        devices = [d for d in dm.list_devices() if d.get("ready")]
        if not devices:
            print("❌ Aucun device ADB connecté.")
            sys.exit(1)
        dm.select_device(devices[0]["serial"])
        log.info("Device auto-sélectionné : %s", devices[0]["serial"])

    device_id = dm.get_selected_serial()

    if args.task == "scroll_feed":
        await task_scroll_feed(device_id, args.count)
    elif args.task == "open_app":
        await task_open_app(args.package, device_id)
    elif args.task == "screenshot_loop":
        await task_screenshot_loop(args.interval, args.count, device_id)
    elif args.task == "batch_demo":
        await task_batch_demo(device_id)


if __name__ == "__main__":
    asyncio.run(main())
