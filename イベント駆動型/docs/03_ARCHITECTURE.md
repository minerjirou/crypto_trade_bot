# 03_ARCHITECTURE.md

## 1. 全体構成

```text
collectors -> normalizer -> feature_engine -> signal_ranker -> risk_engine -> order_manager -> exchange_adapters
       \-> recorder / metrics / alerts
```

## 2. モジュール構成
- `core/`: ドメインモデル、イベント、例外、時計、設定
- `adapters/`: 取引所別 REST/WS 実装
- `collectors/`: 市場データ収集と正規化
- `features/`: basis, funding, oi, volume, listing_age
- `strategies/`: basis_extreme_reversal, funding_filter, dex_signal
- `risk/`: sizing, kill-switch, circuit-breaker
- `execution/`: order manager, router, amendment logic
- `storage/`: sqlite repository, export
- `cli/`: backfill, run, replay, report

## 3. 実行サイクル
1. exchange adapter が market data を購読する
2. normalizer が internal event に変換する
3. feature engine が rolling state を更新する
4. strategy が signal candidate を生成する
5. risk engine が採否を決定する
6. order manager が執行計画を作る
7. adapter が order API を送信する
8. recorder が decision から fill まで永続化する

## 4. ドメインモデル
- `Instrument`
- `MarketSnapshot`
- `OrderBookTop`
- `FundingSnapshot`
- `SignalCandidate`
- `ExecutionPlan`
- `OrderIntent`
- `OrderAck`
- `FillEvent`
- `PositionState`
- `PnLSnapshot`

## 5. 状態管理
- rolling 指標はメモリ + 定期 snapshot
- live 復旧のため、position / open orders / last sequence を永続化
- 再起動時は取引所照会 + ローカル state を reconcile

