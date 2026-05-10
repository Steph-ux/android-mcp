import asyncio
import base64
import os
import sys
import time
import logging
from typing import Optional
from dotenv import load_dotenv

import aiohttp
from google import genai

# Load env variables (for GEMINI_API_KEY)
load_dotenv()

# Fix console encoding on Windows
if sys.platform == "win32":
    import io as _io
    sys.stdout = _io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = _io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [bot] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("trading_bot")

RELAY_URL = "http://localhost:8090"

class RelayClient:
    """Client HTTP pour envoyer des tap/swipe et récupérer le screen à l'app compagnon."""
    def __init__(self, url: str = RELAY_URL):
        self.url = url
        self._session: Optional[aiohttp.ClientSession] = None

    async def start(self):
        self._session = aiohttp.ClientSession()

    async def close(self):
        if self._session:
            await self._session.close()

    async def cmd(self, action: str, **kwargs) -> dict:
        payload = {"action": action, **kwargs}
        try:
            async with self._session.post(
                f"{self.url}/command", json=payload,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as r:
                return await r.json()
        except Exception as e:
            log.warning(f"Relay erreur ({action}): {e}")
            return {"success": False, "error": str(e)}

    async def get_frame(self) -> Optional[bytes]:
        result = await self.cmd("get_live_frame")
        if result.get("success") and result.get("data"):
            return base64.b64decode(result["data"])
        return None

    async def tap(self, x: int, y: int):
        await self.cmd("tap", x=x, y=y)
        await asyncio.sleep(0.5)

    async def input_text(self, text: str):
        # Utilise directement ADB pour l'input text
        import subprocess
        subprocess.run(["adb", "shell", "input", "text", str(text)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        await asyncio.sleep(0.5)

    async def press_key(self, keycode: int):
        import subprocess
        subprocess.run(["adb", "shell", "input", "keyevent", str(keycode)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # Petit sleep pour s'assurer que l'UI réagit
        await asyncio.sleep(0.1)

class GeminiStrategist:
    """Consulte Gemini pour analyser le graphique."""
    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("La clé API Gemini est introuvable. Assure-toi que .env contient GEMINI_API_KEY=...")
        self.client = genai.Client(api_key=api_key)
    
    def consult(self, frame_bytes: bytes) -> str:
        """Envoie le screenshot à Gemini et récupère la décision."""
        prompt = (
            "Tu es un trader professionnel scalpant sur MT5. "
            "Examine ce graphique (chandeliers 1 minute M1). "
            "Identifie les supports/résistances et les cassures (Breakout). "
            "Si tu détectes une vraie opportunité, réponds avec STRICTEMENT l'un de ces formats (sur une seule ligne) :\n"
            "BUY;SL_VALUE;TP_VALUE\n"
            "SELL;SL_VALUE;TP_VALUE\n"
            "WAIT\n"
            "Exemple de réponse si le prix est à 34944 et que tu veux vendre avec un SL au-dessus (ex:35000) et TP en bas (ex:34500):\n"
            "SELL;35000;34500\n"
            "Tu DOIS inclure le SL et TP s'il y a un ordre."
        )

        try:
            response = self.client.models.generate_content(
                model='gemini-2.5-flash',
                contents=[
                    genai.types.Part.from_bytes(data=frame_bytes, mime_type='image/png'),
                    prompt
                ]
            )
            return response.text.strip().upper()
        except Exception as e:
            log.error(f"Gemini error: {e}")
            return "WAIT"

class TradingAgent:
    def __init__(self):
        self.relay = RelayClient()
        self.strategist = GeminiStrategist()
        self.running = False
        
        # Coordonnées déduites par l'exploration dynamique :
        self.COORDS = {
            "tab_charts": (330, 2150),
            "tab_trade": (540, 2150),
            "btn_new_order": (1007, 154),
            "field_sl": (281, 706),
            "field_tp": (799, 706),
            "btn_buy": (810, 2196),
            "btn_sell": (269, 2196),
        }

    async def setup(self):
        await self.relay.start()
        # Assurer qu'on est sur les Charts
        await self.relay.tap(*self.COORDS["tab_charts"])
        await asyncio.sleep(1)

    async def execute_trade(self, action: str, sl: str, tp: str):
        log.info(f"🚀 Execution d'un ordre {action} avec SL={sl} et TP={tp}...")
        
        # 1. Aller sur le tab Trade
        await self.relay.tap(*self.COORDS["tab_trade"])
        await asyncio.sleep(1) # Laisse le temps à l'écran Trade de s'ouvrir
        
        # 2. Bouton "New Order" (+)
        await self.relay.tap(*self.COORDS["btn_new_order"])
        await asyncio.sleep(1) # Laisse le temps à l'écran Order de s'ouvrir
        
        # 3. Entrer SL (effacer le texte existant d'abord)
        await self.relay.tap(*self.COORDS["field_sl"])
        # Pour vider un champ dans MT5, on recule avec des keyevents DELETE (67)
        for _ in range(10): 
            await self.relay.press_key(67)
        await self.relay.input_text(sl)

        # 4. Entrer TP (effacer le texte existant d'abord)
        await self.relay.tap(*self.COORDS["field_tp"])
        for _ in range(10): 
            await self.relay.press_key(67)
        await self.relay.input_text(tp)

        # 5. Executer l'ordre
        if action == "BUY":
            await self.relay.tap(*self.COORDS["btn_buy"])
        elif action == "SELL":
            await self.relay.tap(*self.COORDS["btn_sell"])

        log.info("✅ Ordre executé ! Retour au graphique dans 5 secondes...")
        await asyncio.sleep(5)
        # Retour aux charts pour reprendre l'analyse
        await self.relay.tap(*self.COORDS["tab_charts"])

    async def run(self):
        await self.setup()
        self.running = True
        
        log.info("🎯 Bot Trading Démarré. Analyse toutes les 30s.")
        try:
            while self.running:
                # Récupère l'image
                frame = await self.relay.get_frame()
                if not frame:
                    log.warning("Impossible d'obtenir l'image du flux ADB.")
                    await asyncio.sleep(5)
                    continue

                # Analyse par Gemini
                log.info("📊 Analyse du graphique en cours...")
                # On bloque l'event loop le temps d'attendre Gemini (on aurait pu typer asynchrone mais pas de async-genai dispo nativement sans SDK 2.x beta)
                decision = await asyncio.to_thread(self.strategist.consult, frame)
                log.info(f"🤖 Décision IA : {decision}")

                if decision.startswith("BUY") or decision.startswith("SELL"):
                    # Parse : ACTION;SL;TP
                    parts = decision.split(";")
                    if len(parts) >= 3:
                        action = parts[0]
                        sl = parts[1]
                        tp = parts[2]
                        await self.execute_trade(action, sl, tp)
                        # Pause prolongée après un trade
                        await asyncio.sleep(60)

                await asyncio.sleep(30) # Attend 30 secondes entre chaque check min
                
        except KeyboardInterrupt:
            pass
        finally:
            self.running = False
            await self.relay.close()

if __name__ == "__main__":
    agent = TradingAgent()
    try:
        asyncio.run(agent.run())
    except KeyboardInterrupt:
        print("\nArrêt par l'utilisateur.")
