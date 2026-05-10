"""
viewer.py — Miroir Android haute performance (scrcpy)
======================================================
Lance scrcpy avec les paramètres optimaux pour le setup Android MCP.

Usage :
    python viewer.py                        # device auto-détecté, 90 fps
    python viewer.py --fps 60               # 60 fps
    python viewer.py --fps 30               # 30 fps (WiFi faible)
    python viewer.py --device <serial>      # device spécifique
    python viewer.py --bitrate 4M           # bitrate réduit (WiFi lent)
    python viewer.py --no-control           # lecture seule (pas de contrôle)
    python viewer.py --record               # enregistre la vidéo sur le PC
    python viewer.py --record output.mp4    # enregistre vers un fichier nommé
    python viewer.py --multi                # affiche tous les devices en même temps
    python viewer.py --check                # vérifie scrcpy sans lancer

Contrôles dans la fenêtre scrcpy :
    Clic gauche       → Tap
    Clic droit        → BACK
    Glisser           → Swipe
    Scroll            → Scroll
    Alt+H             → HOME
    Alt+B             → BACK
    Alt+A             → APP_SWITCH (recents)
    Alt+N             → déployer/replier le volet des notifications
    Alt+F             → Plein écran
    Alt+R             → Rotation
    Alt+S             → Capture d'écran → clipboard PC
    Alt+Z             → Activer/désactiver le mode control
    Ctrl+C / fermer   → Quitte le viewer
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).parent

_WINGET_SCRCPY_ID = "Genymobile.scrcpy"
_SCRCPY_DOCS_URL  = "https://github.com/Genymobile/scrcpy"


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _find_scrcpy() -> str | None:
    """Retourne le chemin de scrcpy ou None."""
    # 1. PATH système (cas normal)
    path = shutil.which("scrcpy")
    if path:
        return path

    # 2. Dossiers WinGet (glob — indépendant de la version)
    username = os.environ.get("USERNAME", os.environ.get("USER", ""))
    winget_bases = [
        Path(os.environ.get("LOCALAPPDATA", f"C:/Users/{username}/AppData/Local"))
        / "Microsoft" / "WinGet" / "Packages",
        Path(os.environ.get("PROGRAMFILES", "C:/Program Files"))
        / "Microsoft" / "WinGet" / "Packages",
    ]
    for base in winget_bases:
        for exe in base.glob("Genymobile.scrcpy*/*/scrcpy.exe"):
            return str(exe)
        for exe in base.glob("Genymobile.scrcpy*/*/scrcpy.EXE"):
            return str(exe)

    # 3. Chemins fixes classiques
    fixed = [
        r"C:\Program Files\scrcpy\scrcpy.exe",
        r"C:\Program Files (x86)\scrcpy\scrcpy.exe",
        rf"C:\Users\{username}\scrcpy\scrcpy.exe",
    ]
    for c in fixed:
        if Path(c).exists():
            return c

    return None


def _install_scrcpy() -> bool:
    """Tente d'installer scrcpy via winget."""
    print("  Installation de scrcpy via winget...")
    r = subprocess.run(
        ["winget", "install", _WINGET_SCRCPY_ID,
         "--silent", "--accept-package-agreements", "--accept-source-agreements"],
        capture_output=False,
    )
    if r.returncode != 0:
        return False
    # Recharger le PATH
    import ctypes
    HWND_BROADCAST   = 0xFFFF
    WM_SETTINGCHANGE = 0x001A
    ctypes.windll.user32.SendMessageW(HWND_BROADCAST, WM_SETTINGCHANGE, 0, "Environment")
    return _find_scrcpy() is not None


def _ensure_scrcpy() -> str:
    """Retourne le chemin de scrcpy, installe si nécessaire."""
    path = _find_scrcpy()
    if path:
        return path
    print("\n⚠️  scrcpy non trouvé dans le PATH.")
    print(f"   Documentation : {_SCRCPY_DOCS_URL}")
    print()
    ans = input("Installer scrcpy maintenant via winget ? [O/n] ").strip().lower()
    if ans in ("", "o", "oui", "y", "yes"):
        if _install_scrcpy():
            path = _find_scrcpy()
            if path:
                print("  ✅ scrcpy installé avec succès.")
                return path
        print("  ❌ Installation échouée. Lance manuellement :")
        print("     winget install Genymobile.scrcpy")
    sys.exit(1)


