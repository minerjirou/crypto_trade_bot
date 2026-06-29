# PLAN.md — フェーズ4.5 実データ検証

## 実行方式

Claude Code が各 Step の仕様を設計し、Codex に実装を委任する。
Claude Code はコードを書かない。設計→委任→レビューのサイクルを回す。

```
[Claude Code]          [Codex]              [開発者]
  仕様設計 ──→ /codex:rescue 実装指示
                        実装・テスト実行
              /codex:result ←── 成果物
  レビュー
  OK → 次Step
  NG → 修正指示 ──→ /codex:rescue 再実装
  ...
  🔴 CHECKPOINT ────────────────────→ 確認待ち
```

---

## Step 0: 環境確認

### Claude Code がやること
1. `/codex:setup` を実行して Codex の状態を確認
2. 問題があれば開発者に報告

### 完了したら → Step 1

---

## Step 1: プロジェクト構造の整備

### Claude Code がやること

以下の仕様で Codex に委任:

```
/codex:rescue プロジェクトの初期構造を整備して。

1. 以下のディレクトリを作成 (存在しなければ):
   data/ strategies/ backtest/ live/ tests/ configs/ results/ notebooks/ utils/

2. requirements.txt を作成:
   pandas>=2.0
   numpy>=1.24
   matplotlib>=3.7
   oandapyV20>=0.7
   python-dotenv>=1.0
   loguru>=0.7
   pyyaml>=6.0
   pytest>=7.0

3. pip install -r requirements.txt を実行

4. .gitignore を作成:
   .env
   data/*.csv
   results/
   __pycache__/
   *.pyc
   .pytest_cache/
   notebooks/.ipynb_checkpoints/
   venv/
   .codex/

5. .env.example を作成:
   OANDA_ENV=practice
   OANDA_ACCOUNT_ID=xxx-xxx-xxxxxxx-xxx
   OANDA_TOKEN=your_personal_access_token_here

6. configs/london_breakout.yaml を作成:
   strategy:
     tokyo_start: 0
     tokyo_end: 7
     london_end: 15
     buffer_pips: 3.0
     risk_reward: 1.5
     min_range_pips: 10
     max_range_pips: 100
   backtest:
     spread_pips: 1.0
     slippage_pips: 0.5
   instruments:
     USD_JPY:
       pip_size: 0.01
     EUR_USD:
       pip_size: 0.0001
     GBP_USD:
       pip_size: 0.0001
     GBP_JPY:
       pip_size: 0.01

7. 最後に以下を実行して全ライブラリの import を確認:
   python -c "import pandas, numpy, matplotlib, oandapyV20, dotenv, loguru, yaml; print('ALL OK')"
```

### Claude Code のレビュー観点
- ディレクトリ構造が CLAUDE.md と一致しているか
- requirements.txt に不要な依存が追加されていないか

### 完了したら → Step 2

---

## Step 2: ユニットテスト作成

### Claude Code がやること

以下の仕様で Codex に委任:

