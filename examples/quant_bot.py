import os
import time
import json
import logging
import MetaTrader5 as mt5
import pandas as pd
import pandas_ta as ta # Librairie de calcul des indicateurs techniques
from dotenv import load_dotenv
import google.genai as genai

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("QuantBot")

load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")
SYMBOL = os.getenv("MT5_SYMBOL", "Volatility 75 Index")
LOT_SIZE = 0.01

class QuantStrategist:
    def __init__(self):
        if not API_KEY:
            raise ValueError("La cle API Gemini est introuvable.")
        self.client = genai.Client(api_key=API_KEY)

    def analyze(self, m1_df: pd.DataFrame, h1_df: pd.DataFrame) -> dict:
        # 1. Pre-calculs Mathematiques M1
        m1_df['RSI_14'] = m1_df.ta.rsi(length=14)
        m1_df['EMA_9'] = m1_df.ta.ema(length=9)
        m1_df['EMA_21'] = m1_df.ta.ema(length=21)
        m1_df['ATR_14'] = m1_df.ta.atr(length=14)
        
        # 2. Pre-calculs Mathematiques H1
        h1_df['EMA_50'] = h1_df.ta.ema(length=50)
        h1_df['EMA_200'] = h1_df.ta.ema(length=200)

        # Valeurs actuelles
        current_m1 = m1_df.iloc[-1]
        current_h1 = h1_df.iloc[-1]
        
        # Tendance macro
        macro_trend = "HAUSSIERE" if current_h1['EMA_50'] > current_h1['EMA_200'] else "BAISSIERE"
        
        # Formattage des 10 dernieres bougies M1 pour observer le Price Action recemment
        recent_bars = m1_df.tail(10).copy()
        recent_bars['time_str'] = pd.to_datetime(recent_bars['time'], unit='s').dt.strftime('%H:%M')
        data_to_send = recent_bars[['time_str', 'open', 'high', 'low', 'close']].to_dict(orient='records')
        data_str = json.dumps(data_to_send, indent=2)

        rsi = round(current_m1['RSI_14'], 2) if pd.notna(current_m1['RSI_14']) else 'N/A'
        atr = round(current_m1['ATR_14'], 2) if pd.notna(current_m1['ATR_14']) else 'N/A'
        
        prompt = f"""Tu es un algorithme de trading Quantitatif professionnel (Hedge Fund).
Symbole: {SYMBOL}.

**1. CONTEXTE MACRO (H1 - Graphique 1 Heure)**
- Tendance Primaire : {macro_trend} (Basee sur le croisement structurel EMA 50 / EMA 200)

**2. CONTEXTE MICRO (M1 - Execution)**
- RSI (14) : {rsi}
- Volatilite (ATR 14) : {atr} points
- Dernieres bougies M1 (Price Action) :
{data_str}

**Ton Role :**
1. Aligne tes trades avec la Tendance Primaire H1. Ne trade JAMAIS contre la tendance.
2. Utilise la valeur exacte du RSI calculée ci-dessus pour savoir si c'est le moment d'entrer.
3. Fixe le SL (Stop Loss) a environ 1.5x l'ATR depuis le prix courant, et le TP a 3x l'ATR minimum, selon le price action pour avoir un Risk:Reward > 1:2.
4. Si le marché est rangé ou incertain, la decision est WAIT.

Reponds STRICTEMENT par un objet JSON valide avec ce format exact :
{{
    "decision": "BUY" | "SELL" | "WAIT",
    "stop_loss_price": 1.0500,
    "take_profit_price": 1.0550,
    "reasoning": "Brief technical logic explanation"
}}
Si "WAIT", mets 0 pour le SL et le TP. Les valeurs de SL et TP doivent etre les vrais PRIX de sortie, absolument PAS leur distance en points.
"""
        
        try:
            response = self.client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt
            )
            txt = response.text.replace("```json", "").replace("```", "").strip()
            return json.loads(txt)
        except Exception as e:
            log.error(f"Erreur d'analyse AI : {e}")
            return {"decision": "WAIT", "reasoning": "Error"}

def execute_trade(action: str, slippage: int = 10, sl_price: float = 0.0, tp_price: float = 0.0) -> bool:
    point = mt5.symbol_info(SYMBOL).point
    price = mt5.symbol_info_tick(SYMBOL).ask if action == "BUY" else mt5.symbol_info_tick(SYMBOL).bid
    order_type = mt5.ORDER_TYPE_BUY if action == "BUY" else mt5.ORDER_TYPE_SELL

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": SYMBOL,
        "volume": LOT_SIZE,
        "type": order_type,
        "price": price,
        "sl": sl_price,
        "tp": tp_price,
        "deviation": slippage,
        "magic": 1000,
        "comment": "Gemini Quant Bot",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC, # Peut dependre du broker. Modifiable en ORDER_FILLING_FOK
    }
    
    result = mt5.order_send(request)
    if result and result.retcode != mt5.TRADE_RETCODE_DONE:
        log.error(f"[ERREUR] Ordre echoue : code {result.retcode} - {result.comment}")
        return False
    elif result is None:
        log.error(f"[ERREUR] Echec communication MT5 : {mt5.last_error()}")
        return False
    else:
        log.info(f"[SUCCES] Ordre {action} EXECUTE au prix {price}! ID: {result.order}")
        return True

def main():
    log.info("Connexion a l'API Native de MetaTrader 5...")
    if not mt5.initialize():
        log.critical(f"[ECHEC] Echec initialisation MT5 : {mt5.last_error()}")
        mt5.shutdown()
        return

    if not mt5.symbol_select(SYMBOL, True):
        log.critical(f"[ERREUR] Le symbole {SYMBOL} est introuvable sur ce broker/compte actuel.")
        mt5.shutdown()
        return

    strategist = QuantStrategist()
    log.info(f"Demarrage du bot Quantitatif (Indicateurs Mathematiques + Gemini) sur {SYMBOL}")

    while True:
        try:
            log.info("Extraction multi-timeframe de donnees (M1 / H1)...")
            rates_m1 = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 0, 100)
            rates_h1 = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_H1, 0, 300)
            
            if rates_m1 is None or len(rates_m1) == 0 or rates_h1 is None or len(rates_h1) == 0:
                log.warning("Impossible de recuperer les flux de prix. Verifie la connexion broker.")
                time.sleep(30)
                continue
                
            m1_df = pd.DataFrame(rates_m1)
            h1_df = pd.DataFrame(rates_h1)
            
            # 3. Analyse Mathematique
            decision = strategist.analyze(m1_df, h1_df)
            action = decision.get("decision", "WAIT")
            reasoning = decision.get("reasoning", "Aucune justification")
            
            log.info(f"Decision IA : {action} | Logique : {reasoning}")
            
            if action in ["BUY", "SELL"]:
                sl_price = float(decision.get("stop_loss_price", 0.0))
                tp_price = float(decision.get("take_profit_price", 0.0))
                
                # Executer l'ordre
                success = execute_trade(action, sl_price=sl_price, tp_price=tp_price)
                if success:
                    log.info("Mise en veille de 5 minutes pour ne pas rouvrir trop de trades.")
                    time.sleep(300)
            
            time.sleep(60)

        except Exception as e:
            log.error(f"Erreur dans le coeur analytique: {e}")
            time.sleep(30)

if __name__ == "__main__":
    main()
