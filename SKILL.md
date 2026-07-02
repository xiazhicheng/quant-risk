---
name: quant-risk
description: 【全生命周期风控】美股港股数据+风控分析 — 覆盖投前审查/持仓监控/预警/处置四阶段。基于行情、K线、基本面、资金面、期权、SEC等八层数据源，输出风险等级、风控结论、建议仓位上限、预警阈值、止损止盈条件。适用于事前审查、持续监控、警报触发、处置决策。
origin: custom
version: 1.0.0
---
> 📦 https://github.com/xiazhicheng/quant-risk — Star ⭐ 是最好的支持
# 美股港股全栈数据工具包 V1.0.0（全异步）

八层数据架构，全部异步并行获取，零鉴权。

```
行情层（实时/延时）
├── 新浪财经     → 美股 gb_XXXX 36字段 / 港股 rt_hkXXXXX 25字段
├── 腾讯财经     → 美股 usXXXX 71字段 / 港股 r_hkXXXXX 78字段
└── 东财 push2   → 美股/港股 secid 实时行情

K线层（日/周/月/分钟）
├── 新浪          → 美股日K (回溯至1984年)
└── Yahoo chart   → 美股+港股 (v8 API)

技术指标层：MA/EMA + MACD + RSI + KDJ + 布林带（纯Python）

基本面层
├── 东财 datacenter → 三表+GMAININDICATOR关键指标(中文)
├── Yahoo           → 估值/分析师/机构持仓(英文)
└── SEC EDGAR XBRL  → 美股503个GAAP指标

资金面层：东财 push2his 日级资金流(主力/大单/中单/小单)
期权层：Yahoo 期权链（仅美股）
SEC Filing层：EDGAR submissions + XBRL（仅美股）
工具层：东财搜索 / Yahoo新闻 / SEC CIK / 全市场列表
```

## When to Activate

- 用户要**全生命周期风控**（投前/持仓/预警/处置）
- 用户要**投前审查**（能不能买/仓位上限/止损止盈预设）
- 用户要**持仓监控**（当前盈亏/风险变化/是否需调仓）
- 用户要**预警触发**（价格接近止损/业绩暴雷/基本面恶化）
- 用户要**处置建议**（清仓/减仓/持有/加仓）
- 用户要查**美股/港股**行情/财报/指标/资金流/期权/SEC/搜索/全市场排名
- 关键词：全生命周期风控、投前、持仓、预警、处置、风控审查、风险等级、仓位上限、买入、持有、观望、回避、止损、止盈、PE、PB、ROE、美股、港股、财报、技术分析

---

## Prerequisites

```bash
pip install aiohttp
```

| 依赖 | 版本要求 | 用途 |
|------|---------|------|
| aiohttp | any | 所有 HTTP API 直连（全异步）|

## 核心原则

- **数据全部用 aiohttp 异步拉取**，批量查多只股票时并行，避免串行等待
- 用 `asyncio.run(batch_func())` 同步入口调用
- 零鉴权、零登录、零 cookie、零 crumb、零 token（Yahoo crumb 自动获取）
- **不需要 requests**，全 aiohttp

---

## 共用基础设施

```python
import asyncio, aiohttp, re, json
from datetime import datetime

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"

# ── 全局 aiohttp session ──────────────────────────
_async_session = None

async def get_async_session() -> aiohttp.ClientSession:
    global _async_session
    if _async_session is None or _async_session.closed:
        _async_session = aiohttp.ClientSession(
            headers={"User-Agent": UA},
            timeout=aiohttp.ClientTimeout(total=20),
        )
    return _async_session

async def close_async_session():
    global _async_session
    if _async_session and not _async_session.closed:
        await _async_session.close()

async def _aio_get(url: str, **kwargs) -> str:
    s = await get_async_session()
    async with s.get(url, **kwargs) as resp:
        return await resp.text()

async def _aio_get_json(url: str, **kwargs) -> dict:
    """GET JSON，兼容 text/plain 等非标准 content-type"""
    s = await get_async_session()
    async with s.get(url, **kwargs) as resp:
        text = await resp.text()
        return json.loads(text) if text.strip() else {}

async def _aio_get_gbk(url: str, **kwargs) -> str:
    """GET GBK 编码页面（新浪/腾讯接口用）"""
    s = await get_async_session()
    async with s.get(url, **kwargs) as resp:
        raw = await resp.read()
    return raw.decode("gbk")

# ── 并行执行器 ──────────────────────────
async def parallel_map(funcs: list, max_concurrency: int = 30) -> list:
    sem = asyncio.Semaphore(max_concurrency)
    async def _run(f):
        async with sem:
            return await f()
    return await asyncio.gather(*[_run(f) for f in funcs], return_exceptions=True)

# ── Yahoo crumb ──────────────────────────
_yahoo_crumb = None
_yahoo_session = None

async def _get_yahoo() -> 'tuple[aiohttp.ClientSession, str]':
    global _yahoo_session, _yahoo_crumb
    if _yahoo_session is None or _yahoo_session.closed:
        _yahoo_session = aiohttp.ClientSession(
            headers={"User-Agent": UA},
            timeout=aiohttp.ClientTimeout(total=15),
        )
        await _yahoo_session.get("https://fc.yahoo.com")
        async with _yahoo_session.get("https://query2.finance.yahoo.com/v1/test/getcrumb") as r:
            _yahoo_crumb = await r.text()
    return _yahoo_session, _yahoo_crumb

async def yahoo_quote_summary_async(symbol: str, modules: list[str]) -> dict:
    s, crumb = await _get_yahoo()
    url = f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{symbol}"
    async with s.get(url, params={"modules": ",".join(modules), "crumb": crumb}) as resp:
        results = (await resp.json()).get("quoteSummary", {}).get("result", [{}])
    return results[0] if results else {}
```

