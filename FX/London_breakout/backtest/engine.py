"""
ミニマルなバックテストエンジン

戦略関数が返すポジション系列を受け取り、取引コストを差し引いた損益を計算する。

設計方針:
- シグナルは t バーの終値で確定
- エントリー/イグジットは t+1 バーの始値で行う(ルックアヘッド防止)
- 1単位の通貨ペア取引を仮定(ロット管理は後のフェーズで)
"""
from __future__ import annotations
from dataclasses import dataclass
import pandas as pd
import numpy as np


@dataclass
class BacktestResult:
    equity_curve: pd.Series   # 累積損益(pips)
    trades: pd.DataFrame      # 取引ログ
    stats: dict               # 集計指標


def run_backtest(
    df: pd.DataFrame,
    position: pd.Series,
    spread_pips: float = 1.0,
    slippage_pips: float = 0.5,
    pip_size: float = 0.01,   # USD/JPY なら 0.01、EUR/USD なら 0.0001
) -> BacktestResult:
    """
    Parameters
    ----------
    df         : OHLC DataFrame
    position   : 各バーで取るべきポジション (1/-1/0)。run_backtest 内で t+1 始値発注に変換
    spread_pips: 往復スプレッド(pips)
    slippage_pips: 片道スリッページ(pips)
    pip_size   : 1 pip を価格単位に換算する係数
    """
    df = df.copy()
    df["position"] = position

    # シグナルが出た次のバーの始値で発注
    df["entry_price"] = df["open"].shift(-1)

    # ポジション変化を検出
    df["prev_position"] = df["position"].shift(1).fillna(0)
    df["position_change"] = df["position"] - df["prev_position"]

    # 取引コスト: ポジションが変わったバーで発生
    # 例: 0 -> 1 は片道, 1 -> -1 は往復+往復 (反対売買)
    cost_per_trade = (spread_pips + slippage_pips * 2) * pip_size
    df["trade_cost"] = df["position_change"].abs() * cost_per_trade / 2
    # ↑ position_change の絶対値は 1 or 2。1 単位の変化 = 片道コスト

    # 損益計算: 前のバーの終値から今のバーの終値までの値動きを、前のポジションで取る
    df["price_return"] = df["close"].diff()
    df["pnl"] = df["prev_position"] * df["price_return"] - df["trade_cost"]

    df = df.dropna(subset=["pnl"])

    # pips 換算したエクイティカーブ
    equity_pips = df["pnl"].cumsum() / pip_size

    # 取引ログ
    trade_bars = df[df["position_change"] != 0].copy()
    trades = pd.DataFrame({
        "time": trade_bars.index,
        "action": trade_bars["position_change"].apply(_describe_action),
        "price": trade_bars["open"].shift(-1) if False else trade_bars["close"],
    })

    # 集計
    stats = _compute_stats(df, equity_pips, pip_size)

    return BacktestResult(equity_curve=equity_pips, trades=trades, stats=stats)


def _describe_action(change: int) -> str:
    return {1: "buy", -1: "sell", 2: "buy(reverse)", -2: "sell(reverse)"}.get(change, "?")


def _compute_stats(df: pd.DataFrame, equity_pips: pd.Series, pip_size: float) -> dict:
    pnl = df["pnl"]

    # 取引単位での損益を計算(ポジションを持っていた区間ごと)
    position_runs = (df["position"] != df["prev_position"]).cumsum()
    trade_pnl = df.groupby(position_runs).apply(
        lambda g: g["pnl"].sum() if g["prev_position"].iloc[0] != 0 else 0
    )
    trade_pnl = trade_pnl[trade_pnl != 0]

    if len(trade_pnl) == 0:
        return {"n_trades": 0, "note": "取引が発生しませんでした"}

    wins = trade_pnl[trade_pnl > 0]
    losses = trade_pnl[trade_pnl < 0]

    # 最大ドローダウン(pips)
    running_max = equity_pips.cummax()
    drawdown = equity_pips - running_max
    max_dd_pips = drawdown.min()

    # シャープレシオ(年率、252日換算)
    daily_returns = pnl.resample("D").sum() if hasattr(pnl.index, "date") else pnl
    sharpe = (
        daily_returns.mean() / daily_returns.std() * np.sqrt(252)
        if daily_returns.std() > 0 else 0
    )

    return {
        "n_trades": int(len(trade_pnl)),
        "total_pips": float(equity_pips.iloc[-1]),
        "win_rate": float(len(wins) / len(trade_pnl)),
        "avg_win_pips": float(wins.mean() / pip_size) if len(wins) > 0 else 0,
        "avg_loss_pips": float(losses.mean() / pip_size) if len(losses) > 0 else 0,
        "profit_factor": float(wins.sum() / -losses.sum()) if len(losses) > 0 and losses.sum() != 0 else float("inf"),
        "max_drawdown_pips": float(max_dd_pips),
        "sharpe_ratio": float(sharpe),
    }
