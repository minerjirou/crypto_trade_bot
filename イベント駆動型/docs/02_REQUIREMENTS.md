# 02_REQUIREMENTS.md

## Functional Requirements

### FR-1 市場データ収集
- 現物 ticker / 板 / 先物 ticker / funding / instrument metadata を取得する。
- MEXC / Bitget を必須、Bybit / OKX / Gate / CoinEx / Hyperliquid / DexScreener を任意プラグインとする。
- 取引所の symbol naming 差異を internal symbol registry で吸収する。

### FR-2 シグナル生成
- basis = perp_mid / spot_mid - 1 を計算する。
- rolling mean / std から z-score を算出する。
- volume acceleration / OI acceleration / listing age / funding alignment / spread penalty を算出する。
- スコア上位候補のみを返す。

### FR-3 エントリー制御
- `abs(basis_z) >= threshold` のときだけ候補化する。
- 上場後日数フィルタ、最低流動性フィルタ、最大スプレッドフィルタを適用する。
- 同時保有数上限と日次損失上限を満たす場合のみ発注する。

### FR-4 注文管理
- post-only 指値を優先する。
- 2〜3 分割エントリーをサポートする。
- reduce-only クローズをサポートする。
- 未約定注文の TTL 管理を行う。
- kill-switch による全注文取消をサポートする。

### FR-5 リスク管理
- 日次最大損失率、1トレード最大損失率、最大同時保有数を設定可能にする。
- 連敗数制限、API 異常時新規停止、WS 切断時保護を実装する。

### FR-6 記録・監査
- signal, decision, order, amend, cancel, fill, position snapshot, fee snapshot を保存する。
- SQLite への保存を MVP 必須とする。
- CSV / parquet エクスポートを任意でサポートする。

### FR-7 実行モード
- research mode
- dry-run mode
- paper mode
- live mode

## Non-Functional Requirements
- 単一ホスト (Windows + Python) で動作可能
- 1 台で複数取引所の WS を同時処理可能
- 障害時にプロセス再起動で状態を再構築可能
- 設定ファイルのみで exchange/strategy/risk を切り替え可能
- ログと DB をもとに完全な事後分析が可能

