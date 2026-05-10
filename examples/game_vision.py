"""
game_vision.py — Détection visuelle locale pour gaming
========================================================
Analyse les frames ADB sans passer par Claude.
Dépendances : pip install opencv-python numpy pillow
"""

import cv2
import numpy as np
from dataclasses import dataclass, field
from typing import Optional
import json
import io
from pathlib import Path
from PIL import Image


@dataclass
class Detection:
    label: str
    x: int
    y: int
    w: int
    h: int
    confidence: float = 1.0

    @property
    def center(self):
        return (self.x + self.w // 2, self.y + self.h // 2)

    @property
    def area(self):
        return self.w * self.h


@dataclass
class GameState:
    enemies:      list[Detection] = field(default_factory=list)
    items:        list[Detection] = field(default_factory=list)
    hp_percent:   float = 1.0
    ammo_ok:      bool  = True
    zone_warning: bool  = False
    raw_frame:    Optional[np.ndarray] = None

    @property
    def nearest_enemy(self) -> Optional[Detection]:
        if not self.enemies:
            return None
        cx, cy = (self.raw_frame.shape[1] // 2, self.raw_frame.shape[0] // 2) if self.raw_frame is not None else (540, 960)
        return min(self.enemies, key=lambda e: abs(e.center[0] - cx) + abs(e.center[1] - cy))


class GameVision:
    """
    Moteur de vision par couleur/forme — ~5-15ms/frame sur CPU.

    Chaque profil de jeu est un fichier JSON dans game_profiles/.
    Sinon, utilise les profils intégrés (Free Fire, MLBB, CoD Mobile).
    """

    BUILTIN_PROFILES = {
        "freefire": {
            "name": "Free Fire",
            "screen_size": [1080, 1920],
            "roi": {"x": 0, "y": 0, "w": 1.0, "h": 0.85},
            # Couleurs ennemies en HSV [H_min, S_min, V_min, H_max, S_max, V_max]
            "enemy_colors": [
                [0, 120, 80, 10, 255, 255],    # Rouge
                [165, 120, 80, 180, 255, 255],  # Rouge-rose
            ],
            "hp_roi": {"x": 0.02, "y": 0.88, "w": 0.25, "h": 0.04},
            "hp_color": [40, 80, 80, 90, 255, 255],  # Vert
            "zone_color": [100, 80, 40, 135, 255, 255],
            "item_colors": [
                [20, 100, 150, 40, 255, 255],  # Or
                [15, 80, 180, 30, 255, 255],   # Jaune
            ],
            "enemy_min_area": 200,
            "item_min_area": 100,
        },
        "cod_mobile": {
            "name": "CoD Mobile",
            "screen_size": [1080, 1920],
            "roi": {"x": 0, "y": 0, "w": 1.0, "h": 0.9},
            "enemy_colors": [
                [0, 150, 100, 15, 255, 255],
                [160, 150, 100, 180, 255, 255],
            ],
            "hp_roi": {"x": 0.03, "y": 0.88, "w": 0.3, "h": 0.05},
            "hp_color": [35, 80, 80, 85, 255, 255],
            "zone_color": [100, 60, 40, 140, 255, 255],
            "item_colors": [[15, 80, 150, 35, 255, 255]],
            "enemy_min_area": 300,
            "item_min_area": 80,
        },
        "mlbb": {
            "name": "Mobile Legends",
            "screen_size": [1280, 720],
            "roi": {"x": 0, "y": 0, "w": 1.0, "h": 0.85},
            "enemy_colors": [
                [0, 120, 100, 12, 255, 255],
            ],
            "hp_roi": {"x": 0.01, "y": 0.92, "w": 0.2, "h": 0.04},
            "hp_color": [40, 70, 80, 90, 255, 255],
            "zone_color": [],
            "item_colors": [[20, 80, 150, 45, 255, 255]],
            "enemy_min_area": 150,
            "item_min_area": 50,
        },
    }

    def __init__(self, game: str = "freefire", profile_path: Optional[str] = None):
        if profile_path and Path(profile_path).exists():
            with open(profile_path) as f:
                self.profile = json.load(f)
        else:
            self.profile = self.BUILTIN_PROFILES.get(game, self.BUILTIN_PROFILES["freefire"])
        self._debug = False

    def enable_debug(self, enabled: bool = True):
        self._debug = enabled

    def bytes_to_frame(self, raw: bytes) -> np.ndarray:
        arr = np.frombuffer(raw, np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if frame is None:
            img = Image.open(io.BytesIO(raw)).convert("RGB")
            frame = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
        return frame

    def analyze(self, raw: bytes) -> GameState:
        """
        Analyse principale — appeler dans la boucle autonome.
        Retourne un GameState avec toutes les détections.
        Temps moyen : 8-20ms selon résolution.
        """
        frame = self.bytes_to_frame(raw)
        p = self.profile
        h, w = frame.shape[:2]

        roi_cfg = p.get("roi", {"x": 0, "y": 0, "w": 1.0, "h": 0.85})
        rx = int(roi_cfg["x"] * w)
        ry = int(roi_cfg["y"] * h)
        rw = int(roi_cfg["w"] * w)
        rh = int(roi_cfg["h"] * h)
        roi = frame[ry:ry+rh, rx:rx+rw]

        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        state = GameState(raw_frame=frame)

        state.enemies = self._detect_by_colors(
            hsv, p.get("enemy_colors", []),
            p.get("enemy_min_area", 200),
            offset=(rx, ry), label="enemy"
        )
        state.items = self._detect_by_colors(
            hsv, p.get("item_colors", []),
            p.get("item_min_area", 80),
            offset=(rx, ry), label="item"
        )
        state.hp_percent = self._measure_hp(frame, p)

        if p.get("zone_color"):
            zone_pixels = self._count_color_pixels(hsv, p["zone_color"])
            state.zone_warning = zone_pixels > (rw * rh * 0.03)

        if self._debug:
            self._show_debug(frame, state)

        return state

    def _detect_by_colors(self, hsv, color_ranges, min_area, offset, label):
        detections = []
        combined_mask = None

        for cr in color_ranges:
            lo = np.array(cr[:3], dtype=np.uint8)
            hi = np.array(cr[3:], dtype=np.uint8)
            mask = cv2.inRange(hsv, lo, hi)
            combined_mask = mask if combined_mask is None else cv2.bitwise_or(combined_mask, mask)

        if combined_mask is None:
            return []

        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        combined_mask = cv2.morphologyEx(combined_mask, cv2.MORPH_CLOSE, kernel)
        combined_mask = cv2.morphologyEx(combined_mask, cv2.MORPH_OPEN, kernel)

        contours, _ = cv2.findContours(combined_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        ox, oy = offset

        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < min_area:
                continue
            x, y, w, h = cv2.boundingRect(cnt)
            confidence = min(1.0, area / (min_area * 10))
            detections.append(Detection(
                label=label,
                x=x + ox, y=y + oy,
                w=w, h=h,
                confidence=confidence,
            ))

        detections.sort(key=lambda d: d.area, reverse=True)
        return detections[:10]

    def _measure_hp(self, frame, profile):
        hp_roi_cfg = profile.get("hp_roi", {"x": 0.02, "y": 0.88, "w": 0.25, "h": 0.04})
        hp_color = profile.get("hp_color", [40, 80, 80, 90, 255, 255])
        fh, fw = frame.shape[:2]
        x = int(hp_roi_cfg["x"] * fw)
        y = int(hp_roi_cfg["y"] * fh)
        w = int(hp_roi_cfg["w"] * fw)
        h = int(hp_roi_cfg["h"] * fh)
        if w <= 0 or h <= 0:
            return 1.0
        hp_region = frame[y:y+h, x:x+w]
        hsv_hp = cv2.cvtColor(hp_region, cv2.COLOR_BGR2HSV)
        lo = np.array(hp_color[:3], dtype=np.uint8)
        hi = np.array(hp_color[3:], dtype=np.uint8)
        mask = cv2.inRange(hsv_hp, lo, hi)
        total = w * h
        filled = cv2.countNonZero(mask)
        return min(1.0, filled / max(total * 0.1, 1))

    def _count_color_pixels(self, hsv, color_range):
        lo = np.array(color_range[:3], dtype=np.uint8)
        hi = np.array(color_range[3:], dtype=np.uint8)
        mask = cv2.inRange(hsv, lo, hi)
        return cv2.countNonZero(mask)

    def _show_debug(self, frame, state):
        vis = frame.copy()
        for e in state.enemies:
            cv2.rectangle(vis, (e.x, e.y), (e.x+e.w, e.y+e.h), (0, 0, 255), 2)
            cv2.putText(vis, f"ENE {e.confidence:.1f}", (e.x, e.y-5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 255), 1)
        for it in state.items:
            cv2.rectangle(vis, (it.x, it.y), (it.x+it.w, it.y+it.h), (0, 255, 255), 1)
        hp_text = f"HP: {state.hp_percent*100:.0f}%"
        color = (0, 255, 0) if state.hp_percent > 0.5 else (0, 165, 255) if state.hp_percent > 0.25 else (0, 0, 255)
        cv2.putText(vis, hp_text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
        if state.zone_warning:
            cv2.putText(vis, "ZONE!", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 0, 0), 2)
        dh, dw = vis.shape[:2]
        if dh > 800:
            scale = 800 / dh
            vis = cv2.resize(vis, (int(dw*scale), 800))
        cv2.imshow("Android MCP — Vision debug", vis)
        cv2.waitKey(1)

    def save_calibration_screenshot(self, raw: bytes, path: str = "calibration.png"):
        frame = self.bytes_to_frame(raw)
        cv2.imwrite(path, frame)
        print(f"Frame sauvegarde : {path}")


def pick_color_range(image_path: str):
    """
    Outil de calibration interactif.
    Usage : python game_vision.py pick chemin_image.png
    Clique sur un pixel ennemi -> donne les valeurs HSV pour le profil.
    """
    img = cv2.imread(image_path)
    if img is None:
        print(f"Image introuvable : {image_path}")
        return
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    samples = []

    def on_click(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            pixel_hsv = hsv[y, x]
            pixel_bgr = img[y, x]
            samples.append(pixel_hsv)
            print(f"  Pixel ({x},{y}) -> HSV: {pixel_hsv}  BGR: {pixel_bgr}")
            if len(samples) >= 2:
                h_vals = [s[0] for s in samples]
                s_vals = [s[1] for s in samples]
                v_vals = [s[2] for s in samples]
                print(f"\n  Plage HSV suggeree :")
                print(f"  [{max(0, min(h_vals)-10)}, {max(0, min(s_vals)-30)}, {max(0, min(v_vals)-30)},")
                print(f"   {min(180, max(h_vals)+10)}, 255, 255]")

    cv2.namedWindow("Calibration — clique sur les pixels ennemis")
    cv2.setMouseCallback("Calibration — clique sur les pixels ennemis", on_click)
    print("Clique sur les pixels representant les ennemis. Q pour quitter.")
    while True:
        cv2.imshow("Calibration — clique sur les pixels ennemis", img)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
    cv2.destroyAllWindows()


if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 3 and sys.argv[1] == "pick":
        pick_color_range(sys.argv[2])
    else:
        print("Usage: python game_vision.py pick <image.png>")
