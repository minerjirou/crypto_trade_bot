from __future__ import annotations

import pandas as pd
import pytest

from strategies.london_breakout import Trade, compute_stats, london_breakout

PIP = 0.01
SPREAD = 1.0
SLIPPAGE = 0.5
COST = (SPREAD + SLIPPAGE) * PIP
SLIP = SLIPPAGE * PIP
BUFFER = 3.0
RR = 1.5

BASE_DATE = "2023-01-02"


def _make_bar(hour: int, o: float, h: float, l: float, c: float) -> dict:
    return {
        "time": f"{BASE_DATE} {hour:02d}:00:00",
        "open": o,
        "high": h,
        "low": l,
        "close": c,
    }


def _tokyo_bars() -> list[dict]:
    highs = [150.50, 150.80, 150.60, 150.70, 150.90, 150.55, 150.65]
    lows = [150.30, 150.40, 150.35, 150.45, 150.50, 150.25, 150.40]
    bars = []
    for i in range(7):
        o = (highs[i] + lows[i]) / 2
        bars.append(_make_bar(i, o, highs[i], lows[i], o))
    return bars


RANGE_HIGH = 150.90
RANGE_LOW = 150.25
BREAK_HIGH = RANGE_HIGH + BUFFER * PIP  # 150.93
BREAK_LOW = RANGE_LOW - BUFFER * PIP    # 150.22


def _build_df(london_bars: list[dict]) -> pd.DataFrame:
    rows = _tokyo_bars() + london_bars
    df = pd.DataFrame(rows)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    return df


@pytest.fixture
def long_entry_df():
    london = [
        _make_bar(7, 150.80, 150.80, 150.70, 150.75),
        _make_bar(8, 150.85, 151.00, 150.80, 150.95),
    ]
    for h in range(9, 16):
        london.append(_make_bar(h, 150.95, 150.98, 150.90, 150.95))
    return _build_df(london)


@pytest.fixture
def short_entry_df():
    london = [
        _make_bar(7, 150.40, 150.45, 150.35, 150.38),
        _make_bar(8, 150.30, 150.35, 150.10, 150.15),
    ]
    for h in range(9, 16):
        london.append(_make_bar(h, 150.15, 150.20, 150.10, 150.15))
    return _build_df(london)


def test_tokyo_range_calculation(long_entry_df):
    trades = london_breakout(long_entry_df, pip_size=PIP, buffer_pips=BUFFER,
                             spread_pips=SPREAD, slippage_pips=SLIPPAGE,
                             risk_reward=RR)
    assert len(trades) == 1
    t = trades[0]
    inferred_range_low = t.stop_loss + BUFFER * PIP
    assert inferred_range_low == pytest.approx(RANGE_LOW, abs=1e-6)
    inferred_range_high = (t.entry_price - COST) - BUFFER * PIP
    assert inferred_range_high == pytest.approx(RANGE_HIGH, abs=1e-6)


def test_breakline_with_buffer(long_entry_df):
    trades = london_breakout(long_entry_df, pip_size=PIP, buffer_pips=BUFFER,
                             spread_pips=SPREAD, slippage_pips=SLIPPAGE,
                             risk_reward=RR)
    assert len(trades) == 1
    expected_break_high = RANGE_HIGH + BUFFER * PIP
    assert trades[0].entry_price == pytest.approx(expected_break_high + COST, abs=1e-6)
    assert trades[0].stop_loss == pytest.approx(RANGE_LOW - BUFFER * PIP, abs=1e-6)


def test_long_entry_on_upward_break(long_entry_df):
    trades = london_breakout(long_entry_df, pip_size=PIP, buffer_pips=BUFFER,
                             spread_pips=SPREAD, slippage_pips=SLIPPAGE,
                             risk_reward=RR)
    assert len(trades) == 1
    t = trades[0]
    assert t.direction == 1
    expected_entry = BREAK_HIGH + COST
    assert t.entry_price == pytest.approx(expected_entry, abs=1e-6)


def test_short_entry_on_downward_break(short_entry_df):
    trades = london_breakout(short_entry_df, pip_size=PIP, buffer_pips=BUFFER,
                             spread_pips=SPREAD, slippage_pips=SLIPPAGE,
                             risk_reward=RR)
    assert len(trades) == 1
    t = trades[0]
    assert t.direction == -1
    expected_entry = BREAK_LOW - COST
    assert t.entry_price == pytest.approx(expected_entry, abs=1e-6)


def test_stop_loss_triggered():
    entry_price = BREAK_HIGH + COST
    sl = BREAK_LOW
    london = [
        _make_bar(7, 150.80, 150.80, 150.70, 150.75),
        _make_bar(8, 150.85, 151.00, 150.80, 150.95),
        _make_bar(9, 150.50, 150.50, 150.10, 150.15),
    ]
    df = _build_df(london)
    trades = london_breakout(df, pip_size=PIP, buffer_pips=BUFFER,
                             spread_pips=SPREAD, slippage_pips=SLIPPAGE,
                             risk_reward=RR)
    assert len(trades) == 1
    t = trades[0]
    assert t.exit_reason == "stop_loss"
    assert t.exit_price == pytest.approx(sl - SLIP, abs=1e-6)
    assert t.pnl_pips < 0


