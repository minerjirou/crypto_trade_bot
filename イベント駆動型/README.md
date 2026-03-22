# crypto-bot

小資金向けのイベント駆動型暗号資産トレーディング bot です。  
MVP の主戦略は「新しめアルトの先物-現物乖離 extreme 逆張り + Funding フィルタ」で、まずは `dry-run` / `paper mode` を完成させる前提で実装しています。

## 現在の状態

現時点では、以下まで実装済みです。

- 設定ファイル読み込み
- 共通ドメインモデル
- basis / z-score ベースの特徴量計算
- Basis Extreme Reversal 戦略の MVP
- リスク判定
- 分割エントリー前提の注文計画
- SQLite へのイベント保存
- 分析・自己改善向けの run / journal / note 保存
- dry-run CLI
- MEXC / Bitget adapter の public 骨格

まだ本番自動売買の段階ではありません。  
private API 実装、実約定処理、paper mode の高度化、replay/backtest、live mode はこれからです。

## 戦略の考え方

- `basis = perp_mid / spot_mid - 1`
- rolling mean / std から `basis_z` を計算
- `abs(basis_z)` が大きい局面だけ候補化
- Funding を悪条件フィルタとして使用
- 上場後日数、出来高、スプレッド、板厚を考慮
- リスク条件を満たした場合のみ注文計画を生成

小資金前提のため、常時売買ではなく「条件成立時だけ動く」構成を重視しています。

## ディレクトリ構成

```text
config/                 設定例
docs/                   仕様書
src/crypto_bot/
  adapters/             取引所 adapter
  cli/                  CLI
  core/                 設定・モデル・イベント・ロギング
  execution/            注文計画
  features/             basis / z-score 計算
  risk/                 リスク判定
  storage/              SQLite recorder
  strategies/           売買戦略
tests/                  ユニットテスト
```

## セットアップ

Python `3.12+` を前提にしています。

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e .[dev]
```

依存を最小にしているため、最初は `PyYAML` のみで動作します。

## 実行

dry-run を実行します。

```powershell
$env:PYTHONPATH = "src"
python -m crypto_bot.cli.run_dry --config config/settings.example.yaml
```

またはエントリーポイントを使います。

```powershell
crypto-bot-dry-run --config config/settings.example.yaml
```

現在の `dry-run` はサンプル market snapshot を入力として流し、特徴量計算から注文 ACK 保存までを確認するモードです。

## テスト

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
```

## 保存されるデータ

SQLite は `config/settings.example.yaml` の `storage.sqlite_path` に保存されます。  
主なテーブルは以下です。

- `events`: 生イベントログ
- `runs`: 実行単位のメタ情報
- `signal_journal`: 特徴量、候補、採否、注文計画を横断した分析用テーブル
- `agent_notes`: Codex / ClaudeCode などが残す所見や改善メモ

この構成により、あとから以下のような分析がしやすくなります。

- どの `basis_z` / `funding_rate` / `spread_bps` で候補化されたか
- 採用 / reject の理由は何か
- どの設定で run されたか
- AI が次回改善用に何をメモしたか

`SqliteRecorder.build_analysis_bundle(run_id)` を使うと、特定 run の分析データをまとめて取り出せます。

## 設定

設定例は `config/settings.example.yaml` にあります。主な項目:

- `app`: 実行モード
- `universe`: 対象銘柄条件
- `strategy`: basis 戦略パラメータ
- `risk`: 1 トレード損失、日次損失、同時保有数など
- `execution`: post-only、分割数、TTL など
- `fees`: 手数料のデフォルト値と取引所上書き
- `storage`: SQLite 保存先

## 開発方針

- Python 3.12+
- 型ヒント必須
- `Decimal` で金額処理
- JSON 構造化ログ
- UTC 基準で保存
- adapter / strategy / risk / storage を分離
- 外部 API 呼び出しには timeout / retry / rate-limit を入れる
- まず dry-run / paper mode を固め、その後 live を有効化する

## 仕様書

設計意図や要件は `docs/` にまとまっています。

- `docs/01_PRD.md`
- `docs/02_REQUIREMENTS.md`
- `docs/03_ARCHITECTURE.md`
- `docs/04_EXCHANGE_INTEGRATION.md`
- `docs/05_STRATEGY_SPEC.md`
- `docs/06_RISK_POLICY.md`
- `docs/07_TEST_PLAN.md`
- `docs/08_TASK_BREAKDOWN.md`

## 次の実装候補

- MEXC / Bitget の実データ normalizer
- private API と paper mode の拡張
- fill / position / PnL / exit reason の保存
- replay / backtest
- kill-switch と reconnect の強化
