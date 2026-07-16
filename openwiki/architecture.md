# Architecture

## Overview

quant-risk implements a **12-layer data source architecture** feeding into three analysis modules, organized around a **four-stage risk control lifecycle**. All data fetching is async I/O via `aiohttp`; all calculations are pure Python (no numpy/pandas).

```
┌─ Pre-investment ─ Position Monitoring ─ Alert Triggering ─ Disposal Decision ─┐
│                                                                                │
│   Data Layer  (data.py)                                                        │
│   ├── L1  Quotes       腾讯/新浪/东财 push2/mootdx                            │
│   ├── L2  K-lines      腾讯/新浪/Yahoo/百度/mootdx/TickFlow                   │
│   ├── L3  Technicals   indicators.py (MA/MACD/RSI/KDJ/BOLL)                    │
│   ├── L3.5 Chan Theory  chan.py (fractals→strokes→segments→pivots→divergence)  │
│   ├── L4  Fundamentals  东财 datacenter/Yahoo/SEC EDGAR/同花顺/mootdx         │
│   ├── L5  Capital Flow  东财 push2/两融/大宗/股东户数/分红                  │
│   ├── L6  Signals       同花顺/龙虎榜/北向资金/板块归属/解禁                  │
│   ├── L7  News & Sentiment 金十数据/华尔街见闻/个股新闻舆情/港股资金流      │
│   ├── L8  Announcements 巨潮 cninfo (A-share only)                             │
│   ├── L9  Options       Yahoo (US stocks only)                                 │
│   ├── L10 SEC Filing    EDGAR (US stocks only)                                 │
│   └── L11 Utility       搜索/新闻/CIK/全市场列表                              │
│                                                                                │
│   Analysis Layer                                                               │
│   ├── Technical Indicators  indicators.py                                      │
│   ├── Chan Theory           chan.py                                            │
│   └── StockAnalyzer         report.py                                          │
└────────────────────────────────────────────────────────────────────────────────┘
```

*Source: `/README.md`, `/CLAUDE.md`*

---

## Module Dependency Graph

```
scripts/analyze_hk.py
    └── scripts.quantrisk.report.StockAnalyzer
            ├── scripts.quantrisk.data          (all data fetching)
            ├── scripts.quantrisk.indicators    (technical indicators)
            └── scripts.quantrisk.chan          (Chan Theory — also re-exported via indicators.py)
```

All modules within `scripts/quantrisk/` are independent leaf modules — `data.py` has no internal dependencies, `chan.py` and `indicators.py` are pure-computation modules, and `report.py` is the only module that imports from multiple others.

---

## Four-Stage Risk Control Framework

| Stage | Trigger | Output |
|-------|---------|--------|
| **Pre-investment** | User asks "Can I buy X?" | Buy/Hold/Watch/Avoid + position size + stop-loss/take-profit preset |
| **Position Monitoring** | User asks "How is my position doing?" | Current P&L, risk level change, rebalance suggestion |
| **Alert** | Price near stop-loss, earnings miss, fundamentals deteriorate | Alert message with specific trigger and recommended action |
| **Disposal** | User asks "What should I do with X?" | Clear / Reduce / Hold / Add with reasoning |

*Source: `/SKILL.md` (risk control templates), `/CLAUDE.md` (conventions)*

---

## Three-Dimensional Scoring

**Formula**: `Total = Fundamentals_Score × 5 + Market_Sentiment_Score × 3 + Chan_Theory_Score × 2`

| Dimension | Weight | Data Sources |
|-----------|--------|-------------|
| Fundamentals (基本面) | ×5 | Revenue growth, net profit growth, ROE, gross margin, debt ratio — from 东财 datacenter / Yahoo |
| Market Sentiment (热点) | ×3 | Sector performance ranking, northbound flow, dragon-tiger board, concept blocks |
| Chan Theory (缠论) | ×2 | MA60 position, MACD histogram direction, divergence signals, pivot zone position |

Max score = 50. Scoring rationale: fundamentals as valuation anchor → technicals for timing → market sentiment as catalyst.