---

## Layer 1: 行情层（全部异步）

### 1.1 腾讯港股行情 — 78字段（主推）

```python
async def hk_stock_quote_tencent_async(code: str) -> dict:
    """港股行情：00700, 09988 等 5 位数字代码"""
    text = await _aio_get_gbk(f"https://qt.gtimg.cn/q=r_hk{code}")
    m = re.search(r'"(.+)"', text)
    if not m:
        return {}
    fields = m.group(1).split("~")
    if len(fields) < 50:
        return {}
    def sf(v):
        try: return float(v) if v and v != "-" else 0.0
        except: return 0.0
    return {
        "name": fields[1], "price": sf(fields[3]),
        "change_pct": sf(fields[32]), "pe": sf(fields[39]),
        "pb": sf(fields[56]), "market_cap_100m": sf(fields[44]),
        "high": sf(fields[33]), "low": sf(fields[34]),
        "volume_shares": int(sf(fields[6])),
        "amount_100m": sf(fields[37]),
        "high_52w": sf(fields[35]), "low_52w": sf(fields[36]),
        "timestamp": fields[30] if len(fields) > 30 else "",
    }
```

### 1.2 腾讯美股行情

```python
async def us_stock_quote_tencent_async(ticker: str) -> dict:
    """美股行情：AAPL, TSLA 等"""
    text = await _aio_get_gbk(f"https://qt.gtimg.cn/q=us{ticker.upper()}")
    m = re.search(r'"(.+)"', text)
    if not m:
        return {}
    fields = m.group(1).split("~")
    if len(fields) < 50:
        return {}
    def sf(v):
        try: return float(v) if v and v != "-" else 0.0
        except: return 0.0
    return {
        "name": fields[1], "price": sf(fields[3]),
        "change_pct": sf(fields[32]), "pe": sf(fields[53]),
        "pb": sf(fields[56]), "market_cap": sf(fields[44]),
        "high": sf(fields[33]), "low": sf(fields[34]),
        "volume": int(sf(fields[6])),
        "high_52w": sf(fields[35]), "low_52w": sf(fields[36]),
    }
```

### 1.3 新浪美股行情

```python
async def us_stock_quote_sina_async(ticker: str) -> dict:
    """新浪美股36字段"""
    text = await _aio_get_gbk(f"https://hq.sinajs.cn/list=gb_{ticker.lower()}",
                               headers={"Referer": "https://finance.sina.com.cn/"})
    m = re.search(r'"(.+)"', text)
    if not m:
        return {}
    fields = m.group(1).split(",")
    if len(fields) < 30:
        return {}
    return {
        "name": fields[0], "price": float(fields[1]),
        "change_pct": float(fields[2]),
        "open": float(fields[5]) if fields[5] else 0,
        "high": float(fields[6]) if fields[6] else 0,
        "low": float(fields[7]) if fields[7] else 0,
        "volume": float(fields[10]) if fields[10] else 0,
        "high_52w": float(fields[8]) if fields[8] else 0,
        "low_52w": float(fields[9]) if fields[9] else 0,
        "market_cap": float(fields[12]) if fields[12] else 0,
        "eps": float(fields[13]) if fields[13] else 0,
        "pe": float(fields[14]) if fields[14] else 0,
    }
```

### 1.4 新浪港股行情

```python
async def hk_stock_quote_sina_async(code: str) -> dict:
    """新浪港股25字段"""
    text = await _aio_get_gbk(f"https://hq.sinajs.cn/list=rt_hk{code}",
                               headers={"Referer": "https://finance.sina.com.cn/"})
    m = re.search(r'"(.+)"', text)
    if not m:
        return {}
    fields = m.group(1).split(",")
    return {
        "name": fields[1], "open": float(fields[2]) if fields[2] else 0,
        "prev_close": float(fields[3]) if fields[3] else 0,
        "high": float(fields[4]) if fields[4] else 0,
        "low": float(fields[5]) if fields[5] else 0,
        "price": float(fields[6]) if fields[6] else 0,
        "change_pct": float(fields[8]) if fields[8] else 0,
        "volume": float(fields[12]) if fields[12] else 0,
    }
```

### 1.5 东财 push2 统一行情

```python
async def stock_quote_eastmoney_async(ticker_or_code: str, secid_prefix: int = 105) -> dict:
    """push2 实时行情，统一接口。secid_prefix: 105=NASDAQ, 106=NYSE, 116=港股"""
    d = (await _aio_get_json("https://push2.eastmoney.com/api/qt/stock/get", params={
        "secid": f"{secid_prefix}.{ticker_or_code}",
        "fields": "f43,f44,f45,f46,f47,f48,f55,f57,f58,f59,f60,f170",
    })).get("data")
    if not d:
        return {}
    dec = d.get("f59", 3)
    divisor = 10 ** dec
    def _p(key):
        v = d.get(key)
        return round(v / divisor, dec) if v is not None and v != "-" else None
    return {
        "code": d.get("f57"), "name": d.get("f58"),
        "price": _p("f43"), "high": _p("f44"), "low": _p("f45"),
        "open": _p("f46"), "volume": d.get("f47"), "amount": d.get("f48"),
        "turnover_rate": d.get("f55"), "prev_close": _p("f60"),
        "change_pct": round(d["f170"] / 100, 2) if d.get("f170") is not None else None,
    }
```

---

## Layer 2: K线层

### 2.1 美股日K — 新浪

