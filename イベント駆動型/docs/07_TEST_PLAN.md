# 07_TEST_PLAN.md

## 1. テスト段階
1. unit test
2. integration test (mocked exchange)
3. replay test (recorded market data)
4. demo/paper test
5. limited live

## 2. 必須ユニットテスト
- basis 計算
- z-score 計算
- position sizing
- fee model
- symbol normalization
- order rounding
- stop/target 判定
- state reconciliation

## 3. 統合テスト
- WS reconnect
- REST fallback
- order ack → fill state transition
- partial fill
- cancel/amend race
- clock skew handling

## 4. リプレイテスト
- 過去の basis extreme 発生局面を JSONL で再生
- signal, decision, order intent が deterministic であることを検証

## 5. ペーパーテスト基準
- 7 日連続稼働
- process restart から復旧可能
- signal 数、採用数、reject 理由が集計可能

## 6. ライブ導入条件
- 連続 2 週間で致命的障害なし
- すべての reject/cancel reason が観測可能
- 実 fee と期待 fee の乖離が許容範囲内

