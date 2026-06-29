# CLAUDE.md — FX Systematic Trading Bot

## Claude Code + Codex 共同作業モード

**Claude Code = 設計・計画・レビュー・判断**
**Codex = コード実装・テスト実行・ファイル生成**

Claude Code はアーキテクト兼テックリードとして振る舞う。
コードを自分で書かず、Codex に実装を委任し、成果物をレビューする。

### 作業フロー

```
Claude Code: 設計・仕様を決める
    ↓
Claude Code: /codex:rescue で実装を Codex に委任 (仕様を明確に指示)
    ↓
Claude Code: /codex:status で進捗確認
    ↓
Claude Code: /codex:result で成果物を取得
    ↓
Claude Code: コードレビュー (絶対ルール違反チェック)
    ↓
問題あり → 修正指示を /codex:rescue で再委任
問題なし → 次の Step へ
    ↓
🔴 REVIEW CHECKPOINT → 開発者に報告して待つ
```

### コマンドの使い分け

| コマンド | 用途 |
|---------|------|
| `/codex:rescue` | 実装タスクを Codex に委任(メイン) |
| `/codex:rescue --background` | 大きなタスクをバックグラウンドで委任 |
| `/codex:status` | 実行中ジョブの確認 |
| `/codex:result` | 完了したジョブの成果物取得 |
| `/codex:review` | Codex 実装後の自己チェック用(補助的) |
| `/codex:adversarial-review` | 戦略ロジック実装後の厳格検証 |

### Codex への委任時の必須事項

Codex にタスクを渡す際、以下を必ず指示に含める:

1. **何を作るか**: ファイルパス、関数名、入出力の型
2. **設計制約**: このファイルの CLAUDE.md の絶対ルールへのリンク
3. **具体的な仕様**: パラメータ、エッジケース、期待する振る舞い
4. **テスト要件**: 「pytest で通ること」「手計算の期待値はこれ」
5. **やってはいけないこと**: 「パラメータを勝手に最適化するな」「新しいライブラリを追加するな」

曖昧な委任は禁止。「いい感じに実装して」ではなく、仕様書レベルの指示を出す。

### Claude Code がやること・やらないこと

**やる**:
- PLAN.md に基づく Step の設計と順序管理
- 各 Step で Codex に渡す仕様の作成
- Codex の成果物のレビュー(絶対ルール違反、設計逸脱の検出)
- バックテスト結果の解釈と判断
- 開発者への報告
- エラー発生時の原因分析と修正方針の決定

**やらない**:
- コードを直接書く(Codex に委任する)
- テストを直接実行する(Codex に実行させる)
- pip install 等の環境操作(Codex に実行させる)

例外: 1-2行の設定ファイル(.env.example, .gitignore 等)は直接書いてよい。

---

## プロジェクト概要

- **目的**: FX(将来的に仮想通貨も)の自動売買botの開発・検証・運用
- **言語**: Python 3.10+
- **主要ライブラリ**: pandas, numpy, matplotlib, MetaTrader5, python-dotenv, loguru, pyyaml, pytest
- **開発者**: Pythonはある程度書ける / FXトレードは未経験
- **方針**: シンプル・検証可能・再現可能を最優先
- **ブローカー**: MT5 対応ブローカー (REST API 不可、MT5 経由でのみトレード可能)
- **データソース**: HistData.com (バックテスト用 M1→H1) / MT5 (ライブ用)

---

## 絶対ルール(Codex 実装のレビュー時に必ずチェック)

### 1. ルックアヘッドバイアスの禁止

時刻 t のシグナル判定に、時刻 t 以降の情報を使わない。

- インジケータ: `.shift(1)` でずらしてから判定
- 時間ベース戦略: 東京時間バー → ロンドン時間利用は OK
- NG: `df['signal'] = df['close'] > df['ma']`
- OK: `df['signal'] = df['close'].shift(1) > df['ma'].shift(1)`

**レビュー方法**: Codex 成果物の全シグナル判定行で shift の有無を目視確認。

### 2. コスト未考慮のバックテスト禁止

- スプレッド: USD/JPY=0.3〜1.0, EUR/USD=0.1〜0.5 pips
- スリッページ: 最低 0.5 pips
- スワップ: 日跨ぎ戦略では必須

**レビュー方法**: バックテスト関数の引数に spread/slippage があるか、デフォルト値がゼロでないか。

### 3. データリーク・過剰最適化の禁止

- 訓練/検証/テスト期間を分離
- パラメータ3つ以上の同時最適化は開発者確認

**レビュー方法**: ウォークフォワードの期間分割ロジックに未来データ混入がないか。

### 4. 実弾コードと検証コードの分離

- `backtest/` は絶対に実発注しない
- `live/` は `OANDA_ENV=practice` でガード
- APIキーは `.env` に、コミットしない

---

## ディレクトリ構成

```
fx-bot/
├── CLAUDE.md
├── PLAN.md
├── .env / .env.example / .gitignore / requirements.txt
├── data/                  fetch_oanda.py, load_histdata.py, *.csv
├── strategies/            sma_cross.py, london_breakout.py
├── backtest/              engine.py, run_*.py, validate_london_real.py
├── live/                  oanda_client.py
├── tests/                 pytest テスト
├── configs/               YAML パラメータ
├── results/               出力 (gitignore)
├── notebooks/             Jupyter
└── utils/                 共通ユーティリティ
```

---

## 既存コードの設計判断(Codex への委任時に伝えること)

### strategies/london_breakout.py
- 戻り値: `list[Trade]` (Trade = dataclass)
- 時間ベースのためトレード単位管理
- パラメータ: buffer_pips, risk_reward, tokyo_start/end, london_end, pip_size, spread_pips, slippage_pips
- SL/TP同時ヒット → SL優先(保守的)
- compute_stats() で統計集計

### backtest/engine.py
- ポジション系列ベース(SMAクロス用)。London Breakout は使わない。

### live/oanda_client.py
- allow_live=False デフォルト。pip_size: JPY系=0.01, 他=0.0001

### data/fetch_oanda.py
- 5000本/リクエスト自動分割。Mid/Bid/Ask 全取得。

### backtest/validate_london_real.py
- 5段階検証 + VERDICT (8項目合否)

---

## コーディング規約(Codex への委任時に指示)

- 型ヒント必須
- 戦略は純粋関数
- マジックナンバー禁止
- 実運用コードは loguru
- SettingWithCopyWarning は .copy()
- docstring 必須
- 時刻は UTC 統一

---

## 開発フェーズ

- [x] フェーズ1-4: 基礎〜バックテストの罠
- [ ] **フェーズ4.5: 実データ検証 ← 現在ここ**
- [ ] フェーズ5: デモ運用
- [ ] フェーズ6: 実弾(極小ロット)