```python
async def us_stock_kline_sina_async(ticker: str, num: int = 120) -> list[dict]:
    """新浪美股日K，可回溯至1984年"""
    text = await _aio_get(
        "https://stock.finance.sina.com.cn/usstock/api/jsonp.php/var/US_MinKService.getDailyK",
        params={"symbol": ticker.upper(), "num": num},
        headers={"Referer": "https://finance.sina.com.cn/"},
    )
    m = re.search(r'\((\[.+\])\)', text)
    if not m:
        return []
    items = json.loads(m.group(1))
    return [{"date": i.get("d"), "open": float(i.get("o", 0)),
             "high": float(i.get("h", 0)), "low": float(i.get("l", 0)),
             "close": float(i.get("c", 0)), "volume": int(i.get("v", 0))}
            for i in items]
```

### 2.2 Yahoo K线（美股+港股通用）

```python
async def stock_kline_yahoo_async(symbol: str, interval: str = "1d", range_: str = "6mo") -> list[dict]:
    """Yahoo chart API，零crumb。symbol: "AAPL" 或 "0700.HK" """
    d = await _aio_get_json(f"https://query2.finance.yahoo.com/v8/finance/chart/{symbol}",
                             params={"interval": interval, "range": range_})
    chart = d.get("chart", {}).get("result", [{}])[0]
    timestamps = chart.get("timestamp", [])
    quote = chart.get("indicators", {}).get("quote", [{}])[0]
    result = []
    for i, ts in enumerate(timestamps):
        is_subday = "m" in interval or "h" in interval
        result.append({
            "date": datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M" if is_subday else "%Y-%m-%d"),
            "open": round(quote["open"][i], 2) if quote["open"][i] else 0,
            "high": round(quote["high"][i], 2) if quote["high"][i] else 0,
            "low": round(quote["low"][i], 2) if quote["low"][i] else 0,
            "close": round(quote["close"][i], 2) if quote["close"][i] else 0,
            "volume": int(quote["volume"][i]) if quote["volume"][i] else 0,
        })
    return result
```

---

## Layer 3: 技术指标层（纯计算，与同步/异步无关）

```python
def _ema(values: list[float], period: int) -> list[float]:
    result = [values[0]]
    k = 2 / (period + 1)
    for v in values[1:]:
        result.append(v * k + result[-1] * (1 - k))
    return result

def calc_ma(klines: list[dict], periods: list[int] = None) -> list[dict]:
    if periods is None:
        periods = [5, 10, 20, 60]
    closes = [k["close"] for k in klines]
    ema12, ema26 = _ema(closes, 12), _ema(closes, 26)
    result = []
    for i, k in enumerate(klines):
        row = {"date": k["date"], "close": k["close"]}
        for p in periods:
            row[f"ma{p}"] = round(sum(closes[i-p+1:i+1]) / p, 4) if i >= p-1 else None
        row["ema12"], row["ema26"] = round(ema12[i], 4), round(ema26[i], 4)
        result.append(row)
    return result

def calc_macd(klines: list[dict], fast: int = 12, slow: int = 26, signal: int = 9) -> list[dict]:
    closes = [k["close"] for k in klines]
    dif = [round(f - s, 4) for f, s in zip(_ema(closes, fast), _ema(closes, slow))]
    dea = _ema(dif, signal)
    return [{"date": k["date"], "close": k["close"],
             "dif": round(dif[i], 4), "dea": round(dea[i], 4),
             "macd_hist": round((dif[i] - dea[i]) * 2, 4)}
            for i, k in enumerate(klines)]

def calc_rsi(klines: list[dict], periods: list[int] = None) -> list[dict]:
    if periods is None:
        periods = [6, 12, 24]
    closes = [k["close"] for k in klines]
    changes = [0.0] + [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains, losses = [max(c, 0) for c in changes], [max(-c, 0) for c in changes]
    result = []
    for i, k in enumerate(klines):
        row = {"date": k["date"], "close": k["close"]}
        for p in periods:
            if i < p:
                row[f"rsi{p}"] = None; continue
            ag, al = sum(gains[i-p+1:i+1])/p, sum(losses[i-p+1:i+1])/p
            row[f"rsi{p}"] = 100.0 if al == 0 else round(100 - 100/(1+ag/al), 2)
        result.append(row)
    return result

def calc_kdj(klines: list[dict], n: int = 9, m1: int = 3, m2: int = 3) -> list[dict]:
    k_val, d_val = 50.0, 50.0
    result = []
    for i, kline in enumerate(klines):
        if i < n - 1:
            result.append({"date": kline["date"], "close": kline["close"],
                           "k": None, "d": None, "j": None}); continue
        w = klines[i-n+1:i+1]
        hn, ln = max(i["high"] for i in w), min(i["low"] for i in w)
        rsv = (kline["close"]-ln)/(hn-ln)*100 if hn != ln else 50.0
        k_val, d_val = (1/m1)*rsv + (1-1/m1)*k_val, (1/m2)*k_val + (1-1/m2)*d_val
        result.append({"date": kline["date"], "close": kline["close"],
                       "k": round(k_val, 2), "d": round(d_val, 2), "j": round(3*k_val-2*d_val, 2)})
    return result

def calc_boll(klines: list[dict], period: int = 20, num_std: float = 2.0) -> list[dict]:
    closes = [k["close"] for k in klines]
    result = []
    for i, k in enumerate(klines):
        if i < period - 1:
            result.append({"date": k["date"], "close": k["close"],
                           "upper": None, "middle": None, "lower": None, "bandwidth": None})
            continue
        w = closes[i-period+1:i+1]
        ma, std = sum(w)/period, (sum((x-sum(w)/period)**2 for x in w)/period)**0.5
        up, lo = ma+num_std*std, ma-num_std*std
        result.append({"date": k["date"], "close": k["close"],
                       "upper": round(up, 4), "middle": round(ma, 4), "lower": round(lo, 4),
                       "bandwidth": round((up-lo)/ma*100, 2) if ma else None})
    return result
```

