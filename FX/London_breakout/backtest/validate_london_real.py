"""
実データ検証: ロンドンブレイクアウト戦略

OANDA から取得した実データで以下を検証:
  1. 全期間バックテスト
  2. パラメータ頑健性
  3. ウォークフォワード分析
  4. 年次/月次パフォーマンス
  5. イグジット理由分析
  6. 曜日別パフォーマンス

使い方:
  # まずデータを取得
  python data/fetch_oanda.py --instrument USD_JPY --years 3

  # 検証を実行
  python backtest/validate_london_real.py
  python backtest/validate_london_real.py --file data/EUR_USD_H1.csv --pip-size 0.0001
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from strategies.london_breakout import (
    london_breakout, trades_to_dataframe, compute_stats, Trade
)


# ============================================================
# データ読み込み
# ============================================================

def load_oanda_csv(filepath: str) -> pd.DataFrame:
    """
    fetch_oanda.py で保存したCSVを読み込み。
    UTC DatetimeIndex に変換し、必要カラムのみ返す。
    """
    df = pd.read_csv(filepath, parse_dates=["time"], index_col="time")

    # タイムゾーンを確認・設定
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")

    # 必須カラム確認
    required = ["open", "high", "low", "close"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns: {missing}")

    # スプレッド情報があれば保持
    keep = required + [c for c in ["spread", "volume", "bid_close", "ask_close"] if c in df.columns]
    df = df[keep]

    # NaN / 異常値チェック
    n_nan = df[required].isna().sum().sum()
    if n_nan > 0:
        print(f"  Warning: {n_nan} NaN values found, dropping those rows")
        df = df.dropna(subset=required)

    # 価格が0以下のバーを除外
    df = df[(df["close"] > 0) & (df["open"] > 0)]

    return df


def load_histdata_csv(filepath: str) -> pd.DataFrame:
    """
    HistData.com の CSV 形式 (YYYY.MM.DD,HH:MM,Open,High,Low,Close,Volume) も読める。
    ファイルの先頭数行を見て自動判定。
    """
    # ヘッダー有無を自動判定
    with open(filepath, "r") as f:
        first_line = f.readline().strip()

    if "open" in first_line.lower() or "time" in first_line.lower():
        return load_oanda_csv(filepath)

    # HistData形式: ヘッダーなし、セミコロン区切りの場合もある
    for sep in [",", ";"]:
        try:
            df = pd.read_csv(filepath, sep=sep, header=None)
            if len(df.columns) >= 6:
                break
        except Exception:
            continue

    if len(df.columns) == 7:
        df.columns = ["date", "time_str", "open", "high", "low", "close", "volume"]
        df["datetime"] = pd.to_datetime(df["date"] + " " + df["time_str"])
    elif len(df.columns) == 6:
        df.columns = ["datetime", "open", "high", "low", "close", "volume"]
        df["datetime"] = pd.to_datetime(df["datetime"])
    else:
        raise ValueError(f"Unexpected CSV format with {len(df.columns)} columns")

    df = df.set_index("datetime")
    df.index = df.index.tz_localize("UTC")
    df = df[["open", "high", "low", "close"]]
    return df


# ============================================================
# 分析関数
# ============================================================

def analyze_by_period(trades: list[Trade]) -> pd.DataFrame:
    """月次パフォーマンスを集計"""
    if not trades:
        return pd.DataFrame()
    df = trades_to_dataframe(trades)
    df["month"] = pd.to_datetime(df["date"]).dt.to_period("M")
    monthly = df.groupby("month").agg(
        n_trades=("pnl_pips", "count"),
        total_pips=("pnl_pips", "sum"),
        win_rate=("pnl_pips", lambda x: (x > 0).mean()),
        avg_pnl=("pnl_pips", "mean"),
    )
    return monthly


def analyze_by_weekday(trades: list[Trade]) -> pd.DataFrame:
    """曜日別パフォーマンス"""
    if not trades:
        return pd.DataFrame()
    df = trades_to_dataframe(trades)
    df["weekday"] = pd.to_datetime(df["date"]).dt.day_name()
    weekday_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    by_wd = df.groupby("weekday").agg(
        n_trades=("pnl_pips", "count"),
        total_pips=("pnl_pips", "sum"),
        avg_pips=("pnl_pips", "mean"),
        win_rate=("pnl_pips", lambda x: (x > 0).mean()),
    )
    by_wd = by_wd.reindex(weekday_order)
    return by_wd


def analyze_spread_impact(df_data: pd.DataFrame, trades: list[Trade]) -> dict:
    """実スプレッドの影響を分析"""
    if "spread" not in df_data.columns or not trades:
        return {"note": "spread data not available"}

    spread = df_data["spread"]
    return {
        "avg_spread": float(spread.mean()),
        "median_spread": float(spread.median()),
        "p95_spread": float(spread.quantile(0.95)),
        "max_spread": float(spread.max()),
        "london_open_avg": float(
            df_data[df_data.index.hour.isin([7, 8])]["spread"].mean()
        ),
    }


def walk_forward_real(
    df: pd.DataFrame,
    pip_size: float,
    train_days: int = 365,
    test_days: int = 90,
) -> list[dict]:
    """実データでのウォークフォワード分析"""
    buffers = [1.0, 3.0, 5.0, 8.0]
    rrs = [1.0, 1.5, 2.0, 2.5]

    total_days = (df.index[-1] - df.index[0]).days
    segments = []
    current = df.index[0]

    while True:
        train_end = current + pd.Timedelta(days=train_days)
        test_end = train_end + pd.Timedelta(days=test_days)
        if test_end > df.index[-1]:
            break

        df_tr = df[current:train_end]
        df_te = df[train_end:test_end]

        if len(df_tr) < 24 * 30 or len(df_te) < 24 * 7:
            current += pd.Timedelta(days=test_days)
            continue

        # 訓練期間で最良パラメータ
        best_pips = -np.inf
        best_params = (3.0, 1.5)
        for buf in buffers:
            for rr in rrs:
                tr = london_breakout(
                    df_tr, buffer_pips=buf, risk_reward=rr,
                    pip_size=pip_size, spread_pips=1.0, slippage_pips=0.5,
                )
                if len(tr) >= 5:
                    s = compute_stats(tr)
                    if s["total_pips"] > best_pips:
                        best_pips = s["total_pips"]
                        best_params = (buf, rr)

        # 検証期間
        test_trades = london_breakout(
            df_te, buffer_pips=best_params[0], risk_reward=best_params[1],
            pip_size=pip_size, spread_pips=1.0, slippage_pips=0.5,
        )
        test_stats = compute_stats(test_trades)

        segments.append({
            "train": f"{current.date()} ~ {train_end.date()}",
            "test": f"{train_end.date()} ~ {test_end.date()}",
            "params": best_params,
            "train_pips": best_pips,
            "test_pips": test_stats["total_pips"],
            "test_trades": test_stats["n_trades"],
            "test_wr": test_stats.get("win_rate", 0),
            "pnls": [t.pnl_pips for t in test_trades],
        })

        current += pd.Timedelta(days=test_days)

    return segments


# ============================================================
# メイン
# ============================================================

def print_stats(stats: dict, indent: int = 2):
    prefix = " " * indent
    if stats["n_trades"] == 0:
        print(f"{prefix}No trades")
        return
    print(f"{prefix}Trades     : {stats['n_trades']}  ({stats['long/short']})")
    print(f"{prefix}Total pips : {stats['total_pips']:+.1f}")
    print(f"{prefix}Win rate   : {stats['win_rate']*100:.1f}%")
    print(f"{prefix}Avg win    : {stats['avg_win']:.1f} pips")
    print(f"{prefix}Avg loss   : {stats['avg_loss']:.1f} pips")
    print(f"{prefix}PF         : {stats['profit_factor']:.2f}")
    print(f"{prefix}Max DD     : {stats['max_dd_pips']:.1f} pips")
    print(f"{prefix}Exits      : {stats['exit_reasons']}")


def main():
    parser = argparse.ArgumentParser(description="Validate London Breakout on real data")
    parser.add_argument("--file", default="data/USD_JPY_H1.csv",
                        help="CSVファイルパス")
    parser.add_argument("--pip-size", type=float, default=0.01,
                        help="pip size (JPY pairs=0.01, others=0.0001)")
    parser.add_argument("--output-dir", default="results",
                        help="結果出力ディレクトリ")
    args = parser.parse_args()

    # 出力ディレクトリ
    output_dir = Path(args.output_dir)
    output_dir.mkdir(exist_ok=True)

    # データ読み込み
    filepath = Path(args.file)
    if not filepath.exists():
        print(f"ERROR: {filepath} が見つかりません。")
        print(f"まずデータを取得してください:")
        print(f"  python data/fetch_oanda.py --instrument USD_JPY --years 3")
        return

    print("=" * 70)
    print(f"London Breakout - Real Data Validation")
    print("=" * 70)

    # 自動判定でロード
    try:
        df = load_oanda_csv(str(filepath))
    except Exception:
        df = load_histdata_csv(str(filepath))

    pip_size = args.pip_size
    instrument = filepath.stem.replace("_H1", "").replace("_M1", "")

    print(f"\n  Instrument : {instrument}")
    print(f"  Pip size   : {pip_size}")
    print(f"  Period     : {df.index[0].date()}  ->  {df.index[-1].date()}")
    print(f"  Total bars : {len(df):,}")

    # スプレッド分析
    spread_info = analyze_spread_impact(df, [])
    if "avg_spread" in spread_info:
        avg_pips = spread_info["avg_spread"] / pip_size
        lo_pips = spread_info["london_open_avg"] / pip_size
        p95_pips = spread_info["p95_spread"] / pip_size
        print(f"\n  --- Spread analysis ---")
        print(f"  Average    : {avg_pips:.2f} pips")
        print(f"  London open: {lo_pips:.2f} pips")
        print(f"  95th pctile: {p95_pips:.2f} pips")
        print(f"  Max        : {spread_info['max_spread']/pip_size:.2f} pips")
        # 実際のスプレッドが取得できれば、それをバックテストに使う
        actual_spread = max(avg_pips, 0.5)  # 最低0.5 pips
    else:
        actual_spread = 1.0  # デフォルト

    # ==============================================================
    # Test 1: 全期間バックテスト (デフォルトパラメータ)
    # ==============================================================
    print("\n" + "-" * 70)
    print("Test 1: Full period backtest (default params: buffer=3, RR=1.5)")
    print("-" * 70)

    trades = london_breakout(
        df, buffer_pips=3.0, risk_reward=1.5,
        pip_size=pip_size, spread_pips=actual_spread, slippage_pips=0.5,
    )
    stats = compute_stats(trades, "Default params")
    print_stats(stats)

    # ==============================================================
    # Test 2: パラメータ頑健性
    # ==============================================================
    print("\n" + "-" * 70)
    print("Test 2: Parameter robustness")
    print("-" * 70)
    print(f"  {'buffer':>8} {'RR':>6} {'trades':>8} {'pips':>10} {'win%':>8} {'PF':>8} {'maxDD':>8}")

    robustness_results = []
    for buffer in [1.0, 3.0, 5.0, 8.0]:
        for rr in [1.0, 1.5, 2.0, 2.5]:
            tr = london_breakout(
                df, buffer_pips=buffer, risk_reward=rr,
                pip_size=pip_size, spread_pips=actual_spread, slippage_pips=0.5,
            )
            if len(tr) >= 10:
                s = compute_stats(tr)
                robustness_results.append({
                    "buffer": buffer, "rr": rr, **s
                })
                print(f"  {buffer:>8.1f} {rr:>6.1f} {s['n_trades']:>8} "
                      f"{s['total_pips']:>+10.1f} {s['win_rate']*100:>7.1f}% "
                      f"{s['profit_factor']:>8.2f} {s['max_dd_pips']:>8.1f}")

    # 頑健性スコア
    n_positive = sum(1 for r in robustness_results if r["total_pips"] > 0)
    n_total = len(robustness_results)
    print(f"\n  Robustness: {n_positive}/{n_total} parameter combos are profitable")
    if n_positive == n_total:
        print("  -> EXCELLENT: All combos profitable")
    elif n_positive > n_total * 0.75:
        print("  -> GOOD: Most combos profitable")
    elif n_positive > n_total * 0.5:
        print("  -> MODERATE: Over half profitable, but sensitive to params")
    else:
        print("  -> WEAK: Strategy may not have real edge on this data")

    # ==============================================================
    # Test 3: ウォークフォワード
    # ==============================================================
    print("\n" + "-" * 70)
    print("Test 3: Walk-forward analysis (1yr train / 3mo test)")
    print("-" * 70)

    wf_segments = walk_forward_real(df, pip_size, train_days=365, test_days=90)

    if wf_segments:
        print(f"  {'Test period':<30} {'Params':<14} {'Train':>8} {'Test':>8} {'#':>5} {'WR':>6}")
        total_oos = 0
        total_trades = 0
        for seg in wf_segments:
            b, r = seg["params"]
            print(f"  {seg['test']:<30} buf={b}/rr={r:<6} "
                  f"{seg['train_pips']:>+8.1f} {seg['test_pips']:>+8.1f} "
                  f"{seg['test_trades']:>5} {seg['test_wr']*100:>5.1f}%")
            total_oos += seg["test_pips"]
            total_trades += seg["test_trades"]

        wins = sum(1 for s in wf_segments if s["test_pips"] > 0)
        print(f"\n  OOS total  : {total_oos:+.1f} pips / {total_trades} trades")
        print(f"  Win segments: {wins}/{len(wf_segments)}")

        # 訓練 vs テストの相関
        if len(wf_segments) >= 3:
            train_arr = [s["train_pips"] for s in wf_segments]
            test_arr = [s["test_pips"] for s in wf_segments]
            corr = np.corrcoef(train_arr, test_arr)[0, 1]
            print(f"  Train/Test correlation: {corr:+.3f}")
    else:
        print("  Not enough data for walk-forward analysis (need 1yr+3mo minimum)")

    # ==============================================================
    # Test 4: 月次・曜日別分析
    # ==============================================================
    print("\n" + "-" * 70)
    print("Test 4: Monthly & weekday breakdown")
    print("-" * 70)

    monthly = analyze_by_period(trades)
    if not monthly.empty:
        print("\n  Monthly performance:")
        print(f"  {'Month':<10} {'Trades':>7} {'Pips':>10} {'WR':>8} {'Avg':>8}")
        for period, row in monthly.iterrows():
            print(f"  {str(period):<10} {int(row['n_trades']):>7} "
                  f"{row['total_pips']:>+10.1f} {row['win_rate']*100:>7.1f}% "
                  f"{row['avg_pnl']:>+8.1f}")

        # 負け月の割合
        losing_months = (monthly["total_pips"] < 0).sum()
        print(f"\n  Losing months: {losing_months}/{len(monthly)}")

    weekday = analyze_by_weekday(trades)
    if not weekday.empty:
        print("\n  Weekday performance:")
        print(f"  {'Day':<12} {'Trades':>7} {'Pips':>10} {'Avg':>8} {'WR':>8}")
        for day, row in weekday.iterrows():
            print(f"  {day:<12} {int(row['n_trades']):>7} "
                  f"{row['total_pips']:>+10.1f} {row['avg_pips']:>+8.1f} "
                  f"{row['win_rate']*100:>7.1f}%")

    # ==============================================================
    # Charts
    # ==============================================================
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))

    # (0,0) Equity curve
    if trades:
        pnls = [t.pnl_pips for t in trades]
        cum = np.cumsum(pnls)
        dates = [pd.to_datetime(t.date) for t in trades]
        axes[0, 0].plot(dates, cum, color="#27ae60", lw=1.2)
        axes[0, 0].axhline(0, color="black", lw=0.5)
        axes[0, 0].set_title(f"Equity Curve - {instrument} (Real Data)")
        axes[0, 0].set_ylabel("Cumulative pips")
        axes[0, 0].grid(alpha=0.3)

    # (0,1) Walk-forward OOS equity
    if wf_segments:
        all_oos = []
        for seg in wf_segments:
            all_oos.extend(seg["pnls"])
        if all_oos:
            axes[0, 1].plot(np.cumsum(all_oos), color="#3498db", lw=1.2)
            axes[0, 1].axhline(0, color="black", lw=0.5)
        axes[0, 1].set_title("Walk-Forward (Out-of-Sample)")
        axes[0, 1].set_ylabel("Cumulative pips")
        axes[0, 1].grid(alpha=0.3)

    # (1,0) PnL distribution
    if trades:
        axes[1, 0].hist(pnls, bins=50, color="#95a5a6", edgecolor="white", alpha=0.8)
        axes[1, 0].axvline(0, color="red", lw=1)
        avg = np.mean(pnls)
        axes[1, 0].axvline(avg, color="#27ae60", lw=1.5, ls="--", label=f"Mean: {avg:.1f}")
        axes[1, 0].legend()
        axes[1, 0].set_title("PnL Distribution")
        axes[1, 0].set_xlabel("pips per trade")
        axes[1, 0].grid(alpha=0.3)

    # (1,1) Monthly PnL bar chart
    if not monthly.empty:
        months = [str(p) for p in monthly.index]
        pips = monthly["total_pips"].values
        colors = ["#27ae60" if p > 0 else "#e74c3c" for p in pips]
        axes[1, 1].bar(range(len(months)), pips, color=colors, alpha=0.8)
        axes[1, 1].set_title("Monthly PnL")
        axes[1, 1].set_ylabel("pips")
        # X軸ラベルを間引く
        step = max(1, len(months) // 12)
        axes[1, 1].set_xticks(range(0, len(months), step))
        axes[1, 1].set_xticklabels([months[i] for i in range(0, len(months), step)],
                                    rotation=45, ha="right")
        axes[1, 1].axhline(0, color="black", lw=0.5)
        axes[1, 1].grid(alpha=0.3)

    plt.suptitle(f"London Breakout - {instrument} Real Data Validation", fontsize=14)
    plt.tight_layout()

    chart_path = output_dir / f"london_breakout_{instrument}_validation.png"
    plt.savefig(str(chart_path), dpi=120, bbox_inches="tight")
    print(f"\nChart saved: {chart_path}")

    # ==============================================================
    # 最終判定
    # ==============================================================
    print("\n" + "=" * 70)
    print("VERDICT")
    print("=" * 70)

    checks = []

    # Check 1: 全期間損益
    if stats["n_trades"] > 0:
        checks.append(("Full-period profitable", stats["total_pips"] > 0))
        checks.append(("PF > 1.0", stats["profit_factor"] > 1.0))
        checks.append(("Win rate > 45%", stats["win_rate"] > 0.45))
        checks.append(("Enough trades (>100)", stats["n_trades"] > 100))

    # Check 2: 頑健性
    checks.append(("Robust params (>75% positive)", n_positive > n_total * 0.75))

    # Check 3: WF
    if wf_segments:
        checks.append(("WF positive total", total_oos > 0))
        checks.append(("WF >50% winning segments", wins > len(wf_segments) * 0.5))

    # Check 4: 月次
    if not monthly.empty:
        checks.append(("<50% losing months", losing_months < len(monthly) * 0.5))

    print()
    passed = 0
    for name, ok in checks:
        icon = "PASS" if ok else "FAIL"
        print(f"  [{icon}] {name}")
        if ok:
            passed += 1

    print(f"\n  Score: {passed}/{len(checks)} checks passed")
    if passed == len(checks):
        print("  -> ALL PASSED. Proceed to demo trading (Phase 5).")
    elif passed >= len(checks) * 0.7:
        print("  -> MOSTLY PASSED. Review failed checks, consider adjustments.")
    else:
        print("  -> MULTIPLE FAILURES. Strategy needs rework before live testing.")
    print("  -> Remember: Real trading will be WORSE than backtest. Always.")


if __name__ == "__main__":
    main()
