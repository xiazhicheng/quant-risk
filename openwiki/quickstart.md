# Quant-Risk Quickstart

**quant-risk** is a full-lifecycle quantitative risk control toolkit covering **US stocks, A-shares, and Hong Kong stocks**. It implements a four-stage risk control framework with a three-dimensional scoring system.

- **Source**: <https://github.com/xiazhicheng/quant-risk>
- **Version**: 1.2.1+ (2026-07-13, with TickFlow K-line fallback for all 3 markets, HK financial fields, recommendation templates, capital-flow-based hot scoring, Layer 7 news)
- **License**: Apache 2.0

---

## What It Does

| Phase | Purpose |
|-------|---------|
| **Pre-investment Review** | Evaluate whether a stock is worth buying, suggested position size, stop-loss/take-profit preset |
| **Position Monitoring** | Track current P&L, risk changes, rebalancing signals |
| **Alert Triggering** | Price approaching stop-loss, earnings surprise, fundamental deterioration |
| **Disposal Decision** | Clear / reduce / hold / add positions |

**Three-dimensional scoring** (max 50 points):

| Dimension | Weight | Score Range | Core Question |
|-----------|--------|-------------|---------------|
| Fundamentals | ×5 | 1-5 | Is valuation reasonable? Profit quality? Financial health? |
| Market Sentiment (热点) | ×3 | 1-5 | Is it in the market's main theme? Any catalysts? |
| Chan Theory Timing (缠论) | ×2 | 1-5 | Structural position? Buy/sell signals? |

---

## Quick Start

```bash
uv run scripts/analyze_hk.py 03690              # Analyze Meituan (single)
uv run scripts/analyze_hk.py 03690 00268 00700   # Batch analyze multiple HK stocks
uv run scripts/analyze_hk.py 03690 --json        # JSON output mode
python3 scripts/recommend_hk.py                  # Full HK stock recommendation (114 stocks, TOP10)
python3 scripts/chan_mtf.py 09999                # Multi-timeframe Chan Theory analysis
python3 scripts/chan_mtf.py 09999 00700 02269    # Batch multi-timeframe comparison
```

**Requirements**: Python 3.10+, `uv` package manager, and install dependencies:

```bash
uv add aiohttp  # Required for async HTTP data fetching
# Optional: pip install tickflow mootdx
```

---

## Repository Structure

```
quant-risk/
├── scripts/                     # All code unified here
│   ├── quantrisk/               # Python package (importable via scripts.quantrisk.*)
│   │   ├── __init__.py
│   │   ├── data.py              # Data layer: quotes, K-lines, fundamentals, capital flow, signals, news, options, SEC, TickFlow
│   │   ├── chan.py              # Chan Theory: 分型→笔→线段→中枢→背驰→买卖点
│   │   ├── indicators.py        # Technical indicators: MA/MACD/RSI/KDJ/BOLL + Chan re-export
│   │   ├── screener.py          # Stock pool filtering + batch queries
│   │   └── report.py            # StockAnalyzer unified analysis entry
│   ├── formatter.py             # Selection report formatter (Pydantic + rendering)
│   ├── formatters/              # 4-stage risk formatters
│   └── *.py                     # Entry scripts: analyze_hk.py, recommend_hk.py, portfolio.py, chan_mtf.py
├── SKILL.md                     # Skill definition
├── AGENTS.md                    # Project conventions
└── README.md                    # Project overview
```
│   ├── chan.py                  # Chan Theory: fractals→strokes→segments→pivots→divergence→buy/sell points (~553 lines)
│   ├── indicators.py            # Technical indicators: MA/MACD/RSI/KDJ/BOLL + support/resistance + Chan re-exports (~316 lines)
│   ├── screener.py              # Three-tier candidate pool filtering + batch queries (~113 lines)
│   └── report.py                # StockAnalyzer — one-click full analysis entrypoint (~253 lines)
├── scripts/
│   ├── analyze_hk.py            # Runnable entry script for HK stock analysis
│   ├── recommend_hk.py          # Full HK stock recommendation (114 stocks, 3-step pipeline)
│   └── chan_mtf.py              # Multi-timeframe Chan Theory (5m/60m/日K/周K)
├── SKILL.md                     # Claude Code Skill definition (data functions + risk control templates)
├── CLAUDE.md                    # Project conventions and design decisions (for AI coding agents)
├── AGENTS.md                    # Agent instructions for Codex
├── CHANGELOG.md                 # Version history
└── README.md                    # Project overview (this file)
```

---

## Key Design Decisions

- **async I/O**: All data fetching uses `aiohttp` for parallel, non-blocking requests. Batch operations use `asyncio.gather` with a semaphore-limited pool.
- **No pip install required**: Run with `uv run` directly. No `pyproject.toml`, no `egg-info`.
- **Pure Python calculations**: Technical indicators and Chan Theory use only built-in Python — no numpy/pandas dependency.
- **Data source fallback**: Multiple source priorities per data type/market. For example, HK stock K-lines try Yahoo first, then TickFlow free tier as active fallback (if primary returns <20 candles).
- **TickFlow free tier**: Free, no-registration K-line data service used as active fallback for all three markets. Supports forward/backward price adjustment. Fully implemented as native Python functions in `data.py`.
- **HK fundamentals with 4-tier fallback**: New `hk_fundamentals_async()` chains EastMoney → Tencent 78-field quote → Yahoo key stats → Yahoo financial statements for maximum data coverage.
- **HK quote expanded financial fields**: Tencent's 78-field HK quote now returns 10 financial fields directly (PE_TTM, ROE, profit_margin, revenue_growth, gross_margin, debt_ratio, dividend_yield) — no separate API call needed for fundamental ratios.
- **Mandatory 3-step recommendation workflow**: SKILL.md enforces a strict stock recommendation pipeline: (1) cross-sector full-market scan of 8 mandatory sectors, (2) meso constraint filtering (market cap ≥50B HKD, price ≥1 HKD, PE ≤80), (3) micro 3D scoring with ranked TOP10 output. Includes a fixed output template (sector scan → filter detail → score rankings → per-stock breakdown → combined suggestions). See `SKILL.md` lines 65-181.
- **Code extracted from SKILL.md**: V1.2.0 moved all data functions (~100 functions) from SKILL.md text into proper Python modules.

---

## Documentation Pages

| Page | Covers |
|------|--------|
| [Architecture](architecture.md) | 11-layer data architecture, four-stage risk control, module data flow, key design decisions |
| [Data Layer & Sources](data-model.md) | All 11 data layers, source fallback priorities per market, TickFlow, A-share unique features |
| [Chan Theory Module](chan-theory.md) | Chan Theory pipeline, parameters, risk assessment integration, pure-Python design |
| [Operations Guide](operations.md) | CLI scripts, Python API, batch analysis, stock screener, Claude Code Skill integration, troubleshooting |

---

## When to Use This Project

For an AI coding agent, this project is useful when the user asks about:

- Full lifecycle risk control (投前/持仓/预警/处置)
- Pre-investment review (能不能买/仓位上限/止损止盈)
- Position monitoring (当前盈亏/风险变化/是否需调仓)
- Alert triggering (价格接近止损/业绩暴雷/基本面恶化)
- Disposal advice (清仓/减仓/持有/加仓)
- Any US/HK/A-share stock data queries (quotes, financials, capital flow, dragon-tiger board, northbound flow, announcements)
- Stock screening and scoring
- Chan Theory (缠论) technical analysisl analysis