---

## Layer 4: 基本面层（全部异步）

### 4.1 东财数据中心 — 通用查询

```python
async def eastmoney_datacenter_async(report_name: str, columns: str = "ALL",
                                      filter_str: str = "", page_size: int = 50,
                                      sort_columns: str = "", sort_types: str = "-1") -> list[dict]:
    d = await _aio_get_json(DATACENTER_URL, params={
        "reportName": report_name, "columns": columns,
        "filter": filter_str, "pageNumber": "1", "pageSize": str(page_size),
        "sortColumns": sort_columns, "sortTypes": sort_types,
        "source": "WEB", "client": "WEB",
    })
    return d.get("result", {}).get("data", []) if d.get("result") else []
```

### 4.2 关键财务指标（中文）— GMAININDICATOR

```python
async def key_indicators_eastmoney_async(secucode: str, page_size: int = 4) -> list[dict]:
    market = "hk" if secucode.endswith(".HK") else "us"
    return await eastmoney_datacenter_async(
        f"RPT_{'HK' if market == 'hk' else 'US'}F10_FN_GMAININDICATOR",
        filter_str=f'(SECUCODE="{secucode}")', page_size=page_size,
        sort_columns="REPORT_DATE", sort_types="-1",
    )
```

### 4.3 财报三表（中文）

```python
async def financial_statements_eastmoney_async(secucode: str, statement: str = "balance", page_size: int = 200) -> list[dict]:
    rmap = {"balance": {"us": "RPT_USF10_FN_BALANCE", "hk": "RPT_HKF10_FN_BALANCE"},
            "income": {"us": "RPT_USF10_FN_INCOME", "hk": "RPT_HKF10_FN_INCOME"},
            "cashflow": {"us": "RPT_USSK_FN_CASHFLOW", "hk": "RPT_HKSK_FN_CASHFLOW"}}
    market = "hk" if secucode.endswith(".HK") else "us"
    return await eastmoney_datacenter_async(rmap[statement][market],
        filter_str=f'(SECUCODE="{secucode}")', page_size=page_size,
        sort_columns="REPORT_DATE", sort_types="-1")
```

### 4.4 Yahoo 关键指标（英文）

```python
async def key_statistics_async(symbol: str) -> dict:
    data = await yahoo_quote_summary_async(symbol, ["financialData", "defaultKeyStatistics", "summaryDetail"])
    fd, ks, sd = data.get("financialData", {}), data.get("defaultKeyStatistics", {}), data.get("summaryDetail", {})
    def _v(d, k):
        v = d.get(k, {}); return v.get("raw") if isinstance(v, dict) else v
    return {
        "current_price": _v(fd, "currentPrice"),
        "target_mean": _v(fd, "targetMeanPrice"),
        "recommendation": fd.get("recommendationKey"),
        "trailing_pe": _v(sd, "trailingPE"), "forward_pe": _v(ks, "forwardPE"),
        "peg_ratio": _v(ks, "pegRatio"), "price_to_book": _v(ks, "priceToBook"),
        "enterprise_value": _v(ks, "enterpriseValue"),
        "profit_margin": _v(ks, "profitMargins"),
        "return_on_equity": _v(fd, "returnOnEquity"),
        "return_on_assets": _v(fd, "returnOnAssets"),
        "earnings_growth": _v(fd, "earningsGrowth"),
        "revenue_growth": _v(fd, "revenueGrowth"),
        "beta": _v(ks, "beta"),
        "dividend_yield": _v(sd, "dividendYield"),
        "market_cap": _v(sd, "marketCap"),
        "total_revenue": _v(fd, "totalRevenue"),
        "total_cash": _v(fd, "totalCash"), "total_debt": _v(fd, "totalDebt"),
    }
```

### 4.5 分析师预期

```python
async def analyst_estimates_async(symbol: str) -> dict:
    data = await yahoo_quote_summary_async(symbol, ["earningsTrend", "recommendationTrend", "upgradeDowngradeHistory"])
    return {
        "eps_trend": [{"period": t.get("period"), "end_date": t.get("endDate"),
                        "eps_estimate": t.get("earningsEstimate", {}).get("avg", {}).get("raw"),
                        "revenue_estimate": t.get("revenueEstimate", {}).get("avg", {}).get("raw"),
                        "num_analysts": t.get("earningsEstimate", {}).get("numberOfAnalysts", {}).get("raw")}
                       for t in data.get("earningsTrend", {}).get("trend", [])],
        "rating_trend": data.get("recommendationTrend", {}).get("trend", []),
    }
```

### 4.6 机构持仓

```python
async def institutional_holders_async(symbol: str) -> dict:
    data = await yahoo_quote_summary_async(symbol, ["institutionOwnership", "majorHoldersBreakdown"])
    mhb = data.get("majorHoldersBreakdown", {})
    def _v(d, k):
        v = d.get(k, {}); return v.get("raw") if isinstance(v, dict) else v
    overview = {"insiders_pct": _v(mhb, "insidersPercentHeld"),
                "institutions_pct": _v(mhb, "institutionsPercentHeld"),
                "institutions_float_pct": _v(mhb, "institutionsFloatPercentHeld"),
                "institutions_count": _v(mhb, "institutionsCount")}
    holders = [{"name": h.get("organization"), "shares": _v(h, "position"),
                "value": _v(h, "value"), "pct_held": _v(h, "pctHeld")}
               for h in data.get("institutionOwnership", {}).get("ownershipList", [])[:10]]
    return {"overview": overview, "top_holders": holders}
```

