from __future__ import annotations
import asyncio, os, logging, math, time, statistics, csv
from decimal import Decimal, ROUND_DOWN
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import pybotters
from dotenv import load_dotenv

# ───────────── 設定 ─────────────
PAIR = "xrp_jpy"
ORDER_PCT = Decimal("0.05")            # 残高に対する1注文の割合（複利化）
MAX_POSITION_RATIO = Decimal("0.3")    # 最大ポジション額（残高の30%）
ENTRY_OFFSET = Decimal("0.001")        # ±0.1%
TP_OFFSET = Decimal("0.0015")          # ±0.15%
STOP_OFFSET = Decimal("0.02")          # ±2%
VOL_WINDOW = 20
VOL_THRESHOLD = Decimal("0.01")
PRICE_DECIMALS = 3
SIZE_DECIMALS = 4
STALE_SEC = 180
UPDATE_LIMIT = 6
update_timestamps = deque(maxlen=UPDATE_LIMIT)

LOG_FILE = Path("logs/trades.csv")
LOG_FILE.parent.mkdir(exist_ok=True)

load_dotenv()
API_KEY = os.getenv("BITBANK_API_KEY")
API_SECRET = os.getenv("BITBANK_API_SECRET")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

# ───────────── ロガー ─────────────
def log_trade(event: str, side: str, price: Decimal, amount: Decimal):
    now = datetime.utcnow().isoformat()
    is_new = not LOG_FILE.exists()
    with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(["timestamp", "event", "side", "price", "amount"])
        writer.writerow([now, event, side, str(price), str(amount)])

# ───────────── ユーティリティ ─────────────
def _q(val: Decimal, digits: int) -> Decimal:
    step = Decimal(10) ** -digits
    return val.quantize(step, rounding=ROUND_DOWN)

def _now() -> float:
    return time.time()

def _rate_limited():
    while len(update_timestamps) == UPDATE_LIMIT and _now() - update_timestamps[0] < 1:
        time.sleep(0.02)

async def _post(session, method, url, **kwargs):
    _rate_limited()
    r = await session.request(method, url, **kwargs)
    update_timestamps.append(_now())
    data = await r.json()
    if data.get("success") != 1:
        logging.warning(f"API error: {data}")
    return data

