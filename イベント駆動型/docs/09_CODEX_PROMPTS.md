# 09_CODEX_PROMPTS.md

## Prompt 1: 初期骨組み
以下の仕様書群を読み、Python 3.12 用のプロジェクト骨組みを作成してください。
要件:
- asyncio ベース
- ruff / black / mypy 設定込み
- `src/` レイアウト
- `core`, `adapters`, `features`, `strategies`, `risk`, `execution`, `storage`, `cli` の各 package を作る
- domain model は dataclass または pydantic で型付けする
- SQLite 接続層を用意する
- `python -m bot.cli.main --help` で起動確認できるようにする

## Prompt 2: MEXC + Bitget 市場データ
MEXC と Bitget の public market data adapter を実装してください。
要件:
- ticker と orderbook top を取得する
- internal symbol へ正規化する
- reconnect / backoff / ping/pong を実装する
- raw payload を debug log に残せるようにする
- 例外時でもプロセス全体は落ちないようにする

## Prompt 3: Basis engine
市場データから basis と rolling z-score を算出する feature engine を実装してください。
要件:
- spot / perp の mid price から basis を計算
- rolling mean/std は window configurable
- warmup 期間中は signal を出さない
- pytest を用意する

## Prompt 4: Strategy + Risk
basis extreme reversal strategy を実装してください。
要件:
- abs(z) 閾値
- spread 上限
- listing age フィルタ
- funding filter
- position cap
- daily max loss guard
- 返り値は OrderIntent ではなく SignalCandidate にする

## Prompt 5: Order manager
SignalCandidate を受け取り、post-only を優先する発注計画を組み立てる OrderManager を実装してください。
要件:
- 2〜3 分割エントリー
- round lot / min notional 対応
- reduce-only クローズ
- TTL 超過時再配置
- dry-run 実装を先に作る

## Prompt 6: Recorder と report
signal / order / fill / pnl を SQLite に記録し、日次レポートを出力する仕組みを実装してください。
要件:
- schema migration を簡易実装
- CSV export
- 日次の勝率、平均 R、fee 合計、reject reason 集計を出力

