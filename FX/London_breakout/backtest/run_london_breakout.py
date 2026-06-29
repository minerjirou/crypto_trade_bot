"""
ロンドンブレイクアウト戦略のバックテスト + ウォークフォワード検証

テスト対象:
  1. 通常バックテスト(全期間)
  2. ランダムウォークでのバックテスト(エッジ検証)
  3. ウォークフォワード分析
  4. パラメータ頑健性テスト
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strategies.london_breakout import (
    london_breakout, trades_to_dataframe, compute_stats
)


# ============================================================
# データ生成
# ============================================================

def generate_fx_h1(
    n_days: int = 365 * 3,
    start_price: float = 150.0,
    seed: int = 42,
    trend_strength: float = 0.00015,
    session_effect: bool = True,
) -> pd.DataFrame:
    """
    FXっぽい1時間足を生成。
    session_effect=True なら東京/ロンドン/NYのボラ差と
    ロンドンオープンのブレイク傾向を含む。
    """
    rng = np.random.default_rng(seed)
    n_bars = n_days * 24
    idx = pd.date_range("2021-01-01", periods=n_bars, freq="1h", tz="UTC")

    # 時間帯別ボラティリティ (UTC基準)
    hourly_vol = np.ones(24) * 0.0004
    if session_effect:
        # 東京 (00-07): 低ボラ
        hourly_vol[0:7] = 0.0003
        # ロンドン (07-15): 高ボラ、特にオープン直後
        hourly_vol[7:10] = 0.0007
        hourly_vol[10:15] = 0.0005
        # NY (13-21): 中ボラ
        hourly_vol[13:21] = 0.00045
        # 深夜 (21-24): 最低
        hourly_vol[21:24] = 0.00025

    vols = np.array([hourly_vol[h] for h in idx.hour])
    returns = rng.normal(0, vols)

    # トレンド成分
    if trend_strength > 0:
        trend = np.zeros(n_bars)
        for _ in range(40):
            start = rng.integers(0, n_bars - 500)
            length = rng.integers(100, 500)
            direction = rng.choice([-1, 1])
            trend[start:start + length] += direction * trend_strength
        returns += trend

    # ロンドンオープン時にレンジブレイクの傾向を入れる (session_effect)
    if session_effect:
        for day_start in range(0, n_bars, 24):
            if day_start + 10 >= n_bars:
                break
            # 東京レンジの方向に少し弾む (50-60%の日)
            tokyo_ret = returns[day_start:day_start + 7].sum()
            if rng.random() < 0.55:  # 55%の日でトレンド継続
                returns[day_start + 7] += np.sign(tokyo_ret) * rng.uniform(0.0003, 0.0008)

    prices = start_price * np.exp(np.cumsum(returns))

    # OHLC
    noise = rng.uniform(0.0001, 0.0004, (n_bars, 2))
    high = prices * (1 + noise[:, 0])
    low = prices * (1 - noise[:, 1])
    # high/low が close を包含するよう補正
    high = np.maximum(high, prices * 1.00005)
    low = np.minimum(low, prices * 0.99995)
    open_ = np.concatenate([[start_price], prices[:-1]])
    # open も high/low の間に収める
    high = np.maximum(high, open_)
    low = np.minimum(low, open_)

    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": prices},
        index=idx,
    )


def pure_random_h1(n_days: int = 365 * 3, seed: int = 99) -> pd.DataFrame:
    """セッション効果なしの純ランダム"""
    return generate_fx_h1(
        n_days=n_days, seed=seed,
        trend_strength=0.0, session_effect=False,
    )


# ============================================================
# メイン
# ============================================================

def print_stats(stats: dict):
    print(f"  [{stats.get('label', '')}]")
    if stats["n_trades"] == 0:
        print("    No trades")
        return
    print(f"    Trades     : {stats['n_trades']}  ({stats['long/short']})")
    print(f"    Total pips : {stats['total_pips']:+.1f}")
    print(f"    Win rate   : {stats['win_rate']*100:.1f}%")
    print(f"    Avg win    : {stats['avg_win']:.1f} pips")
    print(f"    Avg loss   : {stats['avg_loss']:.1f} pips")
    print(f"    PF         : {stats['profit_factor']:.2f}")
    print(f"    Max DD     : {stats['max_dd_pips']:.1f} pips")
    print(f"    Exits      : {stats['exit_reasons']}")


def main():
    print("=" * 70)
    print("London Breakout Strategy - Full Validation")
    print("=" * 70)

    # ----------------------------------------------------------
    # Test 1: セッション効果ありデータ vs 純ランダム
    # ----------------------------------------------------------
    print("\n--- Test 1: Session effect vs Pure random ---")

    df_session = generate_fx_h1(n_days=365*3, seed=42, session_effect=True)
    df_random = pure_random_h1(n_days=365*3, seed=99)

    trades_session = london_breakout(df_session)
    trades_random = london_breakout(df_random)

    stats_s = compute_stats(trades_session, "With session effect")
    stats_r = compute_stats(trades_random, "Pure random")
    print_stats(stats_s)
    print_stats(stats_r)

    print("\n  -> Session effect data shows edge? "
          f"{'YES' if stats_s['total_pips'] > 0 and stats_r['total_pips'] <= 0 else 'CHECK MANUALLY'}")
    print("  -> Random data should show NO edge (negative or near-zero pips)")

    # ----------------------------------------------------------
    # Test 2: Parameter robustness
    # ----------------------------------------------------------
    print("\n--- Test 2: Parameter robustness (session data) ---")
    print(f"  {'buffer':>8} {'RR':>6} {'trades':>8} {'pips':>10} {'win%':>8} {'PF':>8}")

    for buffer in [1.0, 3.0, 5.0, 8.0]:
        for rr in [1.0, 1.5, 2.0, 2.5]:
            tr = london_breakout(df_session, buffer_pips=buffer, risk_reward=rr)
            if len(tr) > 20:
                s = compute_stats(tr)
                print(f"  {buffer:>8.1f} {rr:>6.1f} {s['n_trades']:>8} "
                      f"{s['total_pips']:>10.1f} {s['win_rate']*100:>7.1f}% "
                      f"{s['profit_factor']:>8.2f}")

    # ----------------------------------------------------------
    # Test 3: Walk-forward analysis
    # ----------------------------------------------------------
    print("\n--- Test 3: Walk-forward analysis ---")

    df_wf = generate_fx_h1(n_days=365*4, seed=123, session_effect=True)
    train_days = 365
    test_days = 90
    total_days = len(df_wf) // 24

    buffers = [1.0, 3.0, 5.0, 8.0]
    rrs = [1.0, 1.5, 2.0, 2.5]

    wf_segments = []
    day = 0
    while day + train_days + test_days <= total_days:
        train_start = day * 24
        train_end = (day + train_days) * 24
        test_start = train_end
        test_end = min((day + train_days + test_days) * 24, len(df_wf))

        df_tr = df_wf.iloc[train_start:train_end]
        df_te = df_wf.iloc[test_start:test_end]

        # 訓練期間で最良パラメータを探す
        best_pips = -np.inf
        best_params = (3.0, 1.5)
        for buf in buffers:
            for rr in rrs:
                tr = london_breakout(df_tr, buffer_pips=buf, risk_reward=rr)
                if len(tr) >= 10:
                    s = compute_stats(tr)
                    if s["total_pips"] > best_pips:
                        best_pips = s["total_pips"]
                        best_params = (buf, rr)

        # 検証期間でそのパラメータを適用
        test_trades = london_breakout(
            df_te, buffer_pips=best_params[0], risk_reward=best_params[1]
        )
        test_stats = compute_stats(test_trades)

        wf_segments.append({
            "period": f"{df_te.index[0].date()} ~ {df_te.index[-1].date()}",
            "best_params": best_params,
            "train_pips": best_pips,
            "test_pips": test_stats["total_pips"],
            "test_trades": test_stats["n_trades"],
            "test_wr": test_stats.get("win_rate", 0),
            "pnls": [t.pnl_pips for t in test_trades],
        })
        day += test_days

    print(f"  {'Period':<30} {'Params':<12} {'Train':>8} {'Test':>8} {'Trades':>8} {'WR':>6}")
    total_oos_pips = 0
    total_oos_trades = 0
    for seg in wf_segments:
        b, r = seg["best_params"]
        print(f"  {seg['period']:<30} buf={b}/rr={r:<4} "
              f"{seg['train_pips']:>+8.1f} {seg['test_pips']:>+8.1f} "
              f"{seg['test_trades']:>8} {seg['test_wr']*100:>5.1f}%")
        total_oos_pips += seg["test_pips"]
        total_oos_trades += seg["test_trades"]

    print(f"\n  Out-of-sample total : {total_oos_pips:+.1f} pips over {total_oos_trades} trades")
    avg_per_seg = total_oos_pips / len(wf_segments) if wf_segments else 0
    wins = sum(1 for s in wf_segments if s["test_pips"] > 0)
    print(f"  Avg per segment     : {avg_per_seg:+.1f} pips")
    print(f"  Winning segments    : {wins}/{len(wf_segments)}")

    # ----------------------------------------------------------
    # Chart: Equity curve comparison + walk-forward
    # ----------------------------------------------------------
    fig, axes = plt.subplots(2, 2, figsize=(13, 9))

    # (0,0) Session data equity
    pnls_s = [t.pnl_pips for t in trades_session]
    cum_s = np.cumsum(pnls_s)
    axes[0, 0].plot(cum_s, color="#27ae60", lw=1.2)
    axes[0, 0].axhline(0, color="black", lw=0.5)
    axes[0, 0].set_title("With session effect (in-sample)")
    axes[0, 0].set_ylabel("Cumulative pips")
    axes[0, 0].grid(alpha=0.3)

    # (0,1) Random data equity
    pnls_r = [t.pnl_pips for t in trades_random]
    cum_r = np.cumsum(pnls_r)
    axes[0, 1].plot(cum_r, color="#e74c3c", lw=1.2)
    axes[0, 1].axhline(0, color="black", lw=0.5)
    axes[0, 1].set_title("Pure random (no edge)")
    axes[0, 1].set_ylabel("Cumulative pips")
    axes[0, 1].grid(alpha=0.3)

    # (1,0) Walk-forward equity
    all_oos_pnls = []
    for seg in wf_segments:
        all_oos_pnls.extend(seg["pnls"])
    if all_oos_pnls:
        cum_oos = np.cumsum(all_oos_pnls)
        axes[1, 0].plot(cum_oos, color="#3498db", lw=1.2)
        axes[1, 0].axhline(0, color="black", lw=0.5)
    axes[1, 0].set_title("Walk-forward (out-of-sample)")
    axes[1, 0].set_ylabel("Cumulative pips")
    axes[1, 0].set_xlabel("Trade #")
    axes[1, 0].grid(alpha=0.3)

    # (1,1) Trade distribution
    if pnls_s:
        axes[1, 1].hist(pnls_s, bins=40, color="#95a5a6", edgecolor="white", alpha=0.8)
        axes[1, 1].axvline(0, color="red", lw=1)
        avg = np.mean(pnls_s)
        axes[1, 1].axvline(avg, color="#27ae60", lw=1.5, ls="--", label=f"Mean: {avg:.1f}")
        axes[1, 1].legend()
    axes[1, 1].set_title("PnL distribution (session data)")
    axes[1, 1].set_xlabel("pips per trade")
    axes[1, 1].grid(alpha=0.3)

    plt.suptitle("London Breakout Strategy - Validation Suite", fontsize=14, y=1.01)
    plt.tight_layout()
    output_path = Path(__file__).resolve().parents[1] / "results" / "london_breakout_validation.png"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, dpi=120, bbox_inches="tight")
    print(f"\nChart saved: {output_path}")

    # ----------------------------------------------------------
    # Summary
    # ----------------------------------------------------------
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"  Session data in-sample : {sum(pnls_s):+.1f} pips / {len(pnls_s)} trades")
    print(f"  Random data            : {sum(pnls_r):+.1f} pips / {len(pnls_r)} trades")
    print(f"  Walk-forward OOS       : {total_oos_pips:+.1f} pips / {total_oos_trades} trades")
    print()
    if total_oos_pips > 0 and sum(pnls_r) <= 0:
        print("  -> Strategy shows POTENTIAL edge:")
        print("     - Positive on session data")
        print("     - Negative on random (confirms edge is from session structure)")
        print("     - Positive OOS in walk-forward")
        print("     HOWEVER: This is synthetic data. Real market validation needed.")
    else:
        print("  -> Results inconclusive or no edge detected.")
        print("     Review parameters or strategy logic.")


if __name__ == "__main__":
    main()
