# AGENTS.md

## ミッション
300 USD 規模から開始できる暗号資産取引ボットを実装する。
初期 MVP は MEXC / Bitget 対応、戦略は「新しめアルトの先物-現物乖離 extreme 逆張り + Funding フィルタ + イベント駆動」である。

## 最重要制約
1. 収益保証を前提にしない。
2. 小資金を前提に、手数料とスリッページを最重要コストとして扱う。
3. 常時高頻度売買はしない。条件成立時のみ発火する event-driven bot とする。
4. 新規実装は adapter / strategy / risk / storage の分離を守る。
5. 各取引所の API 仕様はハードコードで決め打ちしない。列挙・設定・ feature flag で吸収する。
6. すべての外部 API 呼び出しには timeout / retry / rate-limit 保護を入れる。
7. private key / API secret をコードに埋め込まない。
8. まず dry-run と paper mode を完成させ、本番自動売買は最後に有効化する。

## 成果物の優先順位
1. ディレクトリ構成と設定読み込み
2. 共通ドメインモデル
3. MEXC adapter
4. Bitget adapter
5. Basis extreme strategy
6. Risk engine
7. Order manager
8. Recorder / SQLite
9. Dry-run CLI
10. Backtest / replay

## コーディング規約
- Python 3.12+
- 型ヒント必須
- ruff / black / mypy 前提
- 例外は握りつぶさない
- ログは JSON 構造化
- UTC 基準で記録
- monetary value は Decimal で扱う
- pandas は研究・分析のみに使用し、実運用 path では多用しない

## 実装時の注意
- maker / taker を strategy と execution の両方で明示する
- reduce-only / post-only / time-in-force を注文要求に含める
- 発注 API の ACK と実約定を分離して扱う
- WebSocket 切断時の cancel-all / kill-switch を実装する
- fee model は exchange × market type × symbol zone 単位で差し替え可能にする

