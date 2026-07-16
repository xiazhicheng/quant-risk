# Operations Guide

---

## Running Stock Analysis

### CLI Script (HK Stocks)

```bash
# Single stock analysis
uv run scripts/analyze_hk.py 03690

# Batch analysis
uv run scripts/analyze_hk.py 03690 00268 00700

# JSON output (for programmatic consumption)
uv run scripts/analyze_hk.py 03690 --json
```

The script outputs: price, change %, PE, market cap, daily range, turnover, forward PE, analyst target/rating, key financial indicators, technical indicators (MA/MACD/RSI/BOLL), support/resistance levels, stop-loss/take-profit levels, and Chan Theory verdict.

*Source: `/scripts/analyze_hk.py`*

### Python API

```python
from scripts.quantrisk.report import StockAnalyzer
import asyncio

async def main():
    a = StockAnalyzer()

    # HK stock
    result = await a.analyze_hk("03690")
    print(result["name"], result["quote"]["price"])
    print(result["technicals"]["chan"]["chan_verdict"])

    # A-share
    result = await a.analyze_cn("000858")

    # US stock
    result = await a.analyze_us("AAPL")

    # Batch HK
    results = await a.analyze_hk_batch(["03690", "00268", "00700"])

    await a.close()  # Important! Releases HTTP sessions

asyncio.run(main())
```

### Convenience Functions (auto-close sessions)

```python
from scripts.quantrisk.report import analyze_hk, analyze_cn, analyze_us, analyze_hk_batch

result = asyncio.run(analyze_hk("03690"))
```

*Source: `/scripts/quantrisk/report.py` lines 220-253*

---

## HK Stock Recommendation (3-Step Pipeline)

```bash
# Full HK stock recommendation (8 sectors, 114 stocks, 3D scoring → TOP10)
python3 scripts/recommend_hk.py
```

Automated pipeline following SKILL.md's mandatory 3-step workflow:
1. **Step 1**: Cross-sector full-market scan — 8 sectors, 114 representative stocks
2. **Step 2**: Meso hard-constraint filter — market cap≥50B, price≥1HKD, PE≤80, flag net profit decline>50%
3. **Step 3**: Micro 3D scoring — fundamental×5 + hot×3 + chan×2 → ranked TOP10 with stop-loss/target

**Output format**: Full report with:
- Section ①: sector table (sector | count | performance | 量比/资金)
- Section ②: elimination detail table
- Section ③: TOP10 ranking table
- Per-stock breakdown: 3-row score table + detailed analysis paragraphs (基本面分析/热点分析/缠论分析) per stock
- 综合建议: table with columns 标的 | 建议 | 买入点 | 止损点 | 止盈点
- ⚠️ 风险提示 section with data-missing and sector-concentration warnings
- 市场概况 section with overall market statistics

**Session cleanup**: After reporting, the script explicitly calls `close_async_session()` and `close_tickflow()` then `gc.collect()` to release resources.

## Multi-Timeframe Chan Theory Analysis

```bash
# Single stock (5m/60m/日K/周K multi-timeframe Chan theory)
python3 scripts/chan_mtf.py 09999

# Batch comparison
python3 scripts/chan_mtf.py 09999 00700 02269
```

Auto-detects available data sources (Yahoo → TickFlow → Tencent fqkline) and produces:
- 5-minute short-term + 60-minute medium-term + daily long-term + weekly ultra-long
- Multi-period resonance/divergence signals
- Chan Theory verdict, pivot positions, buy/sell points, support/resistance levels

### Data Source Fallback Chain

| Period | Primary | Fallback |
|--------|---------|----------|
| 5m | Yahoo (intraday) | — (only Yahoo has HK minute data) |
| 60m | Yahoo (intraday) | — |
| 日K | TickFlow | Tencent fqkline → Yahoo daily |
| 周K | Tencent fqkline | — |

*Source: `/scripts/chan_mtf.py`*

## Stock Screener: Three-Tier Filtering

Located in `/scripts/quantrisk/screener.py` (~113 lines), used for the stock recommendation workflow:

### Tier 1: Macro Scan — `build_candidate_pool()`

Scans top-performing sectors and collects candidate stocks:
1. Fetches sector performance ranking via `cn_industry_ranking_async()`
2. Selects top N positive sectors
3. For each sector, fetches top stocks via `market_stock_list()`

### Tier 2: Meso Filter — `filter_candidates()`

Hard constraint removal (HK stock defaults):
- Price ≥ 1.0 HKD
- Volume ≥ 10 million shares
(Adjust thresholds for other markets.)

### Tier 3: Micro Scoring — `score_candidate()`

Three-dimensional scoring:
```python
weights = {"hot": 3, "fundamental": 5, "chan": 2}
total = hot_score * 3 + fundamental_score * 5 + chan_score * 2
```
Returns `{hot_score, fundamental_score, chan_score, total_score}`

### Batch Query Helpers

