#!/usr/bin/env python3
"""
Bitbank ATOM/JPY bot using pybotters + WebSocket ticker
+ 複利対応: JPY残高の一定比率で自動ロット計算
"""

import os, csv, asyncio
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pybotters
from dotenv import load_dotenv

# === CONFIG ===
SYMBOL = "ATOM/JPY"
TICKER_SYMBOL = "atom_jpy"
TRADE_RATIO = Decimal("0.5")       # JPY残高の50%を1回に使う
MIN_SIZE = Decimal("0.0001")
FAST_MA = 5
SLOW_MA = 20
SLEEP_SEC = 30
LOG_PATH = Path("log/trades.csv")

# === STATE ===
last_buy_price = None
in_position = False

load_dotenv()
client = pybotters.Client(
    apis={"bitbank": (os.getenv("BITBANK_API_KEY"), os.getenv("BITBANK_API_SECRET"))}
)

def init_log():
    LOG_PATH.parent.mkdir(exist_ok=True)
    if not LOG_PATH.exists():
        with open(LOG_PATH, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "timestamp", "side", "size", "price", "fee", "pnl",
                "order_id", "balance_jpy", "balance_atom"
            ])

async def log_trade(side, size, price, fee, order_id, pnl=None):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    jpy, atom = await get_balances()
    with open(LOG_PATH, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([ts, side, float(size), price, fee, pnl, order_id, jpy, atom])

async def get_balances():
    res = await client.get("https://api.bitbank.cc/v1/user/assets").send()
    data = await res.json()
    assets = {a["asset"]: Decimal(a["free_amount"]) for a in data["data"]}
    return float(assets.get("jpy", 0)), float(assets.get("atom", 0))

def calc_order_size(jpy_amount: Decimal, price: float) -> Decimal:
    qty = (jpy_amount / Decimal(str(price))).quantize(Decimal("0.000001"))
    return max(qty, MIN_SIZE)

async def place_order(side: str, price: float):
    global last_buy_price, in_position

    jpy_balance, atom_balance = await get_balances()
    jpy_to_use = Decimal(str(jpy_balance)) * TRADE_RATIO
    size = calc_order_size(jpy_to_use, price)

    body = {
        "pair": TICKER_SYMBOL,
        "amount": str(size),
        "side": side,
        "type": "market"
    }

    try:
        res = await client.post("https://api.bitbank.cc/v1/user/spot/order", data=body).send()
        result = await res.json()
        o = result["data"]
        avg_price = float(o.get("average_price", price))
        fee = float(o.get("executed_fee", 0))
        order_id = o.get("order_id", "N/A")

        pnl = None
        if side == "buy":
            last_buy_price = avg_price
            in_position = True
        elif side == "sell" and last_buy_price:
            pnl = round((avg_price - last_buy_price) * float(size), 6)
            last_buy_price = None
            in_position = False

        print(f"{side.upper()} {size} @ {avg_price} (fee={fee}) → PnL={pnl}")
        await log_trade(side, size, avg_price, fee, order_id, pnl)

    except Exception as e:
        print(f"[ERROR] order failed: {e}")

async def fetch_ohlcv():
    url = f"https://public.bitbank.cc/{TICKER_SYMBOL}/candlestick/1min/2024"
    res = await client.get(url).send()
    data = await res.json()
    candles = data["data"]["candlestick"][0]["ohlcv"]
    df = pd.DataFrame(candles, columns=["open", "high", "low", "close", "volume", "timestamp"])
    df["close"] = df["close"].astype(float)
    return df.tail(SLOW_MA + 1)

async def main():
    init_log()
    store = pybotters.bitbankDataStore()
    ws = await client.ws_connect("wss://stream.bitbank.cc/socket.io/?EIO=4&transport=websocket")
    await store.initialize(ws, [f"ticker_{TICKER_SYMBOL}"])

    while True:
        df = await fetch_ohlcv()
        fast = df["close"].rolling(FAST_MA).mean().iloc[-1]
        slow = df["close"].rolling(SLOW_MA).mean().iloc[-1]
        if pd.isna(fast) or pd.isna(slow):
            await asyncio.sleep(SLEEP_SEC)
            continue

        ticker_data = store.ticker.find({"pair": TICKER_SYMBOL})
        if not ticker_data:
            await asyncio.sleep(SLEEP_SEC)
            continue

        last_price = float(ticker_data[-1]["last"])

        if not in_position and fast > slow:
            await place_order("buy", last_price)
        elif in_position and fast < slow:
            await place_order("sell", last_price)

        await asyncio.sleep(SLEEP_SEC)

if __name__ == "__main__":
    asyncio.run(main())
