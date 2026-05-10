"""
examples/whatsapp_auto.py — Automatisation WhatsApp via Android MCP
====================================================================
Démontre les capacités de l'agent IA pour contrôler WhatsApp :
- Ouvrir une conversation
- Envoyer un message
- Lire les messages reçus (OCR)
- Répondre automatiquement

Usage :
    python examples/whatsapp_auto.py --contact "Alice" --message "Bonjour !"
    python examples/whatsapp_auto.py --read 10          # lire les 10 derniers messages
    python examples/whatsapp_auto.py --auto-reply       # mode réponse auto (démo)
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
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

logging.basicConfig(level=logging.INFO, format="%(asctime)s [whatsapp] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("whatsapp_auto")

WHATSAPP_PKG = "com.whatsapp"


# ─── Helpers ──────────────────────────────────────────────────────────────────

async def ok(coro) -> dict:
    r = json.loads(await coro)
    if not r.get("success"):
        raise RuntimeError(r.get("error", "erreur inconnue"))
    return r


async def screenshot_bytes(device_id=None) -> bytes:
    from mcp.types import ImageContent
    result = await android_screen("screenshot", device_id=device_id)
    if isinstance(result, list) and isinstance(result[0], ImageContent):
        return base64.b64decode(result[0].data)
    raise RuntimeError("Screenshot échoué")


async def read_screen_text(device_id=None) -> str:
    r = await ok(android_screen("ocr", {"lang": "fra+eng"}, device_id))
    return r.get("data", "")


async def wait_stable(seconds: float = 1.5):
    """Attend que l'UI se stabilise."""
    await asyncio.sleep(seconds)


# ─── Tâches WhatsApp ──────────────────────────────────────────────────────────

async def open_whatsapp(device_id=None):
    """Ouvre WhatsApp et attend l'écran principal."""
    log.info("Ouverture de WhatsApp...")
    await ok(android_app("launch", {"package": WHATSAPP_PKG}, device_id))
    await wait_stable(2)

    # Vérifier que WhatsApp est bien au premier plan
    r = await ok(android_app("current", device_id=device_id))
    if WHATSAPP_PKG not in r["data"]:
        raise RuntimeError(f"WhatsApp ne s'est pas lancé (app actuelle : {r['data']})")
    log.info("WhatsApp ouvert.")


async def open_conversation(contact: str, device_id=None):
    """Ouvre la conversation avec un contact."""
    log.info("Recherche du contact : %s", contact)

    # Chercher dans la liste des discussions
    r = json.loads(await android_interact("find", {"text": contact, "partial_match": True}, device_id))
    if r.get("found"):
        log.info("Contact trouvé via recherche directe.")
        return

    # Fallback : utiliser la barre de recherche WhatsApp
    log.info("Contact non visible, utilisation de la recherche...")
    search_found = json.loads(
        await android_interact("find", {"text": "Rechercher", "partial_match": True}, device_id)
    )
    if not search_found.get("found"):
        # Essayer le bouton loupe
        await ok(android_interact("key", {"key": "MENU"}, device_id))
        await wait_stable(0.5)

    await ok(android_interact("type", {"text": contact}, device_id))
    await wait_stable(1)
    await ok(android_interact("find", {"text": contact, "partial_match": True}, device_id))
    await wait_stable(0.5)
    log.info("Conversation %s ouverte.", contact)


async def send_message(text: str, device_id=None):
    """Tape et envoie un message dans la conversation ouverte."""
    log.info("Envoi : %s", text[:50])

    # Cliquer dans le champ de message
    r = json.loads(await android_interact(
        "find", {"text": "Message", "partial_match": True}, device_id
    ))
    if not r.get("found"):
        # Fallback : taper en bas de l'écran (~90% de hauteur)
        size_r = await ok(android_screen("size", device_id=device_id))
        w = size_r["data"]["width"]
        h = size_r["data"]["height"]
        await ok(android_interact("tap", {"x": w * 0.5, "y": h * 0.9}, device_id))
    await wait_stable(0.3)

    # Saisir le message
    await ok(android_interact("type", {"text": text}, device_id))
    await wait_stable(0.3)

    # Envoyer (bouton Envoyer ou touche ENTER)
    sent = json.loads(await android_interact(
        "find", {"text": "Envoyer", "partial_match": True}, device_id
    ))
    if not sent.get("found"):
        await ok(android_interact("key", {"key": "ENTER"}, device_id))

    await wait_stable(0.5)
    log.info("Message envoyé.")