def _get_device_serial(requested: str | None) -> str:
    """Retourne le serial du device à utiliser."""
    sys.path.insert(0, str(_ROOT))
    try:
        from device_manager import get_manager
        dm = get_manager()
        if requested:
            dm.select_device(requested)
            return requested
        serial = dm.get_selected_serial()
        if serial:
            return serial
        devices = [d for d in dm.list_devices() if d.get("ready") and not d.get("error")]
        if not devices:
            print("❌ Aucun device Android connecté.")
            print("   Connecte un téléphone (USB ou WiFi ADB) et relance.")
            sys.exit(1)
        if len(devices) == 1:
            return devices[0]["serial"]
        print("\nPlusieurs devices disponibles :")
        for i, d in enumerate(devices):
            print(f"  [{i+1}] {d['serial']}  {d.get('model', '')}  ({d.get('transport', '')})")
        choice = input(f"\nChoix [1-{len(devices)}] : ").strip()
        try:
            idx = int(choice) - 1
            return devices[idx]["serial"]
        except (ValueError, IndexError):
            return devices[0]["serial"]
    except Exception as e:
        print(f"❌ Erreur device_manager : {e}")
        sys.exit(1)


def _get_device_label(serial: str) -> str:
    """Retourne un label lisible pour le device."""
    try:
        sys.path.insert(0, str(_ROOT))
        from device_manager import get_manager
        info = get_manager().get_device_info(serial)
        model = info.get("model", "")
        ver   = info.get("android_version", "")
        return f"{model} — {ver}" if model else serial
    except Exception:
        return serial


def _build_scrcpy_cmd(
    scrcpy_path: str,
    serial: str,
    fps: int,
    bitrate: str,
    no_control: bool,
    title: str,
    record: str | None = None,
) -> list[str]:
    """Construit la commande scrcpy optimisée."""
    cmd = [
        scrcpy_path,
        "--serial", serial,
        "--max-fps", str(fps),
        "--video-bit-rate", bitrate,
        "--no-audio",
        "--stay-awake",
        "--window-title", title,
        "--shortcut-mod", "lalt",
    ]

    # H264 explicite (meilleure compatibilité + faible latence)
    cmd += ["--video-codec", "h264"]

    # Renderer GPU (Windows)
    if sys.platform == "win32":
        cmd += ["--render-driver", "direct3d"]

    if no_control:
        cmd += ["--no-control"]

    if record:
        cmd += ["--record", record]

    return cmd


def _launch_multi(scrcpy_path: str, args) -> None:
    """Lance un scrcpy par device connecté, côte à côte."""
    sys.path.insert(0, str(_ROOT))
    try:
        from device_manager import get_manager
        devices = [d for d in get_manager().list_devices() if d.get("ready")]
    except Exception as e:
        print(f"❌ Impossible de lister les devices : {e}")
        sys.exit(1)

    if not devices:
        print("❌ Aucun device connecté.")
        sys.exit(1)

    print(f"\n  Mode multi-device — {len(devices)} device(s) détecté(s) :")
    for d in devices:
        print(f"    • {d['serial']}  {d.get('model', '')}")
    print()

    procs = []
    for i, d in enumerate(devices):
        serial = d["serial"]
        label  = d.get("model", serial[:20])
        title  = f"MCP [{i+1}/{len(devices)}] {label}"
        cmd = _build_scrcpy_cmd(
            scrcpy_path=scrcpy_path,
            serial=serial,
            fps=args.fps,
            bitrate=args.bitrate,
            no_control=getattr(args, "no_control", False),
            title=title,
        )
        print(f"  ▶ Lancement viewer {i+1}/{len(devices)} : {label}")
        procs.append(subprocess.Popen(cmd))

    print(f"\n  {len(procs)} viewer(s) ouverts. Ferme les fenêtres scrcpy ou Ctrl+C.\n")
    try:
        for p in procs:
            p.wait()
    except KeyboardInterrupt:
        print("\n  Arrêt demandé — fermeture des viewers...")
        for p in procs:
            try:
                p.terminate()
            except Exception:
                pass