def test_take_profit_triggered():
    entry_price = BREAK_HIGH + COST
    sl = BREAK_LOW
    tp = entry_price + (entry_price - sl) * RR
    london = [
        _make_bar(7, 150.80, 150.80, 150.70, 150.75),
        _make_bar(8, 150.85, 151.00, 150.80, 150.95),
        _make_bar(9, 150.95, tp + 0.10, 150.90, tp),
    ]
    df = _build_df(london)
    trades = london_breakout(df, pip_size=PIP, buffer_pips=BUFFER,
                             spread_pips=SPREAD, slippage_pips=SLIPPAGE,
                             risk_reward=RR)
    assert len(trades) == 1
    t = trades[0]
    assert t.exit_reason == "take_profit"
    assert t.exit_price == pytest.approx(tp, abs=1e-6)
    assert t.pnl_pips > 0


def test_time_exit():
    close_at_15 = 150.98
    london = [
        _make_bar(7, 150.80, 150.80, 150.70, 150.75),
        _make_bar(8, 150.85, 151.00, 150.80, 150.95),
    ]
    for h in range(9, 16):
        london.append(_make_bar(h, 150.95, 150.98, 150.90,
                                close_at_15 if h == 15 else 150.95))
    df = _build_df(london)
    trades = london_breakout(df, pip_size=PIP, buffer_pips=BUFFER,
                             spread_pips=SPREAD, slippage_pips=SLIPPAGE,
                             risk_reward=RR)
    assert len(trades) == 1
    t = trades[0]
    assert t.exit_reason == "time_exit"
    assert t.exit_price == pytest.approx(close_at_15, abs=1e-6)


def test_range_filter_too_narrow():
    bars = []
    for i in range(7):
        bars.append(_make_bar(i, 150.48, 150.50, 150.45, 150.47))
    bars.append(_make_bar(8, 150.48, 151.00, 150.40, 150.90))
    df = pd.DataFrame(bars)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    trades = london_breakout(df, pip_size=PIP, buffer_pips=BUFFER,
                             min_range_pips=10.0,
                             spread_pips=SPREAD, slippage_pips=SLIPPAGE)
    assert trades == []


def test_range_filter_too_wide():
    bars = []
    for i in range(7):
        bars.append(_make_bar(i, 151.00, 152.00, 150.00, 151.00))
    bars.append(_make_bar(8, 153.00, 153.50, 149.00, 153.00))
    df = pd.DataFrame(bars)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    trades = london_breakout(df, pip_size=PIP, buffer_pips=BUFFER,
                             max_range_pips=100.0,
                             spread_pips=SPREAD, slippage_pips=SLIPPAGE)
    assert trades == []


def test_one_trade_per_day():
    entry_price = BREAK_HIGH + COST
    sl = BREAK_LOW
    tp = entry_price + (entry_price - sl) * RR
    london = [
        _make_bar(7, 150.80, 150.80, 150.70, 150.75),
        _make_bar(8, 150.85, 151.00, 150.80, 150.95),
        _make_bar(9, 150.95, tp + 0.10, 150.90, tp),
        _make_bar(10, 150.20, 150.25, 150.10, 150.15),
        _make_bar(11, 150.10, 150.15, 149.90, 149.95),
    ]
    df = _build_df(london)
    trades = london_breakout(df, pip_size=PIP, buffer_pips=BUFFER,
                             spread_pips=SPREAD, slippage_pips=SLIPPAGE,
                             risk_reward=RR)
    assert len(trades) == 1
    assert trades[0].exit_reason == "take_profit"


def test_no_lookahead():
    london_a = [_make_bar(7, 150.80, 150.80, 150.70, 150.75),
                _make_bar(8, 150.85, 151.00, 150.80, 150.95)]
    for h in range(9, 16):
        london_a.append(_make_bar(h, 150.95, 150.98, 150.90, 150.95))

    london_b = [_make_bar(7, 150.80, 150.80, 150.70, 150.75),
                _make_bar(8, 150.85, 152.00, 150.80, 151.50)]
    for h in range(9, 16):
        london_b.append(_make_bar(h, 151.50, 151.60, 151.40, 151.50))

    df_a = _build_df(london_a)
    df_b = _build_df(london_b)
    trades_a = london_breakout(df_a, pip_size=PIP, buffer_pips=BUFFER,
                               spread_pips=SPREAD, slippage_pips=SLIPPAGE,
                               risk_reward=RR)
    trades_b = london_breakout(df_b, pip_size=PIP, buffer_pips=BUFFER,
                               spread_pips=SPREAD, slippage_pips=SLIPPAGE,
                               risk_reward=RR)
    assert len(trades_a) >= 1
    assert len(trades_b) >= 1
    assert trades_a[0].stop_loss == pytest.approx(trades_b[0].stop_loss, abs=1e-6)