```
/codex:rescue tests/test_london_breakout.py を作成して。

strategies/london_breakout.py の london_breakout() 関数のユニットテスト。
以下の 10 テストケースを実装すること。

■ 共通の前提
- テスト用の DataFrame は pytest fixture で作成
- 日付は 2023-01-02 (月曜) UTC
- 1時間足 (H1)、カラムは open, high, low, close
- pip_size=0.01 (USD/JPY 想定)
- 浮動小数点比較は pytest.approx(abs=1e-6)
- from strategies.london_breakout import london_breakout, compute_stats, Trade

■ テストケース

1. test_tokyo_range_calculation
   東京時間 (UTC 0-6) に7本のバーを作成。
   high=[150.50, 150.80, 150.60, 150.70, 150.90, 150.55, 150.65]
   low=[150.30, 150.40, 150.35, 150.45, 150.50, 150.25, 150.40]
   → レンジ high=150.90, low=150.25 を確認

2. test_breakline_with_buffer
   buffer_pips=3.0, pip_size=0.01 の場合:
   break_high = 150.90 + 3.0 * 0.01 = 150.93
   break_low = 150.25 - 3.0 * 0.01 = 150.22
   → ロンドン時間のバーで 150.93 を超えたらロング発生を確認

3. test_long_entry_on_upward_break
   ロンドン時間の bar.high が break_high を超える設定。
   → direction=1 のトレードが1つ発生
   → entry_price に spread+slippage が加算されていること

4. test_short_entry_on_downward_break
   ロンドン時間の bar.low が break_low を下回る設定。
   → direction=-1 のトレードが1つ発生

5. test_stop_loss_triggered
   エントリー後、次のバーで SL 価格に到達する設定。
   → exit_reason == "stop_loss"
   → pnl_pips が負であること

6. test_take_profit_triggered
   エントリー後、次のバーで TP 価格に到達する設定。
   → exit_reason == "take_profit"
   → pnl_pips が正であること

7. test_time_exit
   SL にも TP にも到達せずロンドン終了。
   → exit_reason == "time_exit"

8. test_range_filter_too_narrow
   東京レンジ幅が min_range (10 pips) 未満。
   → トレードなし (空リスト)

9. test_range_filter_too_wide
   東京レンジ幅が max_range (100 pips) 超。
   → トレードなし (空リスト)

10. test_one_trade_per_day
    上ブレイクで約定後、同日にさらに下ブレイクが発生する設定。
    → トレードは1つだけ

11. test_no_lookahead
    ロンドン時間のバーを変更しても、東京レンジ (range_high, range_low) が変わらないこと。
    2パターンの DataFrame を作り、東京時間のバーは同一、ロンドン時間のバーだけ変更。
    → 両方でレンジ値が同一

■ 禁止事項
- 新しいライブラリを追加しない
- london_breakout.py 自体を変更しない
- テスト内で print や sleep を使わない

■ 完了条件
pytest tests/test_london_breakout.py -v を実行し、全テスト PASS を確認。
テスト結果のコンソール出力を報告すること。
```

### Claude Code のレビュー観点

`/codex:result` で成果物を取得後:

1. テストが本当に意味のある検証をしているか(assert が形骸化していないか)
2. fixture の DataFrame が OHLC として整合しているか(high >= open,close >= low)
3. ルックアヘッドテストが実際に独立性を検証しているか

問題あれば修正仕様を作成して `/codex:rescue` で再委任。

### 完了したら → Step 3

---

## Step 3: ヒストリカルデータ取得 (HistData.com)

> **変更理由**: OANDA REST API がアカウント制約により利用不可。
> トレードも MT5 経由でしか行えないため、データ取得・ライブ運用ともに
> OANDA API に依存しない方式に切り替える。

### データソース

