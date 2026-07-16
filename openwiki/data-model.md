# Data Layer & Sources

**Source file**: `/scripts/quantrisk/data.py` (~974 lines)

The data layer is organized into **12 layers** (numbered with gaps to allow future insertions). All functions are `async` using `aiohttp` and return consistent dict/list formats.

---

## Layer 1: Quotes (行情层)

Real-time/delayed price data from multiple sources. Each market has a preferred primary source and fallback.

| Market | Primary | Fallback | Fields |
|--------|---------|----------|--------|
| HK | Tencent (`hk_stock_quote_tencent_async`) | Sina (`hk_stock_quote_sina_async`) | 78 fields → **24 extracted** |
| US | Tencent (`us_stock_quote_tencent_async`) | Sina (`us_stock_quote_sina_async`) | 71 fields |
| A-share | Tencent (`cn_stock_quote_tencent_async`) | EastMoney push2 (`cn_stock_quote_eastmoney_async`) | 47 fields |

### HK Quote Financial Fields Expansion

The Tencent HK quote endpoint (`qt.gtimg.cn/q=r_hkXXXXX`) returns 78 raw fields. The function now extracts **10 financial fields** directly from the quote (no separate API call needed):

| Field | Description | Raw Index | Nullable |
|-------|-------------|-----------|----------|
| `pe` | Static PE ratio | f[39] | No |
| `pe_ttm` | PE TTM | f[57] | → 0 if <57 fields |
| `pb` | PB ratio | f[56] | No |
| `dividend_yield` | Dividend yield % | f[31] | → 0 if <31 fields |
| `roe` | ROE % | f[64] | → 0 if <64 fields |
| `profit_margin` | Net profit margin % | f[65] | → 0 if <65 fields |
| `revenue_growth` | Revenue growth % | f[71] | → 0 if <71 fields |
| `gross_margin` | Gross margin % | f[72] | → 0 if <72 fields |
| `debt_ratio` | Debt ratio % | f[74] | → 0 if <74 fields |

*Source: `/scripts/quantrisk/data.py` lines 148-166*

These fields enable **instant fundamental assessment** for any Hong Kong stock from the quote alone, covering bank/insurance stocks where EastMoney's datacenter has no data.

Additional:
- `stock_quote_eastmoney_async()` — Unified EastMoney push2 endpoint (US/HK via secid prefix)
- `cn_stock_basic_info_async()` — A-share basic info (industry, listing date, market cap)

**Key detail**: Tencent API (`qt.gtimg.cn`) is preferred because it does not block IP addresses. Sina requires a `Referer` header.

---

## Layer 2: K-Lines (K线层)

Historical OHLCV data with `{date, open, high, low, close, volume}` format.

| Market | Primary | Fallback |
|--------|---------|----------|
| US | Sina (`us_stock_kline_sina_async`, back to 1984) | TickFlow |
| HK (+ US) | Yahoo (`stock_kline_yahoo_async`, v8 API) | TickFlow |
| A-share | Tencent (`cn_stock_kline_tencent_async`, forward-adjusted) | Baidu / mootdx / TickFlow |

Key functions:
- `stock_kline_yahoo_async(symbol, interval, range_)` — Yahoo Finance v8 chart API, handles any interval (1m to 1mo). Range supports "1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "max". **HK stocks**: auto-strips leading zero from symbol (e.g. `"09999.HK"` → `"9999.HK"`) since Yahoo does not accept leading zeros.
- `hk_kline_tencent_async(code, period, count)` — Tencent fqkline HK daily/weekly K-lines. `code`: 5-digit code, `period`: `day`/`week`, `count`: number of bars. Returns `{date, open, high, low, close, volume}`. **Note**: minute-level (5m/60m) returns only 1 bar per day, unsuitable for Chan Theory.
- `cn_stock_kline_tencent_async(code, days)` — A-share daily K-lines with forward price adjustment, no IP blocking.
- `cn_stock_kline_baidu_async(code, start)` — A-share K-lines with built-in MA5/MA10/MA20 from Baidu.
- `cn_stock_kline_tdx_sync(code)` — A-share multi-period via `mootdx` TCP client (minute/day/week/month).

