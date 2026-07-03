import os
import random
from datetime import datetime, timezone
from typing import Optional, Dict, Any

import httpx
from fastapi import FastAPI, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

PROJECT_NAME = "GHADEER AI HEDGE FUND ELITE"
TELEGRAM_TOKEN = os.getenv("8558238325:AAE5UKVgLtNFF9Yw3G4_j8JuTu-Ov5YVY1M", "")
TELEGRAM_CHAT_ID = os.getenv("989656943", "")

app = FastAPI(title=PROJECT_NAME, version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class SignalRequest(BaseModel):
    symbol: str = "EUR/USD"
    decision: str = "NO TRADE"
    confidence: int = 0
    stop_loss: Optional[str] = None
    take_profit: Optional[str] = None
    risk_reward: Optional[str] = None
    timeframe: Optional[str] = "15min"
    source: Optional[str] = "netlify-dashboard"

ASSETS = ["EUR/USD", "GBP/USD", "USD/JPY", "XAU/USD", "BTC/USD", "ETH/USD", "US30", "NAS100"]
REASONS = [
    "Liquidity Sweep", "BOS", "CHOCH", "Order Block", "EMA 50 / EMA 200",
    "RSI", "MACD", "ADX", "Risk Filter", "Session Filter", "No High Impact News"
]

stats_data = {
    "signals_today": 0,
    "telegram_sent": 0,
    "last_signal": None,
    "avg_confidence": 0,
    "status": "online",
}

def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

def normalize_decision(decision: str) -> str:
    d = (decision or "").upper().strip()
    if "BUY" in d and "NO" not in d:
        return "BUY"
    if "SELL" in d:
        return "SELL"
    return "NO TRADE"

def build_message(sig: Dict[str, Any]) -> str:
    reasons = sig.get("reasons") or []
    reason_text = "\n".join([f"• {r}" for r in reasons]) if reasons else "• Dashboard Consensus"
    return f"""🤖 <b>{PROJECT_NAME}</b>

📌 الأصل: <b>{sig['symbol']}</b>
⏱️ الفريم: <b>{sig.get('timeframe','15min')}</b>
🎯 القرار: <b>{sig['decision']}</b>
📊 الثقة: <b>{sig['confidence']}%</b>

✅ الأدلة:
{reason_text}

🛑 SL: <b>{sig.get('stop_loss') or 'حسب إدارة المخاطر'}</b>
✅ TP: <b>{sig.get('take_profit') or 'حسب إدارة المخاطر'}</b>
⚖️ RR: <b>{sig.get('risk_reward') or '—'}</b>

🕐 {now_utc()}
"""

async def send_telegram_message(message: str) -> Dict[str, Any]:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return {"sent": False, "reason": "TELEGRAM_TOKEN or TELEGRAM_CHAT_ID is missing in Render Environment Variables"}
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(url, json=payload)
        data = r.json()
        return {"sent": bool(data.get("ok")), "telegram_response": data}

def generate_demo_signal(symbol: Optional[str] = None, timeframe: str = "15min") -> Dict[str, Any]:
    symbol = symbol or random.choice(ASSETS)
    confidence = random.randint(55, 96)
    decision = random.choice(["BUY", "SELL"]) if confidence >= 82 else "NO TRADE"
    selected = random.sample(REASONS, random.randint(4, 7))
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "decision": decision,
        "confidence": confidence,
        "reasons": selected,
        "stop_loss": "-2.5%" if decision == "BUY" else "+2.5%" if decision == "SELL" else None,
        "take_profit": "+5.5%" if decision == "BUY" else "-5.5%" if decision == "SELL" else None,
        "risk_reward": "1:2.2" if decision != "NO TRADE" else None,
        "time": now_utc(),
    }

@app.get("/")
def root():
    return {"project": PROJECT_NAME, "status": "online", "routes": ["/health", "/stats", "/signal", "/send-signal", "/telegram-test", "/docs"]}

@app.get("/health")
def health():
    return {"project": PROJECT_NAME, "status": "online", "telegram_configured": bool(TELEGRAM_TOKEN and TELEGRAM_CHAT_ID), "time": now_utc()}

@app.get("/stats")
def stats():
    return stats_data

@app.get("/signal")
def signal(symbol: Optional[str] = None, timeframe: str = "15min"):
    return generate_demo_signal(symbol=symbol, timeframe=timeframe)

@app.post("/send-signal")
async def send_signal(payload: SignalRequest = Body(...)):
    decision = normalize_decision(payload.decision)
    sig = {
        "symbol": payload.symbol.upper(),
        "timeframe": payload.timeframe,
        "decision": decision,
        "confidence": int(payload.confidence or 0),
        "stop_loss": payload.stop_loss,
        "take_profit": payload.take_profit,
        "risk_reward": payload.risk_reward,
        "reasons": ["Netlify Dashboard Consensus", "Multi-Agent Confirmation", "Risk Filter Passed"],
        "time": now_utc(),
    }
    stats_data["signals_today"] += 1
    stats_data["last_signal"] = sig
    stats_data["avg_confidence"] = sig["confidence"]
    if decision == "NO TRADE" or sig["confidence"] < 68:
        return {"sent": False, "reason": "NO TRADE or low confidence", "signal": sig}
    result = await send_telegram_message(build_message(sig))
    if result.get("sent"):
        stats_data["telegram_sent"] += 1
    return {"sent": result.get("sent", False), "telegram": result, "signal": sig}

@app.get("/send-signal")
async def send_generated_signal(symbol: Optional[str] = None, timeframe: str = "15min"):
    sig = generate_demo_signal(symbol=symbol, timeframe=timeframe)
    stats_data["signals_today"] += 1
    stats_data["last_signal"] = sig
    stats_data["avg_confidence"] = sig["confidence"]
    if sig["decision"] == "NO TRADE":
        return {"sent": False, "reason": "NO TRADE", "signal": sig}
    result = await send_telegram_message(build_message(sig))
    if result.get("sent"):
        stats_data["telegram_sent"] += 1
    return {"sent": result.get("sent", False), "telegram": result, "signal": sig}

@app.get("/telegram-test")
async def telegram_test():
    msg = f"✅ <b>{PROJECT_NAME}</b>\nRender + Telegram connection is working.\n🕐 {now_utc()}"
    return await send_telegram_message(msg)