async def read_messages(device_id=None) -> str:
    """Lit le texte visible dans la conversation via OCR."""
    log.info("Lecture des messages visibles...")
    text = await read_screen_text(device_id)
    return text


async def scroll_up_messages(swipes: int = 3, device_id=None):
    """Remonte dans l'historique des messages."""
    size_r = await ok(android_screen("size", device_id=device_id))
    w = size_r["data"]["width"]
    h = size_r["data"]["height"]
    for _ in range(swipes):
        await ok(android_interact(
            "swipe", {"x1": w/2, "y1": h*0.3, "x2": w/2, "y2": h*0.7, "duration_ms": 300},
            device_id,
        ))
        await wait_stable(0.4)


async def take_conversation_screenshot(output_path: str, device_id=None):
    """Capture la conversation et l'enregistre."""
    raw = await screenshot_bytes(device_id)
    Path(output_path).write_bytes(raw)
    log.info("Screenshot → %s", output_path)


# ─── Scénarios complets ───────────────────────────────────────────────────────

async def scenario_send(contact: str, message: str, device_id=None):
    """Scénario : ouvrir WhatsApp, trouver le contact, envoyer un message."""
    await open_whatsapp(device_id)
    await open_conversation(contact, device_id)
    await send_message(message, device_id)
    log.info("✅ Message envoyé à %s : %s", contact, message)


async def scenario_read(contact: str, scroll_up: int = 0, device_id=None):
    """Scénario : ouvrir une conversation et lire les messages."""
    await open_whatsapp(device_id)
    await open_conversation(contact, device_id)
    if scroll_up:
        await scroll_up_messages(scroll_up, device_id)
    text = await read_messages(device_id)
    print(f"\n{'─'*50}")
    print(f"  Messages visibles — {contact}")
    print(f"{'─'*50}")
    print(text)
    print(f"{'─'*50}\n")
    return text


async def scenario_auto_reply(contact: str, keyword: str, reply: str, device_id=None):
    """
    Scénario : surveille une conversation et répond si le dernier message
    contient le keyword.
    """
    log.info("Mode surveillance : contact=%s keyword=%r", contact, keyword)
    await open_whatsapp(device_id)
    await open_conversation(contact, device_id)

    last_seen = ""
    while True:
        text = await read_messages(device_id)
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        last_line = lines[-1] if lines else ""

        if last_line != last_seen and keyword.lower() in last_line.lower():
            log.info("Keyword détecté : %r → réponse automatique", last_line)
            await send_message(reply, device_id)
            last_seen = last_line

        await asyncio.sleep(5)


# ─── Main ─────────────────────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(description="Automatisation WhatsApp via Android MCP")
    parser.add_argument("--contact",    default="",     help="Nom du contact")
    parser.add_argument("--message",    default="",     help="Message à envoyer")
    parser.add_argument("--read",       type=int, default=0, help="Lire N swipes d'historique")
    parser.add_argument("--auto-reply", action="store_true", help="Mode réponse auto")
    parser.add_argument("--keyword",    default="hello", help="Mot-clé à surveiller (auto-reply)")
    parser.add_argument("--reply",      default="Reçu !", help="Réponse automatique")
    parser.add_argument("--device",     default=None,   help="Serial ADB")
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
        log.info("Device : %s", devices[0]["serial"])

    device_id = dm.get_selected_serial()

    if args.auto_reply:
        if not args.contact:
            print("❌ --contact requis pour --auto-reply")
            sys.exit(1)
        await scenario_auto_reply(args.contact, args.keyword, args.reply, device_id)

    elif args.message and args.contact:
        await scenario_send(args.contact, args.message, device_id)

    elif args.read and args.contact:
        await scenario_read(args.contact, args.read, device_id)

    elif args.contact:
        await scenario_read(args.contact, 0, device_id)

    else:
        # Démo : ouvrir WhatsApp et lire l'écran principal
        await open_whatsapp(device_id)
        text = await read_messages(device_id)
        print("\n=== Écran WhatsApp ===")
        print(text[:500])
        print("=====================\n")


if __name__ == "__main__":
    asyncio.run(main())