def _print_banner(
    serial: str, label: str, fps: int, bitrate: str, no_control: bool,
    record: str | None = None,
):
    w = 62
    print("=" * w)
    print(f"  Android MCP — Viewer Live")
    print(f"  Device  : {label}")
    print(f"  Serial  : {serial}")
    print(f"  FPS     : {fps}   Bitrate : {bitrate}")
    print(f"  Mode    : {'lecture seule' if no_control else 'contrôle interactif'}")
    if record:
        print(f"  Enregistrement → {record}")
    print("=" * w)
    if not no_control:
        print("  Contrôles :")
        print("    Clic gauche  → Tap       |  Clic droit  → BACK")
        print("    Glisser      → Swipe     |  Scroll      → Scroll")
        print("    Alt+H → HOME  Alt+A → Recents  Alt+F → Fullscreen")
        print("    Alt+S → Screenshot (clipboard)  Alt+R → Rotation")
    print("=" * w)
    print("  Ferme la fenêtre scrcpy ou Ctrl+C pour quitter.")
    print()


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Viewer Android haute performance (scrcpy)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--device", "-d",  default=None,  help="Serial ADB du device")
    parser.add_argument("--fps",    "-f",  type=int, default=90, help="FPS max (défaut: 90)")
    parser.add_argument("--bitrate","-b",  default="8M",  help="Bitrate vidéo (défaut: 8M)")
    parser.add_argument("--no-control", action="store_true", help="Mode lecture seule")
    parser.add_argument("--record",  "-r", nargs="?", const=True,
                        help="Enregistrer la vidéo sur le PC (optionnel: chemin .mp4)")
    parser.add_argument("--multi",   "-m", action="store_true",
                        help="Ouvrir un viewer pour chaque device connecté")
    parser.add_argument("--check",       action="store_true", help="Vérifier scrcpy sans lancer")
    args = parser.parse_args()

    # ── Vérifier / installer scrcpy ───────────────────────────────────────────
    scrcpy_path = _ensure_scrcpy()

    if args.check:
        r = subprocess.run([scrcpy_path, "--version"], capture_output=True, text=True)
        version_line = r.stdout.splitlines()[0] if r.stdout else "version inconnue"
        print(f"✅ {version_line}")
        print(f"   Chemin : {scrcpy_path}")
        sys.exit(0)

    # ── Mode multi-device ─────────────────────────────────────────────────────
    if args.multi:
        _launch_multi(scrcpy_path, args)
        return

    # ── Sélection device ──────────────────────────────────────────────────────
    serial = _get_device_serial(args.device)
    label  = _get_device_label(serial)
    title  = f"Android MCP — {label}"

    # ── Résolution du chemin d'enregistrement ─────────────────────────────────
    record_path: str | None = None
    if args.record:
        if isinstance(args.record, str):
            record_path = args.record
        else:
            ts = int(time.time())
            record_path = str(_ROOT / f"record_{ts}.mp4")

    _print_banner(serial, label, args.fps, args.bitrate, args.no_control, record_path)

    # ── Construction de la commande ───────────────────────────────────────────
    cmd = _build_scrcpy_cmd(
        scrcpy_path=scrcpy_path,
        serial=serial,
        fps=args.fps,
        bitrate=args.bitrate,
        no_control=args.no_control,
        title=title,
        record=record_path,
    )

    print(f"  Lancement : {' '.join(cmd[:6])} ...")
    print()

    # ── Boucle de relance (backoff exponentiel, max 30s) ─────────────────────
    restart_count = 0
    delay = 2
    while True:
        try:
            start = time.time()
            proc = subprocess.run(cmd)
            uptime = time.time() - start

            if proc.returncode == 0:
                print("\n  Viewer fermé proprement.")
                if record_path:
                    print(f"  Enregistrement sauvegardé → {record_path}")
                break

            restart_count += 1
            # Si le viewer a tourné > 5s, on remet le délai à 2s (connexion stable)
            if uptime > 5:
                delay = 2
            else:
                delay = min(delay * 2, 30)

            print(f"\n  scrcpy s'est arrêté (code {proc.returncode}). Relance #{restart_count} dans {delay}s...")
            time.sleep(delay)
        except KeyboardInterrupt:
            print("\n  Arrêt demandé (Ctrl+C).")
            break
        except FileNotFoundError:
            print(f"\n❌ scrcpy introuvable à : {scrcpy_path}")
            break


if __name__ == "__main__":
    main()
