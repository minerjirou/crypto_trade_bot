# 04_EXCHANGE_INTEGRATION.md

## 1. 対応方針
初期 MVP は MEXC / Bitget を必須対応とする。
Bybit / OKX / Gate / CoinEx / Hyperliquid / DexScreener は interface 準拠の plugin として追加可能にする。

## 2. 共通インターフェース

```python
class ExchangeAdapter(Protocol):
    async def connect_public(self) -> None: ...
    async def connect_private(self) -> None: ...
    async def subscribe_ticker(self, symbols: list[str]) -> None: ...
    async def subscribe_orderbook(self, symbols: list[str]) -> None: ...
    async def fetch_instruments(self) -> list[Instrument]: ...
    async def fetch_fee_rates(self, symbols: list[str]) -> dict[str, FeeRate]: ...
    async def place_order(self, intent: OrderIntent) -> OrderAck: ...
    async def amend_order(self, req: AmendRequest) -> OrderAck: ...
    async def cancel_order(self, req: CancelRequest) -> CancelAck: ...
    async def fetch_open_orders(self) -> list[OrderState]: ...
    async def fetch_positions(self) -> list[PositionState]: ...
```

## 3. Exchange Capability Matrix

| Exchange | Spot | Perp | Demo/Test | Fee API | WS Order | 初期優先度 |
|---|---:|---:|---:|---:|---:|---:|
| MEXC | Yes | Yes | 部分的 | 限定的/設定併用 | あり | 最高 |
| Bitget | Yes | Yes | Demo あり | 設定併用 | あり | 最高 |
| Bybit | Yes | Yes | Demo あり | あり | あり | 高 |
| OKX | Yes | Yes | Demo あり | あり | あり | 高 |
| Gate | Yes | Yes | Testnet あり | あり | あり | 中 |
| CoinEx | Yes | Yes | 不明確/限定 | 設定中心 | あり | 中 |
| Hyperliquid | Spot/Perp | Yes | Testnet 推奨 | あり | onchain | 中 |
| DexScreener | 監視のみ | No | N/A | N/A | N/A | 高 |

## 4. 実装ルール
- symbol 正規化関数を adapter ごとに持つ
- price / size precision を instrument metadata から取り込む
- fee model は exchange + market_type + symbol_zone で解決する
- adapter は raw payload を log/debug に残せるようにする

## 5. 手数料方針
- OKX, Gate は API から fee snapshot を取得する
- MEXC は zone/region/announcement 変動があるため、設定上書きを必須にする
- Bitget/CoinEx は初期設定値を持ち、定期的に設定更新できる構造にする
- 実 fill ごとの fee が取得できる場合は、その値を source of truth とする