```python
from scripts.quantrisk.screener import batch_hk_quotes, batch_key_indicators, batch_hk_full

quotes = batch_hk_quotes(["03690", "00268"])           # Async batch quotes
indicators = batch_key_indicators(["03690.HK"])         # Async batch fundamentals
full = batch_hk_full(["03690", "00268"])                # Both combined
```

---

## Stock Recommendation Workflow (Mandatory)

Defined in `/SKILL.md` lines 65-181. When a user asks for stock recommendations, the agent **must** execute this exact 3-step pipeline — no skipping steps, no single-sector picks.

### Step 1: Cross-Sector Full Market Scan

Must scan all **8 sectors** with their representative stocks:

| Sector | Representative Stocks |
|--------|---------------------|
| 互联网/IT | 腾讯、阿里、美团、网易、小米、快手、京东、百度、哔哩哔哩、金山软件、京东健康 |
| 金融/保险/券商 | 汇丰、友邦、港交所、工行、中行、建行、招行、平安、人寿、太保、中信银行、中国银河 |
| 能源/资源/矿业 | 中海油、中石油、紫金矿业、洛阳钼业、兖矿能源 |
| 通信/运营商 | 中国移动、中国电信、中国联通 |
| 消费/食品/零售 | 农夫山泉、海底捞、蒙牛、安踏、申洲国际、华润啤酒、恒安国际、青岛啤酒、中国飞鹤 |
| 医药/生物科技 | 百济神州、药明生物、石药集团、中国生物制药、信达生物 |
| 制造/工业/半导体 | 比亚迪、舜宇光学、吉利汽车、中芯国际、华虹宏力、潍柴动力、中国重汽 |
| 公用事业/基建/交运 | 中电控股、电能实业、长江基建、港灯、海丰国际、新奥能源 |

### Step 2: Meso Hard-Constraint Filtering

