#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MEXC USDT-M 日計りボット（詳細な例外情報を表示）

• 00:00 JST  ─ 残高 50 % を「人気」上位 10 銘柄へ均等ロング
               ↳ 約定価格 × 1.8 の reduce-only TP 指値を即時セット
• 23:55 JST ─ すべてのロングを成行クローズし残注文をキャンセル
• 取引イベントは   ./trade_log.csv   と Discord Webhook へ通知
• タスク失敗時は **5 分後に 1 回だけ自動リトライ**
• 例外発生時にはスタックトレースを含めて詳しくログに出力

依存:
  pip install ccxt aiohttp schedule>=1.2 python-dotenv pytz
"""

import os
import asyncio
import csv
import aiohttp
import schedule
import traceback
from datetime import datetime
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from pytz import timezone
from dotenv import load_dotenv
import ccxt.async_support as ccxt

# ──────────── .env を読み込む ────────────
load_dotenv()
API_KEY         = os.getenv('MEXC_API_KEY')
SECRET          = os.getenv('MEXC_API_SECRET')
DISCORD_WEBHOOK = os.getenv('DISCORD_WEBHOOK')

if not API_KEY or not SECRET:
    raise RuntimeError("API キー/シークレットが設定されていません。.env を確認してください。")

# ─────────────── 定数設定 ────────────────
TOP_N           = 10          # 人気ランキング取得件数
TRADE_PCT       = 0.50        # 残高使用率
TP_FACTOR       = 1.8         # 利確倍率
LEVERAGE        = 1           # レバレッジ
LOG_PATH        = Path('./trade_log.csv')
JST             = timezone('Asia/Tokyo')
RETRY_DELAY_MIN = 5           # 失敗時のリトライ間隔（分）
# ───────────────────────────────────────────

# ──────────── ヘルパ関数 ────────────
def round_step(val, step, prec):
    """lot size に合わせて小数点以下を切り捨て"""
    return float(
        Decimal(val).quantize(
            Decimal(str(step)) if step else Decimal(f'1e-{prec}'),
            rounding=ROUND_DOWN
        )
    )

def jnow() -> str:
    """JST のタイムスタンプ文字列を返す"""
    return datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S')

async def discord_notify(msg: str):
    """Discord Webhook に通知を投げる"""
    if not DISCORD_WEBHOOK:
        return
    try:
        async with aiohttp.ClientSession() as sess:
            await sess.post(DISCORD_WEBHOOK, json={'content': msg}, timeout=10)
    except Exception as e:
        # Webhook 自体の送信エラーも詳細出力
        err = traceback.format_exc()
        print(f"[{jnow()}] Discord 通知失敗: {e}\n{err}")

async def get_top_symbols(ex):
    """MEXC の人気ランキング上位 TOP_N シンボルを取得"""
    mkts = await ex.load_markets()
    return [s for s in mkts if s.endswith('/USDT:USDT')][:TOP_N]

# ──────────── CSV ログ出力 ────────────
def _ensure_log():
    """ログファイルがなければヘッダーを書き込む"""
    if not LOG_PATH.exists():
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open('w', newline='') as f:
            csv.writer(f).writerow([
                "DateTime", "Action", "Symbol", "Quantity",
                "EntryPx", "ExitPx", "TPpx", "PnL_USDT"
            ])

def _log_csv(*row):
    """CSV ファイルに 1 行追加"""
    _ensure_log()
    with LOG_PATH.open('a', newline='') as f:
        csv.writer(f).writerow(row)

# ──────────── リトライ用スケジュール登録 ────────────
def _schedule_retry(tag: str, coro_fn):
    """
    同じ tag のリトライが既に登録されていなければ、
    RETRY_DELAY_MIN 分後に 1 回だけ実行するジョブを登録。
    成功したらジョブを解除する (schedule.clear(tag) をコルーチン側で呼ぶ)。
    """
    if any(tag in job.tags for job in schedule.jobs):
        return
    schedule.every(RETRY_DELAY_MIN).minutes.do(
        lambda: asyncio.create_task(coro_fn())
    ).tag(tag)
    print(f"[{jnow()}] {tag} を {RETRY_DELAY_MIN} 分後にリトライ予約")

# ──────────── 00:00 JST ── エントリー処理 ────────────
async def entry_long():
    tag = 'retry_entry'
    ex = None
    try:
        ex = ccxt.mexc({
            'apiKey': API_KEY,
            'secret': SECRET,
            'enableRateLimit': True,
            'options': {'defaultType': 'swap'}
        })

        syms      = await get_top_symbols(ex)
        balance   = await ex.fetch_balance({'type': 'swap'})
        usdt_free = balance['USDT']['free']
        budget    = usdt_free * TRADE_PCT
        each_usd  = budget / len(syms)

        await discord_notify(f":rocket: **ENTRY** 予算 {budget:.2f} USDT")

        for sym in syms:
            mkt  = ex.markets[sym]
            last = (await ex.fetch_ticker(sym))['last']
            qty  = round_step(each_usd / last,
                              mkt['limits']['amount']['min'],
                              mkt['precision']['amount'])
            if qty <= 0:
                print(f"[{jnow()}] ENTRY {sym}: ロット数 {qty} が最小値以下のためスキップ")
                continue

            try:
                await ex.set_leverage(LEVERAGE, sym)
            except Exception:
                print(f"[{jnow()}] レバレッジ設定失敗 {sym} (続行します)")

            order     = await ex.create_market_buy_order(
                            sym, qty, {'positionSide': 'long'})
            entry_px  = float(order.get('average') or order.get('price') or last)
            tp_px     = round_step(entry_px * TP_FACTOR,
                                   mkt['limits']['price']['min'],
                                   mkt['precision']['price'])
            await ex.create_limit_sell_order(
                sym, qty, tp_px, {'reduceOnly': True, 'positionSide': 'long'}
            )

            # CSV & Discord 通知
            _log_csv(jnow(), "entry", sym, qty,
                     f"{entry_px:.6f}", "", f"{tp_px:.6f}", "")
            await discord_notify(
                f"• **{sym.replace('/USDT:USDT','')}** qty `{qty}` entry `{entry_px:.4f}` TP `{tp_px:.4f}`"
            )
            print(f"[{jnow()}] ENTRY {sym:<15} qty={qty} entry={entry_px:.4f} TP={tp_px:.4f}")

        # 成功したのでリトライジョブを解除
        schedule.clear(tag)

    except Exception as e:
        err = traceback.format_exc()
        msg = f"[{jnow()}] ENTRY 失敗: {e}\n{err}"
        print(msg)
        await discord_notify(f":warning: {msg}")
        _schedule_retry(tag, entry_long)

    finally:
        if ex:
            try:
                await ex.close()
            except Exception:
                pass

# ──────────── 23:55 JST ── クローズ処理 ────────────
async def exit_all():
    tag = 'retry_exit'
    ex = None
    try:
        ex = ccxt.mexc({
            'apiKey': API_KEY,
            'secret': SECRET,
            'enableRateLimit': True,
            'options': {'defaultType': 'swap'}
        })

        await discord_notify(":stop_sign: **EXIT** 処理開始")

        syms = await get_top_symbols(ex)
        for sym in syms:
            try:
                pos = (await ex.fetch_positions([sym]))[0]
                qty = float(pos['contracts']) if pos['side'] == 'long' else 0
                if qty <= 0:
                    await ex.cancel_all_orders(sym)
                    continue

                entry_px = float(pos['entryPrice'])
                sell     = await ex.create_market_sell_order(
                               sym, qty,
                               {'reduceOnly': True, 'positionSide': 'long'}
                           )
                exit_px  = float(sell.get('average') or sell.get('price'))
                pnl      = (exit_px - entry_px) * qty

                await ex.cancel_all_orders(sym)

                # CSV & Discord 通知
                _log_csv(jnow(), "exit", sym, qty,
                         f"{entry_px:.6f}", f"{exit_px:.6f}", "", f"{pnl:.6f}")
                await discord_notify(
                    f"• **{sym.replace('/USDT:USDT','')}** qty `{qty}` exit `{exit_px:.4f}` PnL `{pnl:.2f}` USDT"
                )
                print(f"[{jnow()}] EXIT  {sym:<15} qty={qty} exit={exit_px:.4f} PnL={pnl:.2f}")

            except Exception as e_sym:
                err_sym = traceback.format_exc()
                warn = f"[{jnow()}] {sym} 決済失敗: {e_sym}\n{err_sym}"
                print(warn)
                await discord_notify(f":warning: {warn}")

        await discord_notify(":white_check_mark: EXIT 完了")
        schedule.clear(tag)

    except Exception as e:
        err = traceback.format_exc()
        msg = f"[{jnow()}] EXIT 全体失敗: {e}\n{err}"
        print(msg)
        await discord_notify(f":warning: {msg}")
        _schedule_retry(tag, exit_all)

    finally:
        if ex:
            try:
                await ex.close()
            except Exception:
                pass

# ──────────── スケジューラ登録 ────────────
def schedule_daily_jobs():
    schedule.every().day.at("00:00", JST).do(
        lambda: asyncio.create_task(entry_long())
    )
    schedule.every().day.at("23:55", JST).do(
        lambda: asyncio.create_task(exit_all())
    )

async def main():
    schedule_daily_jobs()
    while True:
        schedule.run_pending()
        await asyncio.sleep(1)

if __name__ == "__main__":
    asyncio.run(main())