### 4.7 Yahoo 年度/季度财报

```python
async def financial_statements_yahoo_async(symbol: str, quarterly: bool = False) -> dict:
    sfx = "Quarterly" if quarterly else ""
    data = await yahoo_quote_summary_async(symbol, [f"incomeStatementHistory{sfx}", f"balanceSheetHistory{sfx}", f"cashflowStatementHistory{sfx}"])
    def _ext(key):
        stmts = data.get(key, {}).get("incomeStatementHistory" if "income" in key else "balanceSheetStatements" if "balance" in key else "cashflowStatements", [])
        return [{k: v["raw"] if isinstance(v, dict) and "raw" in v else v for k, v in stmt.items()} for stmt in stmts]
    return {"income": _ext(f"incomeStatementHistory{sfx}"),
            "balance": _ext(f"balanceSheetHistory{sfx}"),
            "cashflow": _ext(f"cashflowStatementHistory{sfx}")}
```

---

## Layer 5: 资金面层

```python
async def fund_flow_daily_async(ticker_or_code: str, secid_prefix: int = 105, limit: int = 100) -> list[dict]:
    d = (await _aio_get_json("https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get", params={
        "secid": f"{secid_prefix}.{ticker_or_code}", "klt": 101,
        "fields1": "f1,f2,f3,f7", "fields2": "f51,f52,f53,f54,f55,f56,f57", "lmt": limit,
    })).get("data")
    if not d or not d.get("klines"):
        return []
    result = []
    for line in d["klines"]:
        p = line.split(",")
        result.append({"date": p[0], "main_net": float(p[1]), "small_net": float(p[2]),
                       "mid_net": float(p[3]), "big_net": float(p[4]),
                       "super_big_net": float(p[5]),
                       "main_pct": float(p[6]) if len(p) > 6 and p[6] else 0})
    return result
```

---

## Layer 6: 期权层（仅美股）

```python
async def options_chain_async(symbol: str, expiration: int = None) -> dict:
    """Yahoo 期权链。港股(0700.HK)期权不在覆盖范围"""
    s, crumb = await _get_yahoo()
    params = {"crumb": crumb}
    if expiration: params["date"] = expiration
    async with s.get(f"https://query2.finance.yahoo.com/v7/finance/options/{symbol}", params=params) as resp:
        oc = (await resp.json()).get("optionChain", {}).get("result", [{}])[0]
    opts = oc.get("options", [{}])[0] if oc.get("options") else {}
    def _po(os):
        def _v(k):
            v = o.get(k, {}); return v.get("raw") if isinstance(v, dict) else v
        return [{"strike": _v("strike"), "last_price": _v("lastPrice"), "bid": _v("bid"),
                 "ask": _v("ask"), "volume": _v("volume"), "open_interest": _v("openInterest"),
                 "implied_volatility": _v("impliedVolatility"),
                 "in_the_money": o.get("inTheMoney")} for o in os]
    return {"expiration_dates": oc.get("expirationDates", []),
            "calls": _po(opts.get("calls", [])), "puts": _po(opts.get("puts", [])),
            "underlying_price": oc.get("quote", {}).get("regularMarketPrice")}
```

---

## Layer 7: SEC Filing 层（仅美股）

```python
async def sec_filings_async(cik: str, form_type: str = None) -> dict:
    from aiohttp import ClientSession
    async with ClientSession(headers={"User-Agent": "global-stock-data/2.0"}) as sess:
        async with sess.get(f"https://data.sec.gov/submissions/CIK{cik}.json") as resp:
            data = await resp.json()
    recent = data.get("filings", {}).get("recent", {})
    filings = []
    for i in range(len(recent.get("form", []))):
        if form_type and recent["form"][i] != form_type: continue
        filings.append({"form": recent["form"][i], "date": recent["filingDate"][i],
                        "accession_number": recent["accessionNumber"][i],
                        "primary_document": recent["primaryDocument"][i] if i < len(recent.get("primaryDocument", [])) else ""})
    return {"company_name": data.get("name"), "cik": cik, "filings": filings[:50]}

async def sec_xbrl_facts_async(cik: str, metrics: list[str] = None) -> dict:
    from aiohttp import ClientSession
    async with ClientSession(headers={"User-Agent": "global-stock-data/2.0"}) as sess:
        async with sess.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json") as resp:
            facts = await resp.json()
    us_gaap = facts.get("facts", {}).get("us-gaap", {})
    if not metrics:
        return {"company": facts.get("entityName"), "total_metrics": len(us_gaap),
                "available_metrics": [{"name": k, "label": v.get("label"), "units": list(v.get("units", {}).keys())} for k, v in us_gaap.items()]}
    result = {}
    for mn in metrics:
        m = us_gaap.get(mn, {})
        if not m: result[mn] = []; continue
        unit_key = "USD" if "USD" in m.get("units", {}) else (list(m["units"].keys())[0] if m.get("units") else None)
        if not unit_key: result[mn] = []; continue
        result[mn] = [{"end": e.get("end"), "val": e.get("val"), "form": e.get("form"),
                        "filed": e.get("filed"), "fy": e.get("fy")}
                       for e in m["units"][unit_key] if e.get("form") in ("10-K", "10-Q")][-20:]
    return {"company": facts.get("entityName"), "metrics": result}
```

---

## Layer 8: 工具层