# ───────────── Bot本体 ─────────────
class MakerBot:
    def __init__(self, client):
        self.client = client
        self.mid: Decimal | None = None
        self.jpy_balance: Decimal = Decimal("0")
        self.open_orders = {}
        self.price_window = deque(maxlen=VOL_WINDOW)
        self.positions = {"buy": Decimal("0"), "sell": Decimal("0")}

    async def update_balance(self):
        r = await _post(self.client, "GET", "https://api.bitbank.cc/v1/user/assets", auth=True)
        if r and r.get("success") == 1:
            for a in r["data"]:
                if a["asset"] == "jpy":
                    self.jpy_balance = Decimal(a["free_amount"])
                    logging.info(f"Balance: {self.jpy_balance} JPY")

    async def handle_orderbook(self, msg, _ws):
        bids = msg["data"]["bids"]
        asks = msg["data"]["asks"]
        if not bids or not asks:
            return
        bid = Decimal(bids[0][0])
        ask = Decimal(asks[0][0])
        self.mid = (bid + ask) / 2
        self.price_window.append(self.mid)
        await self.reconcile()

    async def handle_execution(self, msg, _ws):
        for ex in msg["data"]:
            side = "sell" if ex["side"] == "buy" else "buy"
            price = Decimal(ex["price"])
            amount = Decimal(ex["size"])
            self.positions[ex["side"]] += price * amount
            log_trade("EXECUTION", ex["side"], price, amount)
            tp_px = _q(price * (1 + TP_OFFSET) if side == "sell" else price * (1 - TP_OFFSET), PRICE_DECIMALS)
            if not any(
                o for o in self.open_orders.values()
                if o["side"] == side and Decimal(o["price"]) == tp_px
            ):
                await self.send_order(side, amount, tp_px)

    def is_volatile(self):
        if len(self.price_window) < VOL_WINDOW:
            return False
        stdev = statistics.pstdev([float(p) for p in self.price_window])
        mean = float(statistics.mean(self.price_window))
        return (Decimal(stdev) / Decimal(mean)) > VOL_THRESHOLD

    async def reconcile(self):
        if self.mid is None:
            return
        await self.update_balance()
        if self.jpy_balance <= 0 or self.is_volatile():
            return
        await self.cancel_stale_orders()
        await self.ensure_grid()
        await self.check_stop_loss()

    async def cancel_stale_orders(self):
        now_ts = datetime.now(timezone.utc).timestamp()
        for oid, o in list(self.open_orders.items()):
            age = now_ts - o["timestamp"] / 1000
            px = Decimal(o["price"])
            want_buy = _q(self.mid * (1 - ENTRY_OFFSET), PRICE_DECIMALS)
            want_sell = _q(self.mid * (1 + ENTRY_OFFSET), PRICE_DECIMALS)
            if age > STALE_SEC or (o["side"] == "buy" and px != want_buy) or (o["side"] == "sell" and px != want_sell):
                await self.cancel_order(oid)

    async def ensure_grid(self):
        jpy_leg = self.jpy_balance * ORDER_PCT
        max_pos = self.jpy_balance * MAX_POSITION_RATIO
        size = _q(jpy_leg / self.mid, SIZE_DECIMALS)
        want = {
            "buy": _q(self.mid * (1 - ENTRY_OFFSET), PRICE_DECIMALS),
            "sell": _q(self.mid * (1 + ENTRY_OFFSET), PRICE_DECIMALS),
        }
        for side, px in want.items():
            if self.positions[side] > max_pos:
                continue
            if not any(
                o for o in self.open_orders.values()
                if o["side"] == side and Decimal(o["price"]) == px
            ):
                await self.send_order(side, size, px)

    async def check_stop_loss(self):
        max_pos = self.jpy_balance * MAX_POSITION_RATIO
        for side in ["buy", "sell"]:
            opp = "sell" if side == "buy" else "buy"
            if self.positions[side] > max_pos:
                px = _q(self.mid * (1 - STOP_OFFSET) if side == "buy" else self.mid * (1 + STOP_OFFSET), PRICE_DECIMALS)
                size = _q(self.positions[side] / self.mid, SIZE_DECIMALS)
                await self.send_order(opp, size, px)
                log_trade("STOP", opp, px, size)
                self.positions[side] = Decimal("0")

    async def send_order(self, side: str, size: Decimal, px: Decimal):
        log_trade("ORDER", side, px, size)
        r = await _post(self.client, "POST", "https://api.bitbank.cc/v1/user/spot/order", json={
            "pair": PAIR,
            "side": side,
            "type": "limit",
            "price": str(px),
            "size": str(size),
            "post_only": True,
        }, auth=True)
        if r.get("success") == 1:
            oid = r["data"]["order_id"]
            self.open_orders[oid] = {
                "side": side,
                "price": str(px),
                "timestamp": r["data"]["timestamp"],
            }

    async def cancel_order(self, oid: str):
        await _post(self.client, "POST", "https://api.bitbank.cc/v1/user/spot/cancel_order",
                    json={"pair": PAIR, "order_id": oid}, auth=True)
        self.open_orders.pop(oid, None)

# ───────────── メイン関数 ─────────────
async def main():
    async with pybotters.Client(
        apis={"bitbank": {"key": API_KEY, "secret": API_SECRET}}
    ) as client:
        bot = MakerBot(client)
        store = pybotters.BitbankDataStore()

        await bot.update_balance()

        await client.ws_connect(
            "wss://stream.bitbank.cc/socket.io/?EIO=3&transport=websocket",
            send_json=[
                {"type": "subscribe", "channel": f"depth_{PAIR}"},
                {"type": "subscribe", "channel": f"user_executions_{PAIR}"},
            ],
            hdlr_json=store.onmessage,
        )
        store.depth[PAIR].subscribe(bot.handle_orderbook)
        store.user_executions[PAIR].subscribe(bot.handle_execution)

        r = await client.get("https://api.bitbank.cc/v1/user/spot/open_orders",
                             params={"pair": PAIR}, auth=True)
        if r.status == 200:
            d = await r.json()
            for o in d["data"]["orders"]:
                bot.open_orders[o["order_id"]] = o

        while True:
            await asyncio.sleep(60)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