---

## TickFlow K-Line Backup (Free Tier)

**Functions**: `kline_tickflow_async()`, `kline_tickflow_batch_async()`, `close_tickflow()`, `_get_tickflow()` in `/scripts/quantrisk/data.py` lines 318-445

TickFlow provides **free, no-registration** historical K-line data for all three markets, now implemented as native Python functions in `data.py` (moved from SKILL.md in V1.2.0):

- **Symbol format**: `600000.SH`, `03690.HK`, `AAPL.US`
- **Periods**: 1d, 1w, 1M, 1Q, 1Y (no minute-level in free mode)
- **Adjustment**: forward (default), backward, forward_additive, backward_additive, none
- **Rate limit**: 60 requests/minute (free mode); **batch requests** (`kline_tickflow_batch_async`) count as 1 request
- **Session**: Lazy-initialized singleton via `_get_tickflow()` using `AsyncTickFlow.free().__aenter__()`
- **Cleanup**: `close_tickflow()` releases the TickFlow session; called automatically by `StockAnalyzer.close()`
- **Error handling**: All exceptions are caught and logged via `print()`; returns empty list `[]` on failure
- **Docs**: <https://docs.tickflow.org>

**Batch function** (`kline_tickflow_batch_async`, lines 390-445): Accepts a list of symbols and returns `{symbol: [kline_dict, ...], ...}`. Handles the raw API response format manually (iterating timestamp/open/high/low/close/volume arrays). Returns `{}` on failure.

Used as **active fallback** in all three market analyzers. When primary K-line sources (Yahoo/Tencent/Sina) return fewer than 20 candles, `StockAnalyzer` calls `kline_tickflow_async()` to supplement. See `/scripts/quantrisk/report.py` lines 62-66 (HK), 101-106 (CN), 145-149 (US).

---

## Layer 3: Technical Indicators (技术指标层)

Handled by `/scripts/quantrisk/indicators.py`. Pure Python calculations from K-line data:
- `calc_ma()` — Simple moving averages + EMA12/EMA26
- `calc_macd()` — MACD with DIF, DEA, histogram
- `calc_rsi()` — RSI6, RSI12, RSI24
- `calc_kdj()` — Stochastic oscillator
- `calc_boll()` — Bollinger Bands with bandwidth

---

## Layer 3.5: Chan Theory (缠论层)

Handled by `/scripts/quantrisk/chan.py`. See [Chan Theory Module](chan-theory.md) for full documentation.

---

## Layer 4: Fundamentals (基本面层)

| Market | Primary | Secondary |
|--------|---------|-----------|
| HK + A-share | EastMoney datacenter (`key_indicators_eastmoney_async`) | Yahoo key stats |
| US | Yahoo (`key_statistics_async`) | — |

Key functions:
- `key_indicators_eastmoney_async(secucode, page_size)` — Revenue, profit, ROE, gross margin, debt ratio from EastMoney datacenter
- `hk_fundamentals_async(code)` — **HK unified fundamentals** with 4-tier fallback chain: EastMoney → Tencent 78-field quote (PE_TTM/ROE/gross_margin/debt_ratio/营收增速) → Yahoo key stats → Yahoo financial statements. See `/scripts/quantrisk/data.py` lines 537-630. The Tencent quote fallback (Level 2) is especially important for bank/insurance stocks where EastMoney's datacenter has no data.
- `key_statistics_async(symbol)` — Yahoo key statistics (forward PE, target price, recommendation, institutional ownership)
- `cn_financial_statements_sina_async(code)` — A-share 3 financial statements from Sina
- `cn_eps_forecast_sync(code)` — A-share analyst consensus EPS from 同花顺
- `cn_financial_snapshot_sync(code)` — A-share 37-field financial snapshot via `mootdx`

---

## Layer 5: Capital Flow (资金面层)

