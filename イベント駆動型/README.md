# crypto-bot

300 USD 規模を想定した、イベント駆動型の暗号資産トレーディング bot です。  
主戦略は「新しめアルトの先物-現物乖離 extreme 逆張り + Funding フィルタ」で、まずは `dry-run` と `paper` を回しながら戦略・記録・分析基盤を固める構成です。

## いま動くもの

- 設定ファイル読み込み
- 共通ドメインモデル
- basis / rolling z-score 特徴量計算
- Basis Extreme Reversal 戦略
- リスク判定
- 分割エントリー計画
- exit 判定と reduce-only クローズ
- dry-run execution
- paper execution
- replay 実行
- report / CSV export
- SQLite への run / signal / order / fill / pnl / outcome / note 保存
- MEXC / Bitget public adapter の骨格
- adapter registry
- symbol normalizer

## まだ未実装のもの

- MEXC / Bitget の live private API
- 実 WebSocket reconnect / resubscribe
- 本番自動売買
- 複数銘柄の実スキャンとランキング
- 実取引所データによる継続稼働パス
- 本格的な backtest / parameter sweep

現状は「ローカルで dry-run / paper / replay を回し、結果を保存・分析する」ところまでは通っています。

## 構成

```text
config/                 設定例
docs/                   要件・設計書
exports/                report --export-csv の出力先
src/crypto_bot/
  adapters/             取引所 adapter
  cli/                  dry-run / paper / replay / report
  collectors/           demo / replay / normalizer
  core/                 設定・モデル・runner・イベント・ロギング
  execution/            注文計画
  features/             basis / z-score
  risk/                 リスク判定
  storage/              SQLite / report / export
  strategies/           売買戦略
tests/                  ユニットテスト
```

## セットアップ

Python `3.12+` 前提です。

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e .[dev]
```

## 実行モード

`dry-run`

- 注文 ACK まで確認する軽量モード
- fill は発生しない
- 戦略と記録の流れを手早く確認する用途

```powershell
$env:PYTHONPATH = "src"
python -m crypto_bot.cli.run_dry --config config/settings.example.yaml
```

または:

```powershell
crypto-bot-dry-run --config config/settings.example.yaml
```

`paper`

- 約定、ポジション、PnL、trade outcome までシミュレートする
- 現状で一番実用的な検証モード

```powershell
$env:PYTHONPATH = "src"
python -m crypto_bot.cli.run_paper --config config/settings.example.yaml
```

または:

```powershell
crypto-bot-paper --config config/settings.example.yaml
```

`replay`

- JSONL の market snapshot を再生する
- recorded data に対して deterministic に挙動確認したいときに使う

```powershell
$env:PYTHONPATH = "src"
python -m crypto_bot.cli.replay --config config/settings.example.yaml --input path\to\replay.jsonl
```

または:

```powershell
crypto-bot-replay --config config/settings.example.yaml --input path\to\replay.jsonl
```

`report`

- 最新 run か指定 run の集計を表示する
- 必要なら CSV export も行う

```powershell
$env:PYTHONPATH = "src"
python -m crypto_bot.cli.report --config config/settings.example.yaml --export-csv
```

または:

```powershell
crypto-bot-report --config config/settings.example.yaml --export-csv
```

## 保存されるデータ

SQLite は `config/settings.example.yaml` の `storage.sqlite_path` に保存されます。  
主なテーブル:

- `events`: 生イベントログ
- `runs`: 実行単位のメタ情報
- `signal_journal`: 特徴量、候補、採否、執行計画を横断した分析用テーブル
- `order_acks`: 発注 ACK
- `fills`: 約定
- `position_snapshots`: ポジション推移
- `pnl_snapshots`: 実現 / 含み / fee の時系列
- `trade_outcomes`: exit reason を含むトレード結果
- `agent_notes`: Codex / ClaudeCode 向けメモ

`SqliteRecorder.build_analysis_bundle(run_id)` で、特定 run の分析データをまとめて取り出せます。

## CSV export

`report --export-csv` を実行すると `exports/` に run ごとの CSV が出ます。

例:

- `*_journal.csv`
- `*_orders.csv`
- `*_fills.csv`
- `*_pnl.csv`
- `*_outcomes.csv`
- `*_notes.csv`

これをそのまま AI に読ませて、reject 理由、entry 条件、exit 条件、PnL の偏りを分析できます。

## 設定

設定例は [config/settings.example.yaml](c:\Users\Y_Kofuji\Documents\プログラム置き場\仮想通貨bot\イベント駆動型\config\settings.example.yaml) にあります。主な項目:

- `app`: 実行モードの基本設定
- `universe`: 上場日数、出来高、スプレッドなどの対象条件
- `strategy`: basis window、entry / exit z-score、funding filter
- `risk`: 1 トレード損失、日次損失、同時保有数、連敗制限
- `execution`: post-only、分割数、TTL、緊急クローズ設定
- `fees`: デフォルト fee と exchange 上書き
- `storage`: SQLite / export の出力先

## テスト

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
```

現状のテストでは、以下を確認しています。

- basis / z-score 計算
- リスク制限
- SQLite 分析バンドル生成
- replay ローダー
- paper session の fill / outcome / report

## 開発方針

- Python 3.12+
- 型ヒント必須
- 金額は `Decimal`
- ログは JSON 構造化
- UTC 基準で保存
- `adapter / strategy / risk / storage` を分離
- 外部 API 呼び出しには timeout / retry / rate-limit を入れる
- dry-run / paper を固めてから live を有効化する

## 仕様書

詳細な要件と設計意図は `docs/` にあります。

- `docs/01_PRD.md`
- `docs/02_REQUIREMENTS.md`
- `docs/03_ARCHITECTURE.md`
- `docs/04_EXCHANGE_INTEGRATION.md`
- `docs/05_STRATEGY_SPEC.md`
- `docs/06_RISK_POLICY.md`
- `docs/07_TEST_PLAN.md`
- `docs/08_TASK_BREAKDOWN.md`

## 次に詰めるべきところ

- MEXC / Bitget private API
- 実 WS market data と reconnect 制御
- 複数銘柄ランキング
- 実 fill ベースの fee / slippage 詳細化
- recorded data を使う backtest 強化
