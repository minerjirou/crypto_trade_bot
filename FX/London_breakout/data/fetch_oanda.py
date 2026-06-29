"""
OANDA ヒストリカルデータ取得

OANDAのv20 APIから1時間足データをダウンロードし、CSVに保存する。
1回のリクエストで最大5000本取得可能。それ以上は日付で分割してループ。

使い方:
  python data/fetch_oanda.py                        # デフォルト: USD_JPY, 3年分
  python data/fetch_oanda.py --instrument EUR_USD --years 5
  python data/fetch_oanda.py --instrument GBP_JPY --start 2020-01-01 --end 2024-12-31
"""
from __future__ import annotations
import argparse
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

try:
    import oandapyV20
    from oandapyV20.endpoints import instruments
except ImportError:
    print("ERROR: oandapyV20 が未インストールです。")
    print("  pip install oandapyV20")
    raise SystemExit(1)


# ============================================================
# 設定
# ============================================================

DATA_DIR = Path(__file__).resolve().parent
MAX_CANDLES_PER_REQUEST = 5000
RATE_LIMIT_SLEEP = 0.5  # API レート制限対策 (秒)


def get_api_client() -> oandapyV20.API:
    env = os.environ.get("OANDA_ENV", "practice")
    token = os.environ.get("OANDA_TOKEN")
    if not token:
        raise RuntimeError(
            "OANDA_TOKEN が設定されていません。\n"
            ".env ファイルに OANDA_TOKEN=your_token を記載してください。"
        )
    return oandapyV20.API(access_token=token, environment=env)


def fetch_candles(
    client: oandapyV20.API,
    instrument: str,
    granularity: str,
    start: datetime,
    end: datetime,
) -> pd.DataFrame:
    """
    指定期間の全ローソク足を取得。5000本制限を自動分割で回避。
    """
    all_candles = []
    current_start = start

    print(f"Fetching {instrument} {granularity}")
    print(f"  Period: {start.date()} -> {end.date()}")

    request_count = 0
    while current_start < end:
        params = {
            "granularity": granularity,
            "from": current_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "to": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "price": "MBA",  # Mid, Bid, Ask 全部取得
            "count": MAX_CANDLES_PER_REQUEST,
        }

        r = instruments.InstrumentsCandles(instrument=instrument, params=params)

        try:
            client.request(r)
        except Exception as e:
            print(f"  API Error: {e}")
            print(f"  Retrying in 5 seconds...")
            time.sleep(5)
            continue

        candles = r.response.get("candles", [])
        if not candles:
            break

        all_candles.extend(candles)
        request_count += 1

        # 最後のキャンドルの時刻を次の開始点にする
        last_time = candles[-1]["time"]
        current_start = datetime.fromisoformat(last_time.replace("Z", "+00:00"))
        current_start += timedelta(seconds=1)  # 重複回避

        n_total = len(all_candles)
        print(f"  Request #{request_count}: got {len(candles)} candles "
              f"(total: {n_total}, up to {current_start.date()})")

        time.sleep(RATE_LIMIT_SLEEP)

    if not all_candles:
        print("  No data returned!")
        return pd.DataFrame()

    return _candles_to_dataframe(all_candles)


def _candles_to_dataframe(candles: list[dict]) -> pd.DataFrame:
    """OANDA APIレスポンスをDataFrameに変換"""
    rows = []
    for c in candles:
        if not c.get("complete", False):
            continue  # 未完成バーは除外

        mid = c["mid"]
        bid = c["bid"]
        ask = c["ask"]

        rows.append({
            "time": c["time"],
            "open": float(mid["o"]),
            "high": float(mid["h"]),
            "low": float(mid["l"]),
            "close": float(mid["c"]),
            "bid_close": float(bid["c"]),
            "ask_close": float(ask["c"]),
            "spread": float(ask["c"]) - float(bid["c"]),
            "volume": int(c.get("volume", 0)),
        })

    df = pd.DataFrame(rows)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.set_index("time")
    df = df.sort_index()

    # 重複除去
    df = df[~df.index.duplicated(keep="last")]

    return df


def save_data(df: pd.DataFrame, instrument: str, granularity: str):
    """CSV保存"""
    filename = f"{instrument}_{granularity}.csv"
    filepath = DATA_DIR / filename
    df.to_csv(filepath)
    print(f"\nSaved: {filepath}")
    print(f"  Rows   : {len(df):,}")
    print(f"  Period : {df.index[0]}  ->  {df.index[-1]}")
    print(f"  Columns: {list(df.columns)}")
    return filepath


# ============================================================
# メイン
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="Fetch OANDA historical data")
    parser.add_argument("--instrument", default="USD_JPY", help="通貨ペア (例: USD_JPY, EUR_USD)")
    parser.add_argument("--granularity", default="H1", help="時間軸 (M1, M5, M15, H1, H4, D)")
    parser.add_argument("--years", type=float, default=3, help="取得年数 (--start/--end 未指定時)")
    parser.add_argument("--start", default=None, help="開始日 (YYYY-MM-DD)")
    parser.add_argument("--end", default=None, help="終了日 (YYYY-MM-DD)")
    args = parser.parse_args()

    # 期間の決定
    if args.start and args.end:
        start = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end = datetime.strptime(args.end, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    else:
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=int(args.years * 365))

    client = get_api_client()

    # データ取得
    df = fetch_candles(client, args.instrument, args.granularity, start, end)
    if df.empty:
        print("No data fetched. Check your API token and instrument name.")
        return

    # 保存
    save_data(df, args.instrument, args.granularity)

    # 基本統計を表示
    print(f"\n--- Basic stats ---")
    print(f"  Mean close   : {df['close'].mean():.3f}")
    print(f"  Std close    : {df['close'].std():.3f}")
    print(f"  Min close    : {df['close'].min():.3f}")
    print(f"  Max close    : {df['close'].max():.3f}")
    print(f"  Avg spread   : {df['spread'].mean():.5f} "
          f"({df['spread'].mean() / 0.01:.2f} pips for JPY pairs)")
    print(f"  Max spread   : {df['spread'].max():.5f} "
          f"({df['spread'].max() / 0.01:.2f} pips)")


if __name__ == "__main__":
    main()
