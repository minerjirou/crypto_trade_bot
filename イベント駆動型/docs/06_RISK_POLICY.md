# 06_RISK_POLICY.md

## 1. 前提
小資金運用のため、最大の敵は「一撃死」ではなく「手数料負け + 連続損失 + API事故」である。

## 2. 基本ルール
- 1トレード最大リスク: 口座残高の 1.0%〜1.5%
- 日次最大損失: 4%
- 最大同時保有数: 2
- 最大レバレッジ: 3x (初期)
- 3 連敗で当日停止

## 3. Kill Switch
以下のいずれかで新規注文を停止する。
- WebSocket 切断継続
- private stream 異常
- 取引所時刻ズレ閾値超過
- 日次最大損失到達
- open order と local state の不整合
- 異常な slippage / fee spike

## 4. 注文ルール
- post-only が拒否される場合は価格を再計算する
- taker 成行は緊急クローズのみ
- 約定しない場合、TTL 超過で再配置または撤退

## 5. ポジションサイズ
- account_equity を起点にリスク固定
- stop_distance から nominal size を逆算
- precision / lot size / min notional に丸める

## 6. 禁止事項
- 10x 以上の初期レバレッジ
- 同時多銘柄乱立
- 板が薄い銘柄への full-size 成行
- funding 時刻直前の無条件新規エントリー

