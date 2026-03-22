# 08_TASK_BREAKDOWN.md

## Phase 0: Skeleton
- [ ] pyproject.toml を作成
- [ ] package layout を作成
- [ ] settings loader を作成
- [ ] structured logger を作成
- [ ] domain models を作成

## Phase 1: Adapters
- [ ] MEXC public REST/WS adapter
- [ ] Bitget public REST/WS adapter
- [ ] instrument metadata fetch
- [ ] ticker/orderbook normalization
- [ ] funding fetch

## Phase 2: Features
- [ ] rolling basis calculator
- [ ] z-score engine
- [ ] volume/OI accelerators
- [ ] listing age registry
- [ ] spread/depth estimator

## Phase 3: Strategy + Risk
- [ ] basis extreme strategy
- [ ] funding filter
- [ ] risk budget manager
- [ ] max daily loss guard
- [ ] concurrent positions cap

## Phase 4: Execution
- [ ] order intent builder
- [ ] post-only price logic
- [ ] split-entry planner
- [ ] amend/cancel logic
- [ ] emergency close logic

## Phase 5: Persistence
- [ ] SQLite schema
- [ ] repositories
- [ ] CSV/parquet export
- [ ] daily report generator

## Phase 6: Modes
- [ ] dry-run CLI
- [ ] paper mode
- [ ] demo exchange mode
- [ ] live mode feature flag

## Phase 7: Extensions
- [ ] Bybit adapter
- [ ] OKX adapter
- [ ] Gate adapter
- [ ] CoinEx adapter
- [ ] DexScreener scanner
- [ ] Hyperliquid adapter