```python
async def stock_search_async(keyword: str, count: int = 10) -> list[dict]:
    """东财股票搜索 — 中英文通用"""
    d = await _aio_get_json("https://searchapi.eastmoney.com/api/suggest/get", params={
        "input": keyword, "type": 14, "token": "D43BF722C8E33BDC906FB84D85E326E8", "count": count,
    })
    suggestions = d.get("QuotationCodeTable", {}).get("Data", [])
    mkt_map = {"105": "NASDAQ", "106": "NYSE", "107": "US_OTHER", "116": "HK"}
    return [{"code": s.get("Code"), "name": s.get("Name"),
             "mkt_num": int(m.get("MktNum")), "market": mkt_map.get(m.get("MktNum"), "")}
            for s in suggestions if (m := s) and str(s.get("MktNum", "")) in mkt_map]

async def stock_news_async(keyword: str, count: int = 10) -> list[dict]:
    """Yahoo 新闻"""
    s, _ = await _get_yahoo()
    async with s.get("https://query2.finance.yahoo.com/v1/finance/search",
                      params={"q": keyword, "quotesCount": 0, "newsCount": count}) as resp:
        news = (await resp.json()).get("news", [])
    return [{"title": n.get("title"), "publisher": n.get("publisher"),
             "link": n.get("link"), "publish_time": n.get("providerPublishTime")} for n in news]

async def ticker_to_cik_async(ticker: str) -> dict:
    """SEC ticker → CIK"""
    d = await _aio_get_json("https://www.sec.gov/files/company_tickers.json",
                             headers={"User-Agent": "global-stock-data/2.0"})
    for _, v in d.items():
        if v.get("ticker") == ticker.upper():
            return {"ticker": ticker.upper(), "cik": str(v["cik_str"]).zfill(10), "company": v.get("title")}
    return {}

async def market_stock_list_async(market: str = "hk", sort_field: str = "f3",
                                    sort_desc: bool = True, page: int = 1, page_size: int = 20) -> dict:
    """全市场股票列表。market: 'hk', 'us_nasdaq', 'us_nyse'"""
    mkt_map = {"us_nasdaq": "m:105", "us_nyse": "m:106", "us_etf": "m:107", "hk": "m:116"}
    d = await _aio_get_json("https://push2.eastmoney.com/api/qt/clist/get", params={
        "fs": mkt_map.get(market, market), "fields": "f2,f3,f4,f5,f6,f7,f12,f14,f15,f16,f17,f18",
        "pn": page, "pz": page_size, "fid": sort_field, "po": 1 if sort_desc else 0,
    })
    data = d.get("data", {})
    total = data.get("total", 0)
    diff = data.get("diff", [])
    if isinstance(diff, dict): diff = list(diff.values())
    stocks = [{"code": i.get("f12"), "name": i.get("f14"),
               "price": i.get("f2"), "change_pct": round(i["f3"]/100, 2) if i.get("f3") is not None else None,
               "volume": i.get("f5"), "amount": i.get("f6"),
               "high": i.get("f15"), "low": i.get("f16")} for i in diff]
    return {"total": total, "stocks": stocks}
```

---

## 批量并行查询（一键调用）

```python
def batch_hk_quotes(codes: list[str]) -> dict[str, dict]:
    """并行获取多只港股行情"""
    async def _batch():
        funcs = [lambda c=code: hk_stock_quote_tencent_async(c) for code in codes]
        results = await parallel_map(funcs)
        out = {}
        for r in results:
            if isinstance(r, dict) and r.get("name"):
                out[r["name"]] = r
        return out
    return asyncio.run(_batch())

def batch_key_indicators(secucodes: list[str]) -> dict[str, dict]:
    """并行获取多只股票基本面"""
    async def _batch():
        funcs = [lambda s=sc: key_indicators_eastmoney_async(s) for sc in secucodes]
        results = await parallel_map(funcs)
        return {sc: data[0] if isinstance(data, list) and data else {}
                for sc, data in zip(secucodes, results)}
    return asyncio.run(_batch())

def batch_hk_full(codes: list[str]) -> dict:
    """并行获取港股行情+基本面"""
    secucodes = [f"{c}.HK" for c in codes]
    async def _batch():
        qf = [lambda c=code: hk_stock_quote_tencent_async(c) for code in codes]
        indf = [lambda s=sc: key_indicators_eastmoney_async(s) for sc in secucodes]
        quotes, indicators = await asyncio.gather(parallel_map(qf), parallel_map(indf))
        result = {}
        for i, code in enumerate(codes):
            q = quotes[i] if isinstance(quotes[i], dict) else {}
            ind = indicators[i][0] if isinstance(indicators[i], list) and indicators[i] else {}
            result[code] = {"quotes": q, "indicators": ind}
        return result
    return asyncio.run(_batch())
```

---

## 数据源优先级

| 场景 | 第一优先 | 备选 |
|------|---------|------|
| 港股行情 | 腾讯 r_hkXXXXX（78字段） | 新浪/东财 push2 |
| 美股行情 | 新浪 gb_XXXX（36字段） | 腾讯/东财 push2 |
| 美股K线 | 新浪 | Yahoo chart |
| 港股K线 | Yahoo chart | — |
| 关键指标(中文) | 东财 GMAININDICATOR | — |
| 关键指标(英文) | Yahoo quoteSummary | — |
| 财报三表(中文) | 东财 datacenter | — |
| 分析师/机构 | Yahoo quoteSummary | — |
| 资金流 | 东财 push2his | — |
| 期权链(仅美股) | Yahoo options | — |
| SEC Filing | EDGAR | — |
| 搜索 | 东财 search | Yahoo search |
| 全市场列表 | 东财 push2 clist | — |

---

## 辅助分析函数（纯计算，基于已有数据）