A-share (with HK using EastMoney push2 via `batch_hk_capital_flow_async`):
- `cn_fund_flow_minute_async(code)` — Intraday capital flow (main/super-large/large/medium/small orders)
- `fund_flow_daily_async(ticker_or_code, secid_prefix, limit)` — Daily fund flow. Uses **push2** instead of push2his (push2his was IP-rate-limited). Retries up to 3 times with exponential backoff. Returns `{date, main_net, small_net, mid_net, big_net, super_big_net}`.
- `batch_hk_capital_flow_async(codes)` — Parallel HK stock capital flow via `fund_flow_daily_async(secid_prefix=116)`
- `cn_margin_trading_async(code)` — Margin trading (融资融券)
- `cn_block_trade_async(code)` — Block trades (大宗交易)
- `cn_holder_num_change_async(code)` — Shareholder count changes
- `cn_dividend_history_async(code)` — Dividend/distribution history

---

## Layer 6: Signals (信号层 — A-share only)

- `ths_hot_stocks_async()` — 同花顺 hot stocks with theme attribution
- `northbound_flow_async()` — Northbound capital flow (北向资金)
- `cn_concept_blocks_async(code)` — Concept/sector membership
- `cn_dragon_tiger_board_async()` — Dragon-tiger board (龙虎榜, top daily movers)
- `cn_lockup_expiry_async()` — Lockup expiration warnings
- `cn_industry_ranking_async(top_n)` — Sector performance ranking

---

## Layer 7: News & Sentiment (新闻舆情层 — HK/A-share)

Introduced in V1.2.1 for capital-flow-based hot scoring support:

- `jin10_flash_async(count)` — 金十数据 flash news (API may be unreachable; kept as backup)
- `wallstreetcn_flash_async(channel, count)` — 华尔街见闻 flash news; channels: `global-channel` (global/macro), `us-stock-channel`, `a-stock-channel`, `forex-channel`, `goldc-channel`, `oil-channel`
- `stock_news_sentiment_async(code, name)` — Stock news sentiment check (Yahoo search based), returns `{news_count, recent_titles}`
- `batch_hk_capital_flow_async(codes)` — Parallel HK stock capital flow; returns `{code: main_net_inflow (元)}`; uses `fund_flow_daily_async` with EastMoney push2 (secid_prefix=116)

*Source: `/scripts/quantrisk/data.py` lines 924-974*

---

## Layer 8: Announcements (公告层 — A-share only)

- `cninfo_announcements_async(code_or_keyword, page_size)` — Search CNINFO (巨潮) for SSE/SZSE/BSE announcements

---

## Layer 9: Options (期权层 — US only)

- `stock_options_chain_async(ticker)` — Yahoo options chain for US stocks

---

## Layer 10: SEC Filing (SEC层 — US only)

- `sec_filing_async(ticker, count)` — EDGAR submissions list
- `sec_xbrl_async(cik)` — SEC XBRL GAAP data (503 metrics)

---

## Layer 11: Utility (工具层)

- `stock_search(keyword, count)` — EastMoney stock search (US/HK)
- `stock_news(keyword, count)` — Yahoo Finance news
- `ticker_to_cik(ticker)` — SEC CIK lookup
- `market_stock_list(market, sort_field, ...)` — EastMoney push2 market stock list
- `eastmoney_datacenter(report_name, ...)` — Generic EastMoney datacenter query

---

## HTTP Session Infrastructure

```python
# Session management in /scripts/quantrisk/data.py
_async_session: Optional[aiohttp.ClientSession]  # Main session for EastMoney, Tencent, Sina
_yahoo_session: Optional[aiohttp.ClientSession]   # Separate session for Yahoo (crumb auth)
_kline_tickflow_session                           # TickFlow session (lazy init via _get_tickflow())

get_async_session() -> aiohttp.ClientSession
_get(url) -> str               # Simple GET
_get_json(url) -> dict         # GET + JSON decode
_get_gbk(url) -> str           # GET + GBK decode (for Tencent/Sina)
_get_yahoo() -> tuple          # Yahoo session with crumb authentication
_get_tickflow() -> AsyncTickFlow  # TickFlow free session (lazy init)
close_tickflow()               # Close TickFlow session
```

**Parallel execution**: `parallel_map(funcs, max_concurrency=30)` — Wraps functions with a semaphore to limit concurrent requests. Used by batch operations.