**HistData.com** (https://www.histdata.com/download-free-forex-data/)
- 無料・登録不要
- 1分足 (M1) CSV を提供
- 既存の `data/load_histdata.py` で M1 → H1 リサンプル可能

### 開発者がやること (手動作業)

1. HistData.com から以下の通貨ペアの **ASCII形式 M1 データ** をダウンロード:
   - USD/JPY: 2022年, 2023年, 2024年, 2025年 (各年ごとのZIP)
   - EUR/USD: 同上
   - GBP/JPY: 同上

2. ダウンロードした ZIP を以下に展開:
   ```
   data/histdata_usdjpy/   ← USD/JPY の CSV ファイル群
   data/histdata_eurusd/   ← EUR/USD の CSV ファイル群
   data/histdata_gbpjpy/   ← GBP/JPY の CSV ファイル群
   ```

3. Claude Code に「データ配置完了」と報告

### Claude Code がやること

開発者からデータ配置完了の報告を受けたら Codex に委任:

```
/codex:rescue HistData.com の M1 データを H1 にリサンプルして。
作業ディレクトリは C:\Users\minerjirou\Documents\シストレ\FX\London_breakout

python data/load_histdata.py --dir data/histdata_usdjpy/ --output data/USD_JPY_H1.csv
python data/load_histdata.py --dir data/histdata_eurusd/ --output data/EUR_USD_H1.csv
python data/load_histdata.py --dir data/histdata_gbpjpy/ --output data/GBP_JPY_H1.csv

変換後、各CSVについて以下を確認して結果を報告:
1. ファイル存在と行数 (20,000以上が期待値)
2. NaN の数
3. close の min/max (USD/JPY: 100-200, EUR/USD: 0.9-1.5, GBP/JPY: 140-250)
4. 先頭と末尾の日時
5. 週末 (土日) のバーが含まれていないか確認

エラーが出た場合:
- FileNotFoundError → ディレクトリパスを確認して報告
- CSV形式エラー → load_histdata.py の形式判定を確認して報告
```

### Claude Code のレビュー観点
- 行数が期待範囲か (3年分 H1 ≈ 約 19,000-20,000 本)
- 価格が合理的か (異常値は相場変動かデータ破損かを判断)
- UTC タイムゾーンが正しく設定されているか
- 週末データが除外されているか

### 完了したら → Step 4

---

## Step 4: 実データバックテスト

### Claude Code がやること

```
/codex:rescue 以下のコマンドで London Breakout 戦略を実データで検証して。

python backtest/validate_london_real.py --file data/USD_JPY_H1.csv --pip-size 0.01 --output-dir results
python backtest/validate_london_real.py --file data/EUR_USD_H1.csv --pip-size 0.0001 --output-dir results
python backtest/validate_london_real.py --file data/GBP_JPY_H1.csv --pip-size 0.01 --output-dir results

各実行のコンソール出力を全文保存して報告すること。
results/ ディレクトリにチャート画像が生成されることを確認。

エラーが出た場合:
- ImportError → pip install で解決してリトライ
- FileNotFoundError → どのファイルが無いか報告
- その他 → エラーメッセージ全文を報告
```

### Claude Code のレビュー観点

Codex から結果を受け取ったら、以下を判断:

1. **取引回数**: 100回以上あるか → 少なければ min_range 調整を検討
2. **PF**: 1.0以上か → 未満なら戦略にエッジなし
3. **WF結果**: OOS合計がプラスか → マイナスなら過学習の疑い
4. **頑健性**: 75%以上のパラメータ組でプラスか
5. **合成データとの乖離**: 合成(PF=1.85)と実データの差がどの程度か

判断に基づき、必要なら追加分析を Codex に委任:

```
/codex:rescue --background validate_london_real.py の結果から、負けが集中している期間を特定して。
具体的には:
1. results/ の月次データから、最もドローダウンが大きかった3ヶ月間を抽出
2. その期間に何が起きていたか (大きなトレンド? レンジ? ボラ低下?) をデータから分析
3. 結果を results/drawdown_analysis.md に出力
```

### 完了したら → Step 5

---

## Step 5: 結果レポート作成

### Claude Code がやること

```
/codex:rescue results/validation_summary.md を作成して。

以下のテンプレートに Step 4 の結果を埋めること。
数値は validate_london_real.py のコンソール出力から正確に転記。
推測や概算は入れない。

---テンプレート開始---

# London Breakout 実データ検証サマリー

## 検証条件
- 検証日: (今日の日付)
- データ期間: (各ペアの実際の期間)
- データソース: OANDA v20 API (practice)
- 時間軸: H1
- デフォルトパラメータ: buffer=3.0, RR=1.5, spread=1.0, slippage=0.5

## 全期間バックテスト結果

| 指標 | USD/JPY | EUR/USD | GBP/JPY |
|------|---------|---------|---------|
| 取引回数 | | | |
| 累積 pips | | | |
| 勝率 | | | |
| PF | | | |
| 最大DD (pips) | | | |
| Avg Win (pips) | | | |
| Avg Loss (pips) | | | |
| Exit: TP/SL/Time | | | |

## パラメータ頑健性

| 指標 | USD/JPY | EUR/USD | GBP/JPY |
|------|---------|---------|---------|
| プラス組数/全組数 | | | |
| 評価 | | | |

## ウォークフォワード (OOS)

| 指標 | USD/JPY | EUR/USD | GBP/JPY |
|------|---------|---------|---------|
| OOS累積 pips | | | |
| 勝ちセグメント | | | |
| Train/Test相関 | | | |

## VERDICT チェックリスト

| チェック項目 | USD/JPY | EUR/USD | GBP/JPY |
|-------------|---------|---------|---------|
| 全期間プラス | | | |
| PF > 1.0 | | | |
| 勝率 > 45% | | | |
| 取引100回以上 | | | |
| 頑健性75%以上 | | | |
| WFプラス | | | |
| WF勝ち>50% | | | |
| 負け月<50% | | | |

## 合成データとの比較

| 指標 | 合成データ | USD/JPY実データ | 乖離率 |
|------|-----------|----------------|--------|
| 累積 pips | +4,515.6 | | |
| 勝率 | 56.7% | | |
| PF | 1.85 | | |

## 総合判定

GO条件: 8項目中6PASS + 2ペア以上WFプラス + 頑健性75%以上
CONDITIONAL: 4-5 PASS
NO-GO: 3以下 PASS

判定: 

## 次のアクション推奨


---テンプレート終了---
```

### Claude Code のレビュー観点
- 数値がコンソール出力と一致しているか (転記ミス)
- 判定基準が正しく適用されているか
- 「次のアクション推奨」が判定と整合しているか

問題あれば修正指示して再委任。

### 完了したら → 🔴 REVIEW CHECKPOINT

---

## 🔴 REVIEW CHECKPOINT: 実データ検証結果

**Claude Code はここで停止し、開発者に報告する。**

報告内容:
1. validation_summary.md の要約 (各ペアの主要数値と判定)
2. 合成データとの乖離の解釈
3. チャート画像のパス
4. Claude Code としての所見 (懸念、推奨事項)

開発者の応答と対応:
- 「GO」→ フェーズ5 (MT5デモ運用bot) の PLAN.md を設計して Codex に実装させる
- 「CONDITIONAL、○○調整」→ 修正方針を設計して Codex に実装させ、Step 4-5 再実行
- 「NO-GO」→ 問題の根本原因を分析し、代替戦略を提案
- 「別ペアも」→ Step 3-5 を追加ペアで実行

---

## フェーズ5 予告: MT5 ライブ運用 Bot

> OANDA REST API が利用不可のため、ライブトレードは **MetaTrader5 Python パッケージ** 経由で行う。

### アーキテクチャ

```
[Python Bot (live/mt5_london_bot.py)]
    │
    ├── MetaTrader5 パッケージ (pip install MetaTrader5)
    │     ├── mt5.copy_rates_range()  ← H1データ取得 (東京レンジ算出用)
    │     ├── mt5.order_send()        ← エントリー/SL/TP 注文
    │     └── mt5.positions_get()     ← ポジション管理
    │
    ├── strategies/london_breakout.py  ← 既存の戦略ロジックをそのまま利用
    │
    └── configs/london_breakout.yaml   ← パラメータ設定
```

### 主要機能 (フェーズ5 で実装)
1. MT5 接続・認証
2. H1 データ取得 (mt5.copy_rates_range)
3. london_breakout() でシグナル算出
4. MT5 経由で注文送信 (成行 + SL/TP)
5. ポジション監視・time_exit 処理
6. ログ出力 (loguru)
7. スケジューラ (毎日ロンドン時間開始前に起動)

### 前提条件
- Windows 11 (MT5 は Windows 専用) ✅
- MT5 デスクトップアプリがインストール済みであること
- デモ口座でのテスト後、本番口座に切り替え

---

## トラブルシューティング

### /codex:rescue が失敗する
→ `/codex:setup` で状態確認。未インストールなら開発者に報告。

### Codex の実装が絶対ルールに違反している
→ 違反箇所を特定し、修正仕様を明確にして `/codex:rescue` で再委任。
→ 3回修正しても直らなければ、違反箇所とログを開発者に報告。

### .env が未設定
→ 開発者に報告して待つ。

### データ取得でAPI認証エラー
→ 開発者に報告して待つ。

### バックテストでトレード数が少ない (<50)
→ 原因分析 (レンジフィルタか? データ欠損か?) を行い、
   min_range_pips=5 での再実行を Codex に委任。