```python
def calc_support_resistance(klines: list[dict], lookback: int = 60) -> dict:
    """
    从 K 线数据计算支撑位和压力位。
    支撑位 = 最近 lookback 个交易日中最低价的 EMA(5)
    压力位 = 最近 lookback 个交易日中最高价的 EMA(5)
    """
    if not klines or len(klines) < 10:
        return {"support": None, "resistance": None}
    window = klines[-min(lookback, len(klines)):]
    lows = [k["low"] for k in window]
    highs = [k["high"] for k in window]
    def _ema(vals, period=5):
        k = 2 / (period + 1)
        r = [vals[0]]
        for v in vals[1:]:
            r.append(v * k + r[-1] * (1 - k))
        return r
    s_ema = _ema(lows, 5)
    r_ema = _ema(highs, 5)
    return {"support": round(s_ema[-1], 2), "resistance": round(r_ema[-1], 2),
            "current_support": round(lows[-1], 2), "current_resistance": round(highs[-1], 2)}

def calc_stop_loss_take_profit(entry_price: float, atr: float = None, klines: list[dict] = None) -> dict:
    """
    止损/止盈触发条件。
    如果提供了 ATR，按 ATR 倍数计算；否则按最近 N 日最低/最高计算。
    """
    if atr is None and klines and len(klines) > 14:
        # 计算 ATR(14)
        closes, highs, lows = [k["close"] for k in klines], [k["high"] for k in klines], [k["low"] for k in klines]
        tr = []
        for i in range(1, min(15, len(klines))):
            tr.append(max(highs[-i] - lows[-i], abs(highs[-i] - closes[-i-1]), abs(lows[-i] - closes[-i-1])))
        atr = sum(tr) / len(tr)
    
    if atr:
        return {
            "stop_loss": round(entry_price - 2 * atr, 2),
            "stop_loss_trigger": f"收盘价跌破 {round(entry_price - 2 * atr, 2)}（-{round(2 * atr / entry_price * 100, 1)}%）",
            "take_profit": round(entry_price + 3 * atr, 2),
            "take_profit_trigger": f"收盘价突破 {round(entry_price + 3 * atr, 2)}（+{round(3 * atr / entry_price * 100, 1)}%）",
            "atr": round(atr, 2),
        }
    return {"stop_loss": None, "take_profit": None}

def calc_turnover_amount(quote: dict, price: float = None) -> dict:
    """从行情数据提取成交额和估算换手率"""
    volume = quote.get("volume_shares") or quote.get("volume") or 0
    amount = quote.get("amount_100m") or 0
    turnover = quote.get("turnover_rate")  # push2 有换手率
    return {"volume_shares": int(volume), "amount_100m": round(amount / 1e8, 2) if amount > 1e8 else round(amount, 2),
            "turnover_rate": turnover}
```

---

## 全生命周期风控框架

风控分 4 个阶段，每个阶段的输出有不同的侧重点：

```
投前 (Pre-trade)  →  持仓 (Holding)  →  预警 (Alert)  →  处置 (Disposal)
 审查能否入场        持续监控风险        警报触发            决策退出/调整
```

每次调用时先识别当前阶段，然后使用对应模板。

---

## 输出模板

**每个阶段必须有明确的结论清单**，不得模棱两可。

### 阶段 1：投前审查（Pre-trade）

适用于：还没买，审查是否值得入场。

```markdown
## 投前风控审查 | {股票中文名}（{code}）— {date}

### 基本信息

| 指标 | 值 |
|------|----|
| 现价/涨跌幅 | {price} / {change_pct}% |
| PE/市值 | {pe} / {mcap}亿 |
| 成交额/换手率 | {amount} / {turnover}% |
| 行业 | {industry} |
| 支撑/压力 | {support} / {resistance} |

### 基本面评分

| 维度 | 评分(1-5) | 得分依据 |
|------|----------|---------|
| 行业景气度 | {1-5} | {行业上行/平稳/下行 + 政策环境利好/中性/利空} |
| 竞争格局 | {1-5} | {龙头/分散/激烈 + 产业链议价力} |
| 盈利质量 | {1-5} | 毛利率 {x}% / 净利率 {x}% / ROE {x}% |
| 财务健康 | {1-5} | 资产负债率 {x}% / 流动比率 {x} |
| 成长性 | {1-5} | 营收同比 {x}% / 行业增速对比 |

**综合风险等级**: {低/中/较高/高}

### 预设风控参数

| 参数 | 值 |
|------|----|
| 建议仓位上限 | {比例} |
| 止损触发价 | {price}（-{x}%，跌破则离场）|
| 止盈触发价（一档） | {price}（+{x}%，减半仓）|
| 止盈触发价（二档） | {price}（+{x}%，清仓）|
| 持仓周期建议 | {短期/中期/长期} |
| 最大容忍回撤 | {x}% |

### 审查结论

| 维度 | 结论 |
|------|------|
| 风控结论 | **{买入 / 观望 / 拒绝}** |
| 核心理由 | {支撑判断的关键事实} |
| 必须回避的条件 | {如果……则不入场} |
```

---

### 阶段 2：持仓监控（Holding）

适用于：已持有，检查风险变化，判断是否需要调整。