---

## Data Format Conventions

**K-line format** (unified across all sources):
```python
[
  {"date": "2024-01-15", "open": 100.0, "high": 102.0, "low": 99.0, "close": 101.5, "volume": 1000000},
  ...
]
```

**Quote format** varies by source but all use Chinese/English mixed field names. The `StockAnalyzer` in `report.py` merges fields from multiple sources with a fallback priority.

---

## A-Share Unique Features

Added in V1.1.0 (2026-07-03). A-share has unique data sources not available for HK/US:

- **Market prefix helper**: `cn_market_prefix(code)` → `sh`/`sz`/`bj` based on code prefix
- **EastMoney secid helper**: `cn_secid(code)` → `1.xxxxxx` or `0.xxxxxx`
- **mootdx TCP client**: A-share specific multi-period K-lines and financial snapshots via `mootdx`

| `us_stock_kline_sina_async` | US | daily | Sina (back to 1984) | — |
| `stock_kline_yahoo_async` | US/HK | **all** (5m/60m/daily) | Yahoo chart v8 | — |
| `kline_tickflow_async` | ALL | daily/weekly/monthly | TickFlow SDK | Yahoo |
| `cn_stock_kline_tencent_async` | A-share | daily/5m/60m | Tencent (adjust, no IP block) | Baidu / mootdx |
| `hk_kline_tencent_async` | **HK** | **daily/weekly** | Tencent fqkline (120 bars) | — |
| `cn_stock_kline_baidu_async` | A-share | daily (with MA) | Baidu | — |

**Yahoo K-line fix (2026-07-09)**:
- Auto-strips leading zeros for HK stocks (`09999.HK` → `9999.HK`), fixes `"result": None` crash
- Supports all Yahoo intervals: `5m`, `15m`, `30m`, `60m`, `1h`, `1d`, `1w`, `1mo`

**Tencent HK K-line** (`hk_kline_tencent_async`, new in 2026-07-09):
- Endpoint: `web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=hk{code},{period},,,{count},qfq`
- Daily: up to 120 bars with full history; Weekly: up to 120 bars (~2.5 years)
- ⚠️ Minute-level (5m/60m): only returns current day's last bar — not usable for Chan Theory

**Multi-source fallback chain** (used by `scripts/chan_mtf.py`):
| Period | 1st | 2nd | 3rd |
|--------|-----|-----|-----|
| 5m | Yahoo | — | — |
| 60m | Yahoo | — | — |
| 日K | TickFlow | Tencent fqkline | Yahoo daily |
| 周K | Tencent fqkline | — | — |

*Source: `/scripts/quantrisk/data.py` functions `stock_kline_yahoo_async`, `kline_tickflow_async`, `hk_kline_tencent_async`*
- **Capital flow (L5)**: Unique margin trading, block trades, shareholder count
- **Signals (L6)**: Dragon-tiger board, northbound flow, lockup expiry — A-share only concepts
- **Announcements (L8)**: CNINFO (巨潮) is China's official listed company announcement platform

## Source References

| File | What to Find |
|------|-------------|
| `/scripts/quantrisk/data.py` lines 1-83 | Session management, parallel_map, Yahoo auth, utility functions |
| `/scripts/quantrisk/data.py` lines 83-166 | L1: Quote functions for all 3 markets (HK Tencent expanded with 10+ new fields) |
| `/scripts/quantrisk/data.py` lines 166-390 | L2: K-line functions for all markets (includes `hk_kline_tencent_async`, Yahoo leading zero fix) |
| `/scripts/quantrisk/data.py` lines 390-530 | TickFlow implementation + `hk_fundamentals_async()` with 4-tier fallback |
| `/scripts/quantrisk/data.py` lines 530-924 | L4-L11: Fundamentals, capital flow (push2 fix), signals, announcements, options, SEC |
| `/scripts/quantrisk/data.py` lines 924-974 | L7: News & sentiment (金十, 华尔街见闻, stock news sentiment, HK capital flow) |
| `/CLAUDE.md` | Data source priority table (lines 29-46) |
| `/CHANGELOG.md` V1.1.0 | A-share data source additions |