| Condition | HK Threshold |
|-----------|--------------|
| Min market cap | ≥ 50B HKD |
| Min price | ≥ 1 HKD |
| PE cap | ≤ 80 (loss-making = mark "亏损", don't auto-filter; PE>80 = remove) |
| Net profit deterioration | Mark stocks with net profit YoY decline >50% |

### Step 3: Micro 3D Scoring

Scoring formula (max 50):

```
Total = Fundamental_Score × 5 + Hot_Sector_Score × 3 + Chan_Theory_Score × 2
```

Each dimension scored 1-5. Data sources: `key_indicators_eastmoney_async` for fundamentals, `kline_tickflow_async` for K-lines, `chan.py` for Chan signals.

**Final ranking must be by total score descending — no sector quota allocation.**

### Output Template

The output must follow this exact structure (from `/SKILL.md` lines 115-181):

1. **Section ①** — 全市场扫描（8 板块）: table of sector | count | performance
2. **Section ②** — 中观过滤（剔除明细）: table of eliminated ticker | reason
3. **Section ③** — 三维评分 TOP10: ranked table with columns Rank | Ticker | Sector | Fundamental(×5) | Hot(×3) | Chan(×2) | Total | Suggestion
4. **Per-stock breakdown** (⭐): 3-row table per stock — 基本面/热点/缠论 with scores and evidence
5. **综合建议**: table of ticker | suggestion | entry range | stop loss | target
6. **Disclaimer**: ⚠️ 声明：以上分析仅基于公开市场数据，不构成投资建议。

**Note**: Batch helpers run `asyncio.run()` internally, so they are synchronous callable from non-async code. They are designed for quick interactive use.

---

## Claude Code Skill Integration

**Source**: `/SKILL.md` (106KB — main Skill definition)

The SKILL.md is the Claude Code Skill definition that provides:

1. **Data functions** (originally all ~100 functions, now referencing Python modules since V1.2.0)
2. **Risk control templates** for the four-stage framework
3. **Mandatory 3-step stock recommendation pipeline** (newly enforced in V1.2.0+):
   - **Step 1**: Cross-sector full market scan — all **8 sectors** (互联网/IT, 金融/保险/券商, 能源/资源/矿业, 通信/运营商, 消费/食品/零售, 医药/生物科技, 制造/工业/半导体, 公用事业/基建/交运) must be covered, no skipping
   - **Step 2**: Meso hard-constraint filter — min market cap (50亿 HKD), min price (1 HKD), PE cap (≤80), flag net profit deterioration >50%
   - **Step 3**: Micro 3D scoring → ranked TOP 10 recommendations sorted by total score (not by sector allocation)
4. **Trigger keywords**: 全生命周期风控, 投前, 持仓, 预警, 处置, 缠论, 分型, 笔, 线段, 中枢, 背驰, 一买/二买/三买, 选股, 标的池, etc.

### Strict Output Template

The SKILL.md enforces a strict output template for stock recommendations. The pipeline must scan all 8 sectors, apply all 4 filter rules, and not allocate quota by sector (sort by total score descending).

### Installation as Claude Code Skill

```bash
mkdir -p ~/.claude/skills/quant-risk/scripts
curl -o ~/.claude/skills/quant-risk/SKILL.md \
  https://raw.githubusercontent.com/xiazhicheng/quant-risk/main/SKILL.md
# 同步代码模块
git clone https://github.com/xiazhicheng/quant-risk.git /tmp/_qr && \
cp -r /tmp/_qr/scripts ~/.claude/skills/quant-risk/scripts && \
rm -rf /tmp/_qr
```

---

## Session Lifecycle Management

### HTTP Sessions

The data layer initializes HTTP sessions lazily on first API call:

- `_async_session` — Main session for Tencent/Sina/EastMoney (auto-closes after 20s timeout)
- `_yahoo_session` — Yahoo Finance session with crumb-based auth (auto-closes after 15s timeout)
- `_kline_tickflow_session` — TickFlow session (lazy init via `_get_tickflow()` → `AsyncTickFlow.free().__aenter__()`)

### Cleanup

Always call cleanup to release connections:

```python
# Via StockAnalyzer
a = StockAnalyzer()
try:
    result = await a.analyze_hk("03690")
finally:
    await a.close()

# Via convenience function (auto-cleanup)
result = asyncio.run(analyze_hk("03690"))

# Direct session cleanup
from scripts.quantrisk.data import close_async_session, close_tickflow
await close_async_session()
await close_tickflow()
```

---

## Troubleshooting

### Common Issues

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| Empty quotes | API blocks the request | Try fallback source (Sina for HK, EastMoney for A-share) |
| Yahoo K-lines return empty | Yahoo HK data availability issues | TickFlow fallback activates automatically if <20 candles |
| TickFlow import error | `tickflow` not installed | `uv add tickflow` or `pip install tickflow` |
| mootdx import error | `mootdx` not installed | `uv add mootdx` (A-share only, optional) |
| SSL/Certificate errors | Corporate firewall or proxy | Set `aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False))` |
| `_async_session` already closed | Called after `close()` | Reinitialize by calling `get_async_session()` again ; it creates a new session. |
| Rate limiting | Too many requests in short time | `parallel_map()` uses Semaphore(30) max_concurrency to limit parallelism |

### Data Source Health

- **Tencent** (`qt.gtimg.cn`): Most reliable, no IP blocking. Use as primary for all markets.
- **Sina** (`hq.sinajs.cn`): Requires `Referer: https://finance.sina.com.cn/` header.
- **Yahoo Finance**: HK stock data is often incomplete or missing. Always have TickFlow as fallback.
- **EastMoney push2**: Used for stock lists and A-share capital flow. No auth required.
- **EastMoney datacenter**: Used for fundamentals. Subject to occasional schema changes if EastMoney updates their report names.
- **TickFlow free**: 60 req/min limit. Batch requests reduce quota consumption.

---

## Key Files Reference

| File | Purpose | When to Edit |
|------|---------|-------------|
| `/scripts/quantrisk/data.py` | All data fetching functions | Add new data sources or markets |
| `/scripts/quantrisk/chan.py` | Chan Theory calculations | Tweak thresholds or add new pattern recognition |
| `/scripts/quantrisk/indicators.py` | Technical indicator calculations | Add new indicators or visualization helpers |
| `/scripts/quantrisk/screener.py` | Stock pool filtering + batch queries | Modify screening criteria or add markets |
| `/scripts/quantrisk/report.py` | StockAnalyzer unified analysis (~253 lines) | Add new analysis dimensions or output fields |
| `/scripts/analyze_hk.py` | CLI entrypoint | Add new CLI flags or output formats |
| `/SKILL.md` | Claude Code Skill integration | Update trigger keywords, templates, or screening rules |
| `/CLAUDE.md` | Project conventions for AI agents | Update design decisions or conventions |

---

## Testing & Change Guidance

### Testing Philosophy

The project currently has no formal test suite. Changes should be validated by:
1. Running the CLI script against a known stock: `uv run scripts/analyze_hk.py 03690`
2. Checking that all data layers return expected fields (not empty dicts)
3. Verifying Chan Theory outputs are reasonable for different market conditions (trending vs. ranging markets)
4. Ensuring session cleanup doesn't break subsequent calls

### Change Checklist

When modifying any data function:
- [ ] Does the function return empty dict/list on failure? (All data functions should be safe to call.)
- [ ] Does the function follow the K-line format convention?
- [ ] Is the new function async? (Synchronous functions are only acceptable for mootdx TCP.)
- [ ] Does the new function have a fallback source if the primary fails?
- [ ] Have you updated the import in `report.py` if adding a new analysis dimension?
- [ ] Have you updated `SKILL.md` trigger keywords if adding a new market or data type?

When modifying Chan Theory:
- [ ] Are all functions pure Python (no numpy/pandas)?
- [ ] Have you tested with at least 100 K-lines?
- [ ] Does `chan_risk_assessment()` still return the standard output schema?
- [ ] Have you checked edge cases (insufficient data, flat prices, missing volume)?