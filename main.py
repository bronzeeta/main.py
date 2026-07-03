import asyncio
import sqlite3
import json
from datetime import datetime, timezone
import httpx
import pandas as pd
import numpy as np
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

# ====== التوكن حق بوت تيليجرام (إذا جاهز) ======
TELEGRAM_TOKEN = "8558238325:AAE5UKVgLtNFF9Yw3G4_j8JuTu-Ov5YVY1M"   # ← غيّره لبعدين
TELEGRAM_CHAT_ID = "989656943"         # ← غيّره لبعدين
ASSETS = ["BTCUSDT", "ETHUSDT", "EURUSDT", "XAUUSDT", "GBPUSDT", "XRPUSDT", "ADAUSDT"]
INTERVAL = "5m"

app = FastAPI(title="GHADEER AI HEDGE FUND ELITE")
app.add_middleware(CORSMiddleware, allow_origins=["*"])
ws_clients = set()

# ====== قاعدة البيانات ======
def init_db():
    conn = sqlite3.connect("ghadeer_elite.db")
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS trades 
                 (id INTEGER PRIMARY KEY, asset TEXT, action TEXT, price REAL,
                  confidence INT, evidence TEXT, time TEXT, result TEXT DEFAULT 'PENDING',
                  pnl REAL DEFAULT 0, closed_at TEXT)''')
    conn.commit()
    conn.close()

def save_trade(asset, action, price, confidence, evidence):
    conn = sqlite3.connect("ghadeer_elite.db")
    conn.execute("INSERT INTO trades (asset,action,price,confidence,evidence,time,result) VALUES (?,?,?,?,?,?,'PENDING')",
                 (asset, action, price, confidence, json.dumps(evidence), datetime.now(timezone.utc).isoformat()))
    conn.commit()
    conn.close()

def get_stats():
    conn = sqlite3.connect("ghadeer_elite.db")
    df = pd.read_sql("SELECT * FROM trades", conn)
    conn.close()
    if df.empty:
        return {"total": 0, "wins": 0, "losses": 0, "pending": 0, "win_rate": 0,
                "best_asset": "---", "worst_asset": "---", "avg_confidence": 0}
    total = len(df); wins = len(df[df['result']=='WIN']); losses = len(df[df['result']=='LOSS'])
    pending = len(df[df['result']=='PENDING'])
    wr = round(wins/(wins+losses)*100,1) if (wins+losses)>0 else 0
    closed = df[df['result']!='PENDING']
    avg_c = round(closed['confidence'].mean(),1) if not closed.empty else 0
    best, worst = "---", "---"
    if wins+losses > 5:
        g = df[df['result'].isin(['WIN','LOSS'])].groupby('asset')['result'].apply(lambda x: (x=='WIN').sum()/len(x)*100)
        best = g.idxmax().replace("USDT","/USD") if not g.empty else "---"
        worst = g.idxmin().replace("USDT","/USD") if not g.empty else "---"
    return {"total": total, "wins": wins, "losses": losses, "pending": pending,
            "win_rate": wr, "best_asset": best, "worst_asset": worst, "avg_confidence": avg_c}

# ====== تيليجرام ======
async def send_telegram(msg):
    if TELEGRAM_TOKEN == "YOUR_TELEGRAM_TOKEN": return
    await httpx.AsyncClient().post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                                   json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"})

# ====== جلب البيانات ======
async def fetch_ohlcv(symbol, limit=100):
    r = await httpx.AsyncClient().get(f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={INTERVAL}&limit={limit}")
    df = pd.DataFrame(r.json(), columns=['t','o','h','l','c','v','ct','qa','n','tb','tq','ig'])
    for col in ['o','h','l','c','v']: df[col] = df[col].astype(float)
    return df

# ====== الرياضيات ======
class MathEngine:
    @staticmethod
    def analyze(df):
        c = df['c']; price = c.iloc[-1]
        mean = c.rolling(20).mean().iloc[-1]; std = c.rolling(20).std().iloc[-1]
        z = (price - mean) / std if std != 0 else 0
        score, ev = 50, []
        if z < -2: score = 90; ev.append(f"Z-Score ({z:.2f}) تشبع بيعي إحصائي")
        elif z > 2: score = 10; ev.append(f"Z-Score ({z:.2f}) تشبع شرائي إحصائي")
        return {"score": max(0, min(100, score)), "evidence": ev}

# ====== التحليل الفني ======
class TechEngine:
    @staticmethod
    def analyze(df):
        c, h, l = df['c'], df['h'], df['l']
        score, ev = 50, []
        sma10, sma20, sma50 = c.rolling(10).mean().iloc[-1], c.rolling(20).mean().iloc[-1], c.rolling(50).mean().iloc[-1]
        if sma10 > sma20 > sma50: score += 15; ev.append("ترتيب المتوسطات صاعد")
        elif sma10 < sma20 < sma50: score -= 15; ev.append("ترتيب المتوسطات هابط")
        delta = c.diff()
        gain = delta.where(delta>0,0).rolling(14).mean().iloc[-1]; loss = (-delta.where(delta<0,0)).rolling(14).mean().iloc[-1]
        rsi = 50 if loss==0 else 100-(100/(1+gain/loss))
        if rsi < 30: score += 15; ev.append("RSI تشبع بيعي")
        elif rsi > 70: score -= 15; ev.append("RSI تشبع شرائي")
        ema12, ema26 = c.ewm(span=12).mean().iloc[-1], c.ewm(span=26).mean().iloc[-1]
        if ema12 > ema26: score += 10; ev.append("MACD إيجابي")
        else: score -= 10; ev.append("MACD سلبي")
        tr = np.maximum(h-l, np.maximum(abs(h-c.shift(1)), abs(l-c.shift(1))))
        atr = tr.rolling(14).mean().iloc[-1]
        return {"score": max(0, min(100, score)), "evidence": ev, "atr": atr}

# ====== Price Action (15 نموذج) ======
class PriceActionEngine:
    @staticmethod
    def analyze(df):
        score, ev = 50, []
        O,H,L,C = df['o'].iloc[-1], df['h'].iloc[-1], df['l'].iloc[-1], df['c'].iloc[-1]
        O1,C1,H1,L1 = df['o'].iloc[-2], df['c'].iloc[-2], df['h'].iloc[-2], df['l'].iloc[-2]
        O2,C2 = df['o'].iloc[-3], df['c'].iloc[-3]
        body = abs(C-O); uw = H-max(O,C); lw = min(O,C)-L
        if lw > body*2 and uw < body*0.5: score += 20; ev.append("شمعة مطرقة (Hammer) شراء")
        elif uw > body*2 and lw < body*0.5: score -= 20; ev.append("شمعة شهاب (Shooting Star) بيع")
        if C>O and C1<O1 and C>O1 and O<C1: score += 25; ev.append("ابتلاع شرائي Bullish Engulfing")
        elif C<O and C1>O1 and C<O1 and O>C1: score -= 25; ev.append("ابتلاع بيعي Bearish Engulfing")
        if body <= (H-L)*0.1: ev.append("دوجي Doji - ترقب")
        if C>O and abs(C1-O1)<(H1-L1)*0.2 and C2<O2 and C>(O2+C2)/2: score += 30; ev.append("نجمة الصباح Morning Star")
        elif C<O and abs(C1-O1)<(H1-L1)*0.2 and C2>O2 and C<(O2+C2)/2: score -= 30; ev.append("نجمة المساء Evening Star")
        if C>O and C1<O1 and O>C1 and C<O1: score += 15; ev.append("Harami صاعد")
        elif C<O and C1>O1 and O<C1 and C>O1: score -= 15; ev.append("Harami هابط")
        if C>O and C1<O1 and O<L1 and C>(O1+C1)/2: score += 20; ev.append("Piercing Line صاعد")
        elif C<O and C1>O1 and O>H1 and C<(O1+C1)/2: score -= 20; ev.append("Dark Cloud هابط")
        if C>O and uw<body*0.05 and lw<body*0.05: score += 15; ev.append("Marubozu صاعد - سيطرة مشترين")
        elif C<O and uw<body*0.05 and lw<body*0.05: score -= 15; ev.append("Marubozu هابط - سيطرة بائعين")
        return {"score": max(0, min(100, score)), "evidence": ev}

# ====== Smart Money (ICT) ======
class SmartMoneyEngine:
    @staticmethod
    def analyze(df):
        price = df['c'].iloc[-1]; score, ev = 50, []
        df['sh'] = df['h'][df['h']==df['h'].rolling(5,center=True).max()]
        df['sl'] = df['l'][df['l']==df['l'].rolling(5,center=True).min()]
        sh = df['sh'].dropna().values; sl = df['sl'].dropna().values
        if len(sh)<2 or len(sl)<2: return {"score": 50, "evidence": []}
        bsl = [h for h in sh if h>price][-2:]; ssl = [l for l in sl if l<price][-2:]
        if bsl and abs(price-bsl[-1])/price<0.002: score -= 10; ev.append("BSL قريب - احتمال بيع")
        if ssl and abs(price-ssl[-1])/price<0.002: score += 10; ev.append("SSL قريب - احتمال شراء")
        hh, hl = sh[-1]>sh[-2], sl[-1]>sl[-2]; ll, lh = sl[-1]<sl[-2], sh[-1]<sh[-2]
        if hh and hl: trend = "Bullish"
        elif ll and lh: trend = "Bearish"
        else: trend = "Ranging"
        if trend=="Bullish" and price<sl[-1]: score -= 30; ev.append("CHOCH هابط - كسر هيكل")
        elif trend=="Bearish" and price>sh[-1]: score += 30; ev.append("CHOCH صاعد - كسر هيكل")
        high, low = sh[-1], sl[-1]; rng = high-low
        if rng > 0:
            fib50, fib618, fib705 = high-(rng*0.5), high-(rng*0.618), high-(rng*0.705)
            if price < fib50:
                if fib705 <= price <= fib618: score += 25; ev.append("🎯 OTE شرائي في منطقة Discount")
            else:
                s618, s705 = low+(rng*0.618), low+(rng*0.705)
                if s618 <= price <= s705: score -= 25; ev.append("🎯 OTE بيعي في منطقة Premium")
        fvg_bull = df['l'] > df['h'].shift(2); fvg_bear = df['h'] < df['l'].shift(2)
        if fvg_bull.iloc[-2]: score += 15; ev.append("FVG صاعد")
        if fvg_bear.iloc[-2]: score -= 15; ev.append("FVG هابط")
        return {"score": max(0, min(100, score)), "evidence": ev}

# ====== المخاطر ======
class RiskEngine:
    @staticmethod
    def analyze(atr, price):
        score, ev = 50, []
        hour = datetime.now(timezone.utc).hour
        if 8 <= hour < 16: ev.append("🕒 جلسة لندن")
        elif 13 <= hour < 21: ev.append("🕒 جلسة نيويورك")
        else: score -= 10; ev.append("🕒 جلسة آسيا")
        v = (atr/price)*100
        if v > 0.5: ev.append(f"⚠️ تذبذب عالي {v:.2f}%")
        else: ev.append("✅ تذبذب طبيعي")
        return {"score": score, "evidence": ev}

# ====== محرك القرار ======
async def analyze_market():
    signals = []
    for asset in ASSETS:
        df = await fetch_ohlcv(asset)
        math = MathEngine.analyze(df)
        tech = TechEngine.analyze(df)
        pa = PriceActionEngine.analyze(df)
        smc = SmartMoneyEngine.analyze(df)
        risk = RiskEngine.analyze(tech['atr'], df['c'].iloc[-1])
        consensus = int((smc['score']*0.35)+(pa['score']*0.25)+(tech['score']*0.20)+(math['score']*0.10)+(risk['score']*0.10))
        action = "NO_TRADE"
        if consensus >= 75: action = "CALL"
        elif consensus <= 25: action = "PUT"
        all_ev = smc['evidence']+pa['evidence']+tech['evidence']+math['evidence']+risk['evidence']
        signal = {"asset": asset.replace("USDT","/USD"), "price": round(df['c'].iloc[-1],2),
                  "action": action, "confidence": consensus if action=="CALL" else (100-consensus),
                  "evidence": all_ev}
        if action != "NO_TRADE":
            save_trade(asset, action, signal['price'], signal['confidence'], all_ev)
            msg = f"🏦 GHADEER ELITE | {signal['asset']}\n🔥 {action}\n💰 ${signal['price']}\n🎯 {signal['confidence']}%\n\n"
            msg += "\n".join([f"• {e}" for e in all_ev[:4]])
            stats = get_stats()
            if stats['total'] >= 5:
                msg += f"\n\n📊 إحصائيات: {stats['win_rate']}% فوز ({stats['wins']}/{stats['wins']+stats['losses']})"
            await send_telegram(msg)
        signals.append(signal)
    return signals

# ====== WebSocket ======
@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    ws_clients.add(websocket)
    try:
        while True: await websocket.receive_text()
    except: ws_clients.discard(websocket)

@app.get("/stats")
async def stats_api(): return get_stats()

async def market_loop():
    while True:
        try:
            signals = await analyze_market()
            for c in list(ws_clients):
                try: await c.send_json(signals)
                except: ws_clients.discard(c)
        except Exception as e: print(f"Error: {e}")
        await asyncio.sleep(45)

@app.on_event("startup")
async def startup():
    init_db()
    asyncio.create_task(market_loop())

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
