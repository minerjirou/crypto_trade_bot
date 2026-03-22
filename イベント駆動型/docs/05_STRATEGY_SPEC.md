# 05_STRATEGY_SPEC.md

## 1. 戦略名
Basis Extreme Reversal with Funding Filter

## 2. 戦略の核
- `basis = perp_mid / spot_mid - 1`
- `basis_z = (basis - rolling_mean) / rolling_std`
- 極端な basis の歪みが収束することを狙う
- Funding は主シグナルではなく、悪条件を避けるフィルタとして使う
- 上場後間もないアルト、話題化銘柄、OI/出来高急増銘柄を優先する

## 3. 対象ユニバース
- 現物と perpetual の両方がある銘柄
- 上場後 30 日以上 365 日以下を優先
- 最低 24h 出来高閾値を満たす
- 最大スプレッド閾値以下

## 4. 特徴量
- `basis`
- `basis_z`
- `funding_rate`
- `oi_change_1h`
- `volume_change_1h`
- `listing_age_days`
- `spread_bps`
- `depth_usd_at_5bps`
- `dex_attention_score` (任意)

## 5. スコア関数
```text
score =
  0.35 * abs(basis_z)
+ 0.20 * volume_acceleration
+ 0.15 * oi_acceleration
+ 0.10 * listing_age_bonus
+ 0.10 * funding_alignment
- 0.10 * spread_penalty
```

## 6. エントリー条件
### Long candidate
- `basis_z <= -2.0`
- funding が極端なプラスでない
- spread 許容内
- 24h volume / depth が十分

### Short candidate
- `basis_z >= +2.0`
- funding が極端なマイナスでない
- spread 許容内
- 24h volume / depth が十分

## 7. エグジット条件
- `basis_z` が 0 近辺まで戻る
- 目標 R 到達
- 最大許容損失到達
- 保有時間上限超過
- OI / volume が急減し thesis 崩壊

## 8. 発注方式
- 原則 post-only 指値
- 2〜3 分割
- 緊急クローズのみ taker を許容

## 9. 将来拡張
- DEX signal を事前フィルタに追加
- Listing event calendar を追加
- market regime filter を追加