*Source: `/scripts/quantrisk/screener.py` (score_candidate function), `/CLAUDE.md`*

---

## Key Design Decisions

1. **async I/O everywhere**: All HTTP data fetching uses `aiohttp`. Batch operations use `asyncio.gather` with a `Semaphore(30)` for rate limiting. See `/scripts/quantrisk/data.py` `parallel_map()` (line 68) and `StockAnalyzer._gather()` in `/scripts/quantrisk/report.py` (line 27).

2. **Data source fallback chain**: Each data type has a primary source and 1-2 fallbacks. Example: HK stock quotes try Tencent (78 fields) → Sina (25 fields). HK K-lines try Yahoo → TickFlow. If all fail, the function returns an empty dict/list and the caller handles it gracefully. See `/CLAUDE.md` (data source priority table).

3. **No numpy/pandas**: Technical indicators and Chan Theory use only built-in Python data structures (lists, dicts). This keeps the dependency footprint minimal and avoids setup issues on machines without scientific Python stacks. See `/scripts/quantrisk/chan.py` (line 5-6) and `/scripts/quantrisk/indicators.py`.

4. **Optional dependencies**: `tickflow` and `mootdx` are optional. The code handles import failures and missing data gracefully via try/except and fallback checks. See `/scripts/quantrisk/data.py` `kline_tickflow_async()` (line 342) and the mootdx `cn_stock_kline_tdx_sync()`.

5. **Session lifecycle**: HTTP sessions are lazily initialized on first use and cached globally. Callers must call `StockAnalyzer.close()` or the module-level `close_async_session()` / `close_tickflow()` to release resources. See `/scripts/quantrisk/data.py` `get_async_session()` (line 43) and `/scripts/quantrisk/report.py` `StockAnalyzer.close()` (line 213).

6. **V1.2.0 extraction from SKILL.md**: Originally all ~100 data functions lived inside SKILL.md as Claude Code Skill instructions. V1.2.0 extracted them into proper Python modules for direct import. The SKILL.md now references the Python modules instead of containing duplicate code.

7. **TickFlow as active K-line fallback** for all three markets (HK, CN, US). When primary sources (Yahoo/Tencent/Sina) return fewer than 20 K-lines, `StockAnalyzer` calls `kline_tickflow_async()` to supplement. See `/scripts/quantrisk/report.py` lines 62-66 (HK), 101-106 (CN), 145-149 (US). TickFlow uses a lazy-initialized singleton `AsyncTickFlow.free()` session, with explicit cleanup via `close_tickflow()`. The batch version (`kline_tickflow_batch_async`) counts as a single request against the 60/min rate limit.

8. **HK quote expanded with financial fields**: `hk_stock_quote_tencent_async()` extracts 10 fundamental fields (PE_TTM, ROE, profit_margin, revenue_growth, gross_margin, debt_ratio, dividend_yield) directly from the Tencent 78-field quote response. This enables instant fundamental assessment for any HK stock without a separate API call, and covers bank/insurance stocks where EastMoney's datacenter has gaps.

9. **Mandatory recommendation workflow in SKILL.md**: A strict 3-step stock recommendation pipeline is enforced as a prompt-level rule: (1) cross-sector scan of 8 mandatory sectors, (2) meso constraint filtering, (3) micro 3D scoring with ranked TOP10 output. Includes a fixed Markdown output template. See `/SKILL.md` lines 65-181.

---

## Important Conventions for Future Agents

- Always use `uv run` to execute Python, never `pip install` (no `pyproject.toml`).
- Write internal thinking/comments in Chinese (project convention).
- Risk control output must have a clear conclusion: Buy / Hold / Watch / Avoid — no ambiguous non-conclusions.
- For stock recommendations, the scoring pipeline in `/scripts/quantrisk/screener.py` plus SKILL.md's 3-step screening must be followed strictly.
- Add new data source functions with market prefix: `cn_` for A-share, `hk_` for Hong Kong, `us_` for US.
- K-line format convention across all sources: `[{"date", "open", "high", "low", "close", "volume"}, ...]`.