```markdown
## 持仓风控检查 | {股票中文名}（{code}）— {date}

### 当前持仓

| 指标 | 值 |
|------|----|
| 持仓成本 | {cost_price} |
| 当前价格 | {current_price} |
| 浮动盈亏 | {profit_loss}（{pct}%）|
| 当前仓位占比 | {position_pct} |
| 风控允许上限 | {max_limit} |
| 持仓天数 | {days} |

### 风险变化追踪

| 检查项 | 上次 | 本次 | 变化方向 |
|--------|------|------|---------|
| PE | {old_pe} | {new_pe} | {恶化/改善/持平} |
| 价格距止损位 | {old_dist}% | {new_dist}% | {逼近/远离} |
| 成交额趋势 | {old_amt} | {new_amt} | {缩量/放量} |
| 行业景气度 | {old_outlook} | {new_outlook} | {转好/转差} |

### 离场条件检查

| 条件 | 状态 | 操作 |
|------|------|------|
| 未触发止损 | {安全 / 逼近 / 已触发} | 跌破 {price} 必须离场 |
| 未触发止盈 | {未到 / 接近 / 已触发} | 突破 {price} 考虑分批止盈 |
| 盈利保护线 | {盈利 / 保本 / 亏损} | 盈利回吐超 {x}% 需减仓 |
| 基本面预警 | {正常 / 关注 / 恶化} | {具体预警内容} |

### 操作建议

| 选项 | 建议 |
|------|------|
| 继续持有 | {理由} |
| 减仓至 | {建议仓位}%（原为 {x}%）|
| 增持至 | {建议仓位}%（如适用）|
| 清仓离场 | {触发条件} |

**结论**: {持有/减仓/增持/清仓}

**下一步观察点**: {具体要盯的关键变量}
```

---

### 阶段 3：预警触发（Alert）

适用于：价格触及预设线、基本面突发变化、需要紧急判断。

```markdown
## ⚠ 风控预警 | {股票中文名}（{code}）— {date}

### 触发条件

{价格触及止损线 / 价格触及止盈线 / 业绩暴雷 / 行业政策突变 / 其他}

### 触发详情

| 指标 | 值 |
|------|----|
| 当前价格 | {price}（较入场 {change}%）|
| 触发条件值 | {trigger_value} |
| 预设风控线 | {threshold} |
| 偏离幅度 | {deviation} |
| 时间 | {time} |

### 紧急基本面检查

| 检查项 | 状态 |
|--------|------|
| 最新财报日期 | {date} |
| 近期是否有未预期利空 | {是/否}（{描述}）|
| 行业是否有系统性风险 | {是/否} |
| 成交量是否异常 | {放量/缩量/正常}（较日均 {ratio}）|

### 处置建议

| 选项 | 是否建议 | 理由 |
|------|---------|------|
| 执行止损 | {是/否} | {理由} |
| 部分减仓 | {是/否} | {减至 x%} |
| 继续持有观察 | {是/否} | {观察期 x 天} |
| 反向加仓 | {是/否} | {仅限判断为错杀时} |

**结论**: {立即止损 / 减仓观望 / 持有观察 / 加仓}

**执行优先级**: {高/中/低} — 建议 {立即 / 本日 / 本周} 执行
```

---

### 阶段 4：处置决策（Disposal）

适用于：决定退出后，如何执行（一次性清仓/分批/转仓）。

```markdown
## 处置方案 | {股票中文名}（{code}）— {date}

### 处置原因

{止损触发 / 止盈达标 / 基本面恶化 / 策略调整 / 资金需求 / 其他}

### 当前状态

| 指标 | 值 |
|------|----|
| 持仓量 | {shares} 股 |
| 持仓成本 | {cost} |
| 现价 | {price} |
| 浮动盈亏 | {total_profit}（{pct}%）|
| 仓位占比 | {position_pct} |
| 板块配置占比 | {sector_pct} |

### 处置方案对比

| 方案 | 操作 | 预估影响 | 建议 |
|------|------|---------|------|
| A: 一次性清仓 | 全部市价卖出 | 兑现 {profit_loss}，释放 {capital} 资金 | {是否推荐} |
| B: 分批退出 | 分 {n} 批，每批间隔 {days} 天 | 降低冲击成本，但承担期间波动 | {是否推荐} |
| C: 减仓不空仓 | 保留 {x}% 底仓 | 保留反弹仓位，降低整体敞口 | {是否推荐} |
| D: 转仓 | 卖出本股，换入 {target} | 维持板块配置，调整个股 | {是否推荐} |

### 执行计划

- **方式**: {市价 / 限价 / 条件单}
- **时限**: {立即 / 本日 / 本周 / 两周内}
- **分批明细**: {如有，列出每批的时间和数量}

### 赎回资金再配置建议

{如有，给出资金释放后的配置方向}

### 经验记录

{本轮交易的经验教训，供后续参考}
```

---

### 通用风控判断规则

| 风控结论 | 投前条件 | 持仓条件 |
|---------|---------|---------|
| **买入/继续持有** | ① 低风险或中等风险 ② 盈利为正 ③ 营收正增长或稳定 ④ PE 合理（< 30 或行业均值附近） | ① 距止损线 > 5% ② 基本面无恶化 ③ 无预警信号 |
| **观望/减仓** | ① 较高风险 ② 或盈利为负但营收高增长 ③ 或估值偏高但行业前景好 | ① 距止损线 < 5% ② 盈利回吐 > 50% ③ 基本面预警 |
| **拒绝/清仓** | ① 高风险 ② 或亏损严重且无改善 ③ 或营收大幅下滑 ④ 或负债率过高(>70%) | ① 触发止损 ② 业绩暴雷 ③ 行业系统性风险 |

仓位上限参考：低风险 ≤ 15% / 中等风险 ≤ 10% / 较高风险 ≤ 5% / 高风险 ≤ 2%

### 输出规范

1. **日期**：在标题标注分析日期
2. **涨跌幅**：正数前加 `+`，负数直接显示
3. **亏损公司 PE**：`{负值}(亏损)`
4. **不分析未上市公司**：提示 "未上市" 并跳过
5. **所有指标来源于 SKILL API，不允许编造字段值**
6. **每个阶段必须有清晰结论**：投前 → 买入/观望/拒绝；持仓 → 持有/减仓/清仓；预警 → 立即执行/观察；处置 → 具体方案
7. **预警和处置阶段需要标明执行优先级和时限**
