# crypto-bot-codex-spec-pack

Codex に投入するための仕様書一式です。

## 目的
- 300 USD 規模から開始できる、イベント駆動型の暗号資産ボットを実装する。
- 初期は MEXC / Bitget を主戦場にし、Bybit / OKX / Gate / CoinEx / DexScreener / Hyperliquid を後付け可能な構成にする。
- 常時売買ではなく、先物-現物乖離・Funding フィルタ・上場/話題化イベントを起点に、期待値が高い局面だけを取る。

## パック内容
- `AGENTS.md`: Codex 用の作業指示
- `docs/01_PRD.md`: プロダクト要求仕様
- `docs/02_REQUIREMENTS.md`: 要件定義
- `docs/03_ARCHITECTURE.md`: システム構成
- `docs/04_EXCHANGE_INTEGRATION.md`: 取引所統合仕様
- `docs/05_STRATEGY_SPEC.md`: 戦略仕様
- `docs/06_RISK_POLICY.md`: リスク管理仕様
- `docs/07_TEST_PLAN.md`: テスト計画
- `docs/08_TASK_BREAKDOWN.md`: 実装タスク分解
- `docs/09_CODEX_PROMPTS.md`: Codex に投げるプロンプト集
- `docs/10_SOURCES.md`: 参照元一覧
- `config/.env.example`: 環境変数テンプレート
- `config/settings.example.yaml`: 設定ファイル例

## 開発ポリシー
- Python 3.12 以上
- asyncio ベース
- 取引所の板/注文/約定のリアルタイム処理は原則として各取引所のネイティブ WebSocket を優先する
- `ccxt` は補助用途に限定する
- 手数料は固定値にせず、可能な限り API か設定で外出しする
- 初期フェーズで DEX 実売買はしない。DEX はシグナルソースとしてのみ使う

