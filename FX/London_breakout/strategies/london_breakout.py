from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class Trade:
    date: str
    direction: int
    entry_price: float
    exit_price: float
    stop_loss: float
    take_profit: float
    pnl_pips: float
    exit_reason: str


def _prepare_ohlc(df: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(df, pd.DataFrame):
        raise TypeError("df must be a pandas DataFrame")

    data = df.copy()
    if "time" in data.columns:
        data["time"] = pd.to_datetime(data["time"], utc=True)
        data = data.set_index("time")
    elif isinstance(data.index, pd.DatetimeIndex):
        if data.index.tz is None:
            data.index = data.index.tz_localize("UTC")
        else:
            data.index = data.index.tz_convert("UTC")
    else:
        raise ValueError("df must have a UTC DatetimeIndex or a time column")

    required = {"open", "high", "low", "close"}
    missing = required.difference(data.columns)
    if missing:
        raise ValueError(f"df is missing required OHLC columns: {sorted(missing)}")

    return data.sort_index()


def london_breakout(
    df,
    tokyo_start=0,
    tokyo_end=7,
    london_end=15,
    buffer_pips=3.0,
    risk_reward=1.5,
    min_range_pips=10.0,
    max_range_pips=100.0,
    pip_size=0.01,
    spread_pips=1.0,
    slippage_pips=0.5,
) -> list[Trade]:
    data = _prepare_ohlc(df)
    trades: list[Trade] = []

    cost = (spread_pips + slippage_pips) * pip_size
    slippage = slippage_pips * pip_size

    for day, day_bars in data.groupby(data.index.date, sort=True):
        if day.weekday() >= 5:
            continue

        tokyo_bars = day_bars[
            (day_bars.index.hour >= tokyo_start) & (day_bars.index.hour < tokyo_end)
        ]
        if tokyo_bars.empty:
            continue

        range_high = float(tokyo_bars["high"].max())
        range_low = float(tokyo_bars["low"].min())
        range_width_pips = (range_high - range_low) / pip_size
        if range_width_pips < min_range_pips or range_width_pips > max_range_pips:
            continue

        break_high = range_high + buffer_pips * pip_size
        break_low = range_low - buffer_pips * pip_size

        position = 0
        entry = sl = tp = 0.0
        entry_time = None
        exit_price = None
        exit_reason = None

        session_bars = day_bars[day_bars.index.hour >= tokyo_end]
        for timestamp, bar in session_bars.iterrows():
            hour = timestamp.hour

            if position == 0:
                if hour >= london_end:
                    break
                if float(bar["high"]) > break_high:
                    position = 1
                    entry = break_high + cost
                    sl = break_low
                    tp = entry + (entry - sl) * risk_reward
                    entry_time = timestamp
                    continue
                if float(bar["low"]) < break_low:
                    position = -1
                    entry = break_low - cost
                    sl = break_high
                    tp = entry - (sl - entry) * risk_reward
                    entry_time = timestamp
                    continue
                continue

            if timestamp == entry_time:
                continue

            high = float(bar["high"])
            low = float(bar["low"])
            close = float(bar["close"])

            if position == 1:
                if low <= sl:
                    exit_price = sl - slippage
                    exit_reason = "stop_loss"
                elif high >= tp:
                    exit_price = tp
                    exit_reason = "take_profit"
                elif hour >= london_end:
                    exit_price = close
                    exit_reason = "time_exit"
            else:
                if high >= sl:
                    exit_price = sl + slippage
                    exit_reason = "stop_loss"
                elif low <= tp:
                    exit_price = tp
                    exit_reason = "take_profit"
                elif hour >= london_end:
                    exit_price = close
                    exit_reason = "time_exit"

            if exit_reason is not None and exit_price is not None:
                if position == 1:
                    pnl_pips = (exit_price - entry) / pip_size
                else:
                    pnl_pips = (entry - exit_price) / pip_size
                trades.append(
                    Trade(
                        date=day.isoformat(),
                        direction=position,
                        entry_price=float(entry),
                        exit_price=float(exit_price),
                        stop_loss=float(sl),
                        take_profit=float(tp),
                        pnl_pips=float(pnl_pips),
                        exit_reason=exit_reason,
                    )
                )
                break

    return trades


def compute_stats(trades, label="") -> dict:
    if len(trades) == 0:
        return {"n_trades": 0, "label": label}

    pnls = [float(t.pnl_pips) for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    long_count = sum(1 for t in trades if t.direction == 1)
    short_count = sum(1 for t in trades if t.direction == -1)

    total_pips = sum(pnls)
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    if gross_loss == 0:
        profit_factor = float("inf") if gross_win > 0 else 0.0
    else:
        profit_factor = gross_win / gross_loss

    equity = []
    running = 0.0
    for pnl in pnls:
        running += pnl
        equity.append(running)

    peak = 0.0
    max_dd = 0.0
    for value in equity:
        peak = max(peak, value)
        max_dd = max(max_dd, peak - value)

    exit_reasons: dict[str, int] = {}
    for trade in trades:
        exit_reasons[trade.exit_reason] = exit_reasons.get(trade.exit_reason, 0) + 1

    return {
        "label": label,
        "n_trades": len(trades),
        "long/short": f"{long_count}L/{short_count}S",
        "total_pips": float(total_pips),
        "win_rate": len(wins) / len(trades),
        "avg_win": float(sum(wins) / len(wins)) if wins else 0.0,
        "avg_loss": float(sum(losses) / len(losses)) if losses else 0.0,
        "profit_factor": float(profit_factor),
        "max_dd_pips": float(max_dd),
        "exit_reasons": exit_reasons,
    }


def trades_to_dataframe(trades) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "date": t.date,
                "direction": t.direction,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "pnl_pips": t.pnl_pips,
                "exit_reason": t.exit_reason,
            }
            for t in trades
        ],
        columns=[
            "date",
            "direction",
            "entry_price",
            "exit_price",
            "pnl_pips",
            "exit_reason",
        ],
    )
