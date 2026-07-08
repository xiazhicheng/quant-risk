---
name: quant-risk
description: 【全生命周期风控+标的池筛选】美股+港股+A股数据+风控分析 — 三层标的池筛选（宏观全市场扫描→中观硬约束过滤→微观三维评分），覆盖投前审查/持仓监控/预警/处置四阶段。集成缠论（Chan Theory）分型/笔/线段/中枢/背驰/买卖点。基于行情、K线、基本面、资金面、期权、SEC等数据源，输出风险等级、风控结论、建议仓位上限、预警阈值、止损止盈条件。
origin: custom
version: 1.2.0
---
> 📦 https://github.com/xiazhicheng/quant-risk — Star ⭐ 是最好的支持
# 美股+A股+港股全栈数据工具包 V1.2.0（全异步）

十一层数据架构，全部异步并行获取，零鉴权。

```
行情层（实时/延时）
├── 腾讯财经     → A股 sh/sz 47字段 / 美股 usXXXX 71字段 / 港股 r_hkXXXXX 78字段
├── 新浪财经     → 美股 gb_XXXX 36字段 / 港股 rt_hkXXXXX 25字段
├── 东财 push2   → A股 secid:0-1 / 美股 secid:105-107 / 港股 secid:116
└── mootdx (TCP) → A股五档盘口+逐笔成交

K线层（日/周/月/分钟）
├── 腾讯          → A股日K前复权(带MA5/10/20)
├── 新浪          → 美股日K (回溯至1984年)
├── Yahoo chart   → 美股+港股 (v8 API)
├── 百度          → A股日K(带MA)
└── mootdx        → A股多周期(分钟/日/周/月)

技术指标层：MA/EMA + MACD + RSI + KDJ + 布林带（纯Python）

缠论层：分型 → 包含处理 → 笔 → 线段 → 中枢 → 背驰 → 买卖点（纯Python）

基本面层
├── 东财 datacenter → 三表+GMAININDICATOR关键指标(中/英/港)
├── mootdx finance  → A股季报37字段
├── 新浪            → A股三表(资产负债/利润/现金流)
├── 同花顺          → A股机构一致预期EPS
├── Yahoo           → 估值/分析师/机构持仓(英文)
└── SEC EDGAR XBRL  → 美股503个GAAP指标

资金面层
├── 东财 push2his → 日级资金流(主力/大单/中单/小单)
└── 东财 datacenter → A股融资融券/大宗交易/股东户数/分红

信号层（A股独有）
├── 同花顺  → 强势股+题材归因+北向资金
├── 东财    → 龙虎榜+解禁+行业排名+板块归属
└── 百度    → 概念板块

公告层（A股独有）：巨潮 cninfo 沪深北全量公告
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
- 用户要查**美股/港股/A股**行情/财报/指标/资金流/龙虎榜/北向/公告/调研
- 关键词：全生命周期风控、投前、持仓、预警、处置、风控审查、风险等级、仓位上限、买入、持有、观望、回避、止损、止盈、PE、PB、ROE、美股、港股、**A股**、**沪深**、**上证**、**深证**、**创业板**、**科创板**、**北交所**、**打板**、**涨停**、**龙虎榜**、**北向资金**、**融资融券**、**大宗交易**、财报、技术分析、**缠论**、**分型**、**笔**、**线段**、**中枢**、**背驰**、**一买**、**二买**、**三买**、**一卖**、**二卖**、**三卖**、**顶分型**、**底分型**、**选股**、**推荐**、**标的**、**标的池**、**筛选**、**三维评分**、**宏观筛选**、**中观过滤**

---

## ⚠️ 推荐股票强制执行规则（禁止跳过）

用户要求**推荐股票**时，必须按以下三层流程完整执行，**不得跳过任何一步，不得仅从单一板块挑选**。

### 第 1 步 — 跨板块全市场扫描

必须扫描以下 **全量 8 个板块**，一个不能少：

| 板块 | 必须覆盖的代表性标的 |
|------|-------------------|
| 互联网/IT | 腾讯、阿里、美团、网易、小米、快手、京东、百度、哔哩哔哩、金山软件、京东健康 |
| 金融/保险/券商 | 汇丰、友邦、港交所、工行、中行、建行、招行、平安、人寿、太保、中信银行、中国银河 |
| 能源/资源/矿业 | 中海油、中石油、紫金矿业、洛阳钼业、兖矿能源 |
| 通信/运营商 | 中国移动、中国电信、中国联通 |
| 消费/食品/零售 | 农夫山泉、海底捞、蒙牛、安踏、申洲国际、华润啤酒、恒安国际、青岛啤酒、中国飞鹤 |
| 医药/生物科技 | 百济神州、药明生物、石药集团、中国生物制药、信达生物 |
| 制造/工业/半导体 | 比亚迪、舜宇光学、吉利汽车、中芯国际、华虹宏力、潍柴动力、中国重汽 |
| 公用事业/基建/交运 | 中电控股、电能实业、长江基建、港灯、海丰国际、新奥能源 |

### 第 2 步 — 中观硬约束过滤

列出以下剔除条件及被剔除的标的：

| 条件 | 港股阈值 |
|------|---------|
| 最小市值 | ≥ 50亿 HKD |
| 最小股价 | ≥ 1 HKD |
| PE上限 | ≤ 80（亏损公司标记"亏损"不自动过滤，PE>80剔除）|
| 净利恶化 | 标记净利同比下滑>50%的标的 |

### 第 3 步 — 微观三维评分排序

使用 `quantrisk` 模块中的 `key_indicators_eastmoney_async` 和 `kline_tickflow_async` 获取基本面和K线，自动计算各项指标和缠论信号。

评分标准：每维 1-5 分
- 基本面评分依据：营收增速、净利增速、ROE、毛利率、负债率
- 热点评分依据：板块今日涨幅和市场位置
- 缠论评分依据：MA60位置、MACD柱方向、背驰信号、中枢位置

**总分 = 基本面评分 × 5 + 热点评分 × 3 + 缠论评分 × 2**

**最终推荐按总分从高到低排列，不得按板块分配名额。****

### 输出模板 — 选股推荐报告

输出必须严格按此结构，**不得改变段落顺序和格式**：

```markdown
## 港股选股推荐 | {date}

### ① 全市场扫描（8 板块）

| 板块 | 扫描只数 | 今日表现 |
|------|:-------:|---------|
| 互联网/IT | {n} | {表现} |
| 金融/保险/券商 | {n} | {表现} |
| 能源/资源/矿业 | {n} | {表现} |
| 通信/运营商 | {n} | {表现} |
| 消费/食品/零售 | {n} | {表现} |
| 医药/生物科技 | {n} | {表现} |
| 制造/工业/半导体 | {n} | {表现} |
| 公用事业/基建/交运 | {n} | {表现} |

### ② 中观过滤（剔除明细）

| 剔除标的 | 原因 |
|---------|------|
| {code} {name} | {原因} |

候选池 {n} 只通过过滤。

### ③ 三维评分 TOP10

| 排名 | 标的 | 板块 | 基本面(×5) | 热点(×3) | 缠论(×2) | 总分 | 建议 |
|:----:|------|:----:|:----------:|:--------:|:--------:|:----:|------|
| ⭐1 | **{code} {name}** | {板块} | {n} | {n} | {n} | **{n}** | {建议} |
| ⭐2 | **{code} {name}** | {板块} | {n} | {n} | {n} | **{n}** | {建议} |
| ⭐3 | **{code} {name}** | {板块} | {n} | {n} | {n} | **{n}** | {建议} |
| ⭐4 | **{code} {name}** | {板块} | {n} | {n} | {n} | **{n}** | {建议} |
| ⭐5 | **{code} {name}** | {板块} | {n} | {n} | {n} | **{n}** | {建议} |
| ⭐6 | **{code} {name}** | {板块} | {n} | {n} | {n} | **{n}** | {建议} |
| ⭐7 | **{code} {name}** | {板块} | {n} | {n} | {n} | **{n}** | {建议} |
| ⭐8 | **{code} {name}** | {板块} | {n} | {n} | {n} | **{n}** | {建议} |
| ⭐9 | **{code} {name}** | {板块} | {n} | {n} | {n} | **{n}** | {建议} |
| ⭐10 | **{code} {name}** | {板块} | {n} | {n} | {n} | **{n}** | {建议} |

### ⭐ 各股详细分析

#### 1. {name}（{code}）— {price} 港元 | {pct}%

| 维度 | 评分 | 依据 |
|:----:|:----:|------|
| 📊 **基本面** | **{n}/5** | PE={n} / 营收={n}% / 净利={n}% / ROE={n}% / 毛利率={n}% / 负债率={n}%。{判断} |
| 🔥 **热点** | **{n}/5** | {板块}板块{表现} |
| 🔧 **缠论** | **{n}/5** | MA60={n} / 现价={n} / MACD柱={n} / {信号}。{判断} |

**建议**：{操作建议}。止损 {price}。

#### 2~5. 同上格式

### 综合建议

| 标的 | 建议 | 入场区间 | 止损 | 目标 |
|:----|:----:|:--------:|:----:|:----:|
| {code} | {建议} | {区间} | {price} | {price} |
| {code} | {建议} | {区间} | {price} | {price} |
| {code} | {建议} | {区间} | {price} | {price} |
| {code} | {建议} | {区间} | {price} | {price} |
| {code} | {建议} | {区间} | {price} | {price} |
| {code} | {建议} | {区间} | {price} | {price} |
| {code} | {建议} | {区间} | {price} | {price} |
| {code} | {建议} | {区间} | {price} | {price} |
| {code} | {建议} | {区间} | {price} | {price} |
| {code} | {建议} | {区间} | {price} | {price} |

> ⚠️ 声明：以上分析仅基于公开市场数据，不构成投资建议。
```

---

## Prerequisites

```bash
pip install aiohttp
# A 股数据（可选，仅在需要 A 股 K 线/财务快照时安装）
pip install mootdx
```

| 依赖 | 版本要求 | 用途 |
|------|---------|------|
| aiohttp | any | 所有 HTTP API 直连（全异步）|
| mootdx | >=0.10 | A 股多周期 K 线 + 财务快照（可选）|

## Install / Update

一键安装或更新本 skill：

```bash
curl -o ~/.claude/skills/quant-risk/SKILL.md \
  https://raw.githubusercontent.com/xiazhicheng/quant-risk/main/SKILL.md
# 同步缠论模块
curl -o ~/.claude/skills/quant-risk/quantrisk/chan.py \
  https://raw.githubusercontent.com/xiazhicheng/quant-risk/main/quantrisk/chan.py
mkdir -p ~/.claude/skills/quant-risk/quantrisk
```

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
from typing import Optional

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"

# ── A股市场前缀 ──────────────────────────
def cn_market_prefix(code: str) -> str:
    """A股代码 → 腾讯前缀: sh/sz/bj"""
    if code.startswith(("6", "9")):
        return "sh"
    if code.startswith(("0", "3")):
        return "sz"
    if code.startswith(("4", "8")):
        return "bj"
    return "sz"

def cn_secid(code: str) -> str:
    """A股代码 → 东财 secid: 0.上证 / 1.深证"""
    prefix = "1" if code.startswith(("6", "9")) else "0"
    return f"{prefix}.{code}"

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

### 1.6 A股行情 — 腾讯财经（主推，不封IP）

```python
async def cn_stock_quote_tencent_async(code: str) -> dict:
    """A股实时行情，腾讯源。code: 688017, 000858 等6位代码。
    返回 name/price/change_pct/pe_ttm/pb/market_cap_100m/
    turnover_rate/high/low/high_limit/low_limit/volume/amount"""
    text = await _aio_get_gbk(f"https://qt.gtimg.cn/q={cn_market_prefix(code)}{code}")
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
        "name": fields[1], "code": fields[2], "price": sf(fields[3]),
        "change_pct": sf(fields[32]), "pe_ttm": sf(fields[39]),
        "pb": sf(fields[46]), "market_cap_100m": sf(fields[44]),
        "total_shares_100m": sf(fields[45]),
        "high": sf(fields[33]), "low": sf(fields[34]),
        "turnover_rate": sf(fields[38]),
        "volume": sf(fields[6]), "amount_100m": sf(fields[37]),
        "high_limit": sf(fields[48]), "low_limit": sf(fields[49]),
        "amp": sf(fields[43]), "timestamp": fields[30] if len(fields) > 30 else "",
    }
```

### 1.7 A股行情 — 东财 push2

```python
async def cn_stock_quote_eastmoney_async(code: str) -> dict:
    """A股 push2 实时行情。code: 6位代码，自动识别上证(0.)/深证(1.)"""
    secid = cn_secid(code)
    d = (await _aio_get_json("https://push2.eastmoney.com/api/qt/stock/get", params={
        "secid": secid,
        "fields": "f43,f44,f45,f46,f47,f48,f55,f57,f58,f59,f60,f170,f116,f117,f100",
    })).get("data")
    if not d:
        return {}
    dec = d.get("f59", 2)
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
        "total_mv": _p("f116"), "float_mv": _p("f117"),
    }
```

### 1.8 A股基础信息 — 东财 push2

```python
async def cn_stock_basic_info_async(code: str) -> dict:
    """A股基本面信息：行业/总股本/流通股/上市日期/市盈率/市净率"""
    secid = cn_secid(code)
    d = (await _aio_get_json("https://push2.eastmoney.com/api/qt/stock/get", params={
        "secid": secid,
        "fields": "f57,f58,f84,f85,f98,f86,f116,f117,f100,f120,f121",
    })).get("data")
    return {
        "code": d.get("f57"), "name": d.get("f58"),
        "industry": d.get("f84"), "industry_ems": d.get("f85"),
        "listing_date": str(d.get("f98"))[:10] if d.get("f98") else None,
        "total_mv_100m": (d.get("f116") or 0) / 1e8,
        "float_mv_100m": (d.get("f117") or 0) / 1e8,
    } if d else {}

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

### 2.3 A股日K — 腾讯（前复权，主推，不封IP）

```python
async def cn_stock_kline_tencent_async(code: str, days: int = 120) -> list[dict]:
    """A股日K线，腾讯源，前复权。code: 6位代码，自动识别市场。
    返回 date/open/high/low/close/volume，适合回测和估值分析。"""
    url = f"http://ifzq.gtimg.cn/appstock/app/kline/mkline?param={cn_market_prefix(code)}{code},m,,{days}"
    d = await _aio_get_json(url, headers={"Referer": "https://finance.qq.com/"})
    data = d.get("data", {})
    key = f"{cn_market_prefix(code)}{code}"
    klines = data.get(key, {}).get("m", []) or data.get(key, {}).get("day", []) or []
    if not klines or not klines[0]:
        klines = data.get(key, {}).get("qfq", []) or data.get(key, {}).get("day", []) or []
    if not klines or not klines[0]:
        return []
    result = []
    for item in klines:
        if len(item) < 6:
            continue
        result.append({
            "date": item[0], "open": float(item[1]),
            "high": float(item[2]), "low": float(item[3]),
            "close": float(item[4]), "volume": int(item[5]),
        })
    return result
```

### 2.4 A股日K — 百度（带MA5/10/20）

```python
async def cn_stock_kline_baidu_async(code: str, start: str = "") -> list[dict]:
    """百度A股日K，直接返回MA5/MA10/MA20均价。code: 6位代码"""
    secid = cn_secid(code)
    d = await _aio_get_json(
        "https://gupiao.baidu.com/api/single/stockday",
        params={"code": secid, "start": start, "format": "json"},
        headers={"Referer": "https://gupiao.baidu.com/"},
    )
    items = d.get("data", []) if isinstance(d, dict) else d
    if not items:
        return []
    return [{"date": i.get("date"), "open": float(i.get("open", 0)),
             "high": float(i.get("high", 0)), "low": float(i.get("low", 0)),
             "close": float(i.get("close", 0)), "volume": int(i.get("volume", 0)),
             "ma5": float(i["ma"][0]) if i.get("ma") and len(i["ma"]) > 0 else None,
             "ma10": float(i["ma"][1]) if i.get("ma") and len(i["ma"]) > 1 else None,
             "ma20": float(i["ma"][2]) if i.get("ma") and len(i["ma"]) > 2 else None}
            for i in items]
```

### 2.5 A股多周期K线 — mootdx（TCP，分钟/日/周/月，同步）

```python
try:
    from mootdx.quotes import Quotes as _MootdxQuotes
    _MOOTDX_OK = True
except ImportError:
    _MOOTDX_OK = False

def _tdx_client():
    """创建 mootdx 客户端，带内置服务器探测和 fallback"""
    if not _MOOTDX_OK:
        raise ImportError("mootdx 未安装: pip install mootdx")
    servers = [
        ("119.147.212.81", 7709), ("180.153.18.170", 7709),
        ("59.175.238.38", 7709), ("112.74.214.43", 7709),
    ]
    for ip, port in servers:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1.5)
        try:
            s.connect((ip, port)); s.close()
            return _MootdxQuotes.factory(market="std", server=(ip, port))
        except:
            s.close()
            continue
    return _MootdxQuotes.factory(market="std")

def cn_stock_kline_tdx_sync(code: str, frequency: int = 9, start: int = 0,
                             count: int = 200) -> list[dict]:
    """A股K线（mootdx）。frequency: 9=日线, 8=1分钟, 0=5分钟,
    7=15分钟, 1=30分钟, 2=60分钟, 10=周, 11=月。返回不复权原始价。"""
    try:
        client = _tdx_client()
        df = client.bars(symbol=code, frequency=frequency, start=start, count=count)
        if df is None or df.empty:
            return []
        result = []
        for _, row in df.iterrows():
            result.append({
                "date": str(row.get("date", ""))[:19],
                "open": round(float(row.get("open", 0)), 2),
                "high": round(float(row.get("high", 0)), 2),
                "low": round(float(row.get("low", 0)), 2),
                "close": round(float(row.get("close", 0)), 2),
                "volume": int(row.get("volume", 0)),
                "amount": round(float(row.get("amount", 0)), 2),
            })
        return result
    except Exception as e:
        print(f"[WARN] mootdx K线获取失败({code}): {e}")
        return []
```

### 2.6 A股财务快照（同步 — mootdx）

```python
def cn_financial_snapshot_sync(code: str) -> dict:
    """A股最新季报财务快照（EPS/ROE/净利润/营收等）"""
    try:
        client = _tdx_client()
        df = client.finance(symbol=code)
        if df is None or df.empty:
            return {}
        report = df.iloc[-1].to_dict()
        return {
            "eps": round(float(report.get("eps", 0)), 4),
            "total_equity": float(report.get("equity", 0)),
            "revenue_total": float(report.get("revenue", 0)),
            "net_profit": float(report.get("net_profit", 0)),
            "roe_pct": round(float(report.get("roe", 0)) * 100, 2),
        }
    except Exception as e:
        print(f"[WARN] mootdx 财务快照失败({code}): {e}")
        return {}
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

## Layer 3.5: 缠论层（Chan Theory — 纯 Python 计算）

缠论（缠中说禅理论）是国内技术分析领域最系统的理论框架之一。本层实现核心组件：分型 → 包含处理 → 笔 → 线段 → 中枢 → 背驰 → 买卖点。

### 理论基础

```
K线包含处理 → 顶/底分型 → 笔（相邻分型连接） → 线段（笔的包含处理）
                                                    ↓
                        中枢（≥3段重叠区间）←─────────┘
                                                    ↓
                 趋势/盘整判断 → 背驰检测（力度/MACD） → 一/二/三类买卖点
```

- **分型 (Fractal)**：三根K线构成，中间最高→顶分型，中间最低→底分型。分型必须经过包含处理，顶分型最高K线的低点是分型下沿，底分型最低K线的高点是分型上沿。
- **笔 (Stroke/Pen)**：相邻顶底分型连线。上升笔 = 底分型 → 顶分型；下降笔 = 顶分型 → 底分型。标准笔要求至少 5 根独立K线且中间K线与首尾没有包含关系。
- **线段 (Segment)**：笔按严格规则进行特征序列包含处理后构成。不小于三笔且前三笔必须有重叠。
- **中枢 (Pivot/Zhongshu)**：至少三段连续重叠的区间。中枢区间 = [max(所有段低点), min(所有段高点)]。本级别中枢是次级别走势类型的重叠。
- **背驰 (Divergence)**：趋势力度衰竭。MACD 背驰 = 价格新高/新低但 MACD 柱面积缩小；力度背驰 = 后一段力度小于前一段。
- **买卖点**：一买 = 下跌趋势最后一个中枢后底背驰的终结点；一卖 = 上涨趋势最后一个中枢后顶背驰的终结点。二买/二卖 = 一买/一卖后的回调/反弹不创新低/新高。三买/三卖 = 中枢突破后的回踩/反弹不进入中枢。

### 3.5.1 K线包含处理

```python
def kline_contain(klines: list[dict]) -> list[dict]:
    """
    K线包含处理：向上的K线取高高（high 取 max, low 取 max），
    向下的K线取低低（high 取 min, low 取 min）。
    处理后相邻K线不再存在包含关系。
    """
    if len(klines) < 3:
        return klines
    result = [dict(klines[0])]
    for i in range(1, len(klines)):
        curr = dict(klines[i])
        prev = result[-1]
        # 判断包含方向：用倒数第二根非包含K线或 prev 之前的K线
        if len(result) >= 2:
            direction = "up" if result[-1]["high"] > result[-2]["high"] else "down"
        else:
            direction = "up" if curr["high"] > prev["high"] else "down"
        # 检测包含关系
        if (curr["high"] >= prev["high"] and curr["low"] <= prev["low"]) or \
           (curr["high"] <= prev["high"] and curr["low"] >= prev["low"]):
            if direction == "up":
                # 向上：高高 (取 high max, low max)
                merged = dict(prev)
                merged["high"] = max(prev["high"], curr["high"])
                merged["low"] = max(prev["low"], curr["low"])
                # 取接近当前的方向
                merged["close"] = curr["close"] if curr["close"] > prev["close"] else prev["close"]
                merged["volume"] = prev.get("volume", 0) + curr.get("volume", 0)
                result[-1] = merged
            else:
                # 向下：低低 (取 high min, low min)
                merged = dict(prev)
                merged["high"] = min(prev["high"], curr["high"])
                merged["low"] = min(prev["low"], curr["low"])
                merged["close"] = curr["close"] if curr["close"] < prev["close"] else prev["close"]
                merged["volume"] = prev.get("volume", 0) + curr.get("volume", 0)
                result[-1] = merged
        else:
            result.append(curr)
    return result
```

### 3.5.2 分型识别

```python
def find_fractals(klines: list[dict]) -> list[dict]:
    """
    识别顶分型和底分型。在包含处理后的K线中，i 位置的最高价 > i-1 和 i+1 的最高价 → 顶分型；
    i 位置的最低价 < i-1 和 i+1 的最低价 → 底分型。
    返回 [{index, type("top"/"bottom"), high, low, date}, ...]
    """
    if len(klines) < 3:
        return []
    processed = kline_contain(klines)
    fractals = []
    for i in range(1, len(processed) - 1):
        prev_k, cur_k, next_k = processed[i - 1], processed[i], processed[i + 1]
        # 顶分型：中间最高价最高，且左右K线的高点都低于中间，低点也低于或等于中间
        if cur_k["high"] > prev_k["high"] and cur_k["high"] > next_k["high"]:
            fractals.append({
                "index": i,
                "type": "top",
                "high": cur_k["high"],
                "low": cur_k["low"],
                "date": cur_k["date"],
            })
        # 底分型：中间最低价最低，且左右K线的低点都高于中间，高点也高于或等于中间
        elif cur_k["low"] < prev_k["low"] and cur_k["low"] < next_k["low"]:
            fractals.append({
                "index": i,
                "type": "bottom",
                "high": cur_k["high"],
                "low": cur_k["low"],
                "date": cur_k["date"],
            })
    return fractals
```

### 3.5.3 笔的构建

```python
def build_strokes(klines: list[dict], fractals: list[dict] = None) -> list[dict]:
    """
    从分型序列构建笔。原则：
    1. 相邻分型必须一个顶一个底交替出现
    2. 同方向选择最极端的（顶选更高的，底选更低的）
    3. 一笔至少包含 5 根独立K线，且分型之间至少有 1 根独立K线
    返回 [{type, start_index, end_index, start_date, end_date, high, low, direction}, ...]
    """
    if fractals is None:
        fractals = find_fractals(klines)
    if len(fractals) < 2:
        return []
    # 去重：同向分型取最极端包络
    filtered = [fractals[0]]
    for f in fractals[1:]:
        last = filtered[-1]
        if f["type"] == last["type"]:
            if f["type"] == "top" and f["high"] > last["high"]:
                filtered[-1] = f  # 更高的顶替换
            elif f["type"] == "bottom" and f["low"] < last["low"]:
                filtered[-1] = f  # 更低的底替换
        else:
            filtered.append(f)
    # 确保第一个是底分型（上升笔从底开始）或第一个是顶分型（下降笔从顶开始）
    strokes = []
    i = 0
    if filtered[0]["type"] == "top":
        i = 0
    else:
        i = 0
    while i < len(filtered) - 1:
        a, b = filtered[i], filtered[i + 1]
        # 必须是顶→底 或 底→顶
        if a["type"] == b["type"]:
            i += 1
            continue
        # 要求分型之间有足够距离（至少 1 根独立K线，总跨度≥5根）
        span = b["index"] - a["index"]
        if span < 4:  # 间隔不足，跳过较弱的分型
            if i + 2 < len(filtered):
                # 比较：a-b-c，如果 a-c 距离足够则跳过一个
                c = filtered[i + 2]
                if c["type"] != a["type"] and (c["index"] - a["index"]) >= 4:
                    i += 1
                    continue
            i += 1
            continue
        # 顶→底 = 下降笔，底→顶 = 上升笔
        direction = "down" if a["type"] == "top" else "up"
        stroke = {
            "type": a["type"],
            "start_index": a["index"],
            "end_index": b["index"],
            "start_date": a["date"],
            "end_date": b["date"],
            "high": max(a["high"], b["high"]),
            "low": min(a["low"], b["low"]),
            "direction": direction,
        }
        strokes.append(stroke)
        i += 1
    return strokes
```

### 3.5.4 线段构建

```python
def build_segments(klines: list[dict], strokes: list[dict] = None) -> list[dict]:
    """
    从笔构建线段。线段 = 至少 3 笔（且前三笔有重叠）的走势。
    特征序列包含处理：上升线段取向下笔的特征序列；下降线段取向上笔的特征序列。
    简化实现：识别能构成至少 3 笔重叠的连续走势。
    返回 [{type, start_index, end_index, start_date, end_date, high, low, stroke_count}, ...]
    """
    if strokes is None:
        strokes = build_strokes(klines)
    if len(strokes) < 3:
        return []
    segments = []
    i = 0
    while i <= len(strokes) - 3:
        s1, s2, s3 = strokes[i], strokes[i + 1], strokes[i + 2]
        # 三笔必须交替方向
        if s1["direction"] == s2["direction"] or s2["direction"] == s3["direction"]:
            i += 1
            continue
        # 前三笔必须有重叠区间
        overlap_high = min(s1["high"], s2["high"], s3["high"])
        overlap_low = max(s1["low"], s2["low"], s3["low"])
        if overlap_high <= overlap_low:
            i += 1
            continue
        # 向后延伸
        j = i + 3
        while j < len(strokes):
            next_s = strokes[j]
            new_high = min(overlap_high, next_s["high"])
            new_low = max(overlap_low, next_s["low"])
            if new_high <= new_low:
                # 不再重叠，停止延伸
                break
            overlap_high, overlap_low = new_high, new_low
            j += 1
        # 确定线段方向：以第一笔的方向为准
        seg_direction = s1["direction"]
        first = strokes[i]["type"]
        seg = {
            "start_index": strokes[i]["start_index"],
            "end_index": strokes[j - 1]["end_index"],
            "start_date": strokes[i]["start_date"],
            "end_date": strokes[j - 1]["end_date"],
            "high": max(s["high"] for s in strokes[i:j]),
            "low": min(s["low"] for s in strokes[i:j]),
            "stroke_count": j - i,
            "direction": seg_direction,
        }
        segments.append(seg)
        i = j  # 跳到下一段
    return segments
```

### 3.5.5 中枢识别

```python
def find_pivots(segments: list[dict], min_overlap: int = 3) -> list[dict]:
    """
    从线段中识别中枢（至少 min_overlap 段重叠）。
    带回溯的滑动窗口：从1个候选段开始逐步扩大，找到最长的重叠区间。
    返回 [{start_index, end_index, high, low, segment_count, zg(中轴), zd(中枢下沿), zz(中枢区间宽度)}, ...]
    """
    if len(segments) < min_overlap:
        return []
    pivots = []
    i = 0
    while i <= len(segments) - min_overlap:
        hi = segments[i]["high"]
        lo = segments[i]["low"]
        count = 1
        j = i + 1
        while j < len(segments):
            new_hi = min(hi, segments[j]["high"])
            new_lo = max(lo, segments[j]["low"])
            if new_hi <= new_lo:
                break
            hi, lo = new_hi, new_lo
            count += 1
            j += 1
        if count >= min_overlap:
            pivots.append({
                "start_index": segments[i]["start_index"],
                "end_index": segments[j - 1]["end_index"],
                "start_date": segments[i]["start_date"],
                "end_date": segments[j - 1]["end_date"],
                "high": hi,
                "low": lo,
                "segment_count": count,
                "zg": hi,  # 中枢上沿
                "zd": lo,  # 中枢下沿
                "zz_width": round(hi - lo, 4),  # 中枢区间宽度
            })
            i = j
        else:
            i += 1
    return pivots
```

### 3.5.6 趋势类型判别

```python
def classify_trend(pivots: list[dict], segments: list[dict]) -> dict:
    """
    根据中枢数量识别走势类型：
    - 0 中枢 → 单边走势
    - 1 中枢 → 盘整
    - ≥2 中枢 → 趋势（2 个=标准趋势，多于 2=大趋势）
    返回 {type("uptrend"/"downtrend"/"consolidation"), pivot_count, direction, description}
    """
    if not pivots:
        # 无中枢：用线段方向判断单边
        if segments:
            up_count = sum(1 for s in segments if s["direction"] == "up")
            down_count = len(segments) - up_count
            if up_count > down_count:
                return {"type": "uptrend", "pivot_count": 0, "direction": "up", "description": "无中枢单边上涨"}
            else:
                return {"type": "downtrend", "pivot_count": 0, "direction": "down", "description": "无中枢单边下跌"}
        return {"type": "unknown", "pivot_count": 0, "direction": "neutral", "description": "无足夠数据判断"}
    # 有中枢：判断整体方向
    if len(pivots) == 1:
        # 单中枢 = 盘整
        direction = "up" if segments and segments[-1]["direction"] == "up" else "down"
        return {"type": "consolidation", "pivot_count": 1, "direction": direction,
                "description": f"单中枢盘整（{'偏多' if direction=='up' else '偏空'}）"}
    # 多中枢 = 趋势
    first_pz = pivots[0]
    last_pz = pivots[-1]
    is_up = last_pz["high"] > first_pz["high"] and last_pz["low"] > first_pz["low"]
    if is_up:
        return {"type": "uptrend", "pivot_count": len(pivots),
                "direction": "up", "description": f"上涨趋势，含 {len(pivots)} 个中枢"}
    else:
        return {"type": "downtrend", "pivot_count": len(pivots),
                "direction": "down", "description": f"下跌趋势，含 {len(pivots)} 个中枢"}
```

### 3.5.7 背驰检测（MACD 背驰 + 力度背驰）

```python
def detect_divergence(klines: list[dict], segments: list[dict] = None,
                      strokes: list[dict] = None) -> list[dict]:
    """
    检测背驰：价格新高/新低，但 MACD 面积缩小 或 力度衰减。
    比较相邻两段同向走势：二段价格幅度 > 一段，但 MACD 面积 < 一段 → 背驰。
    返回 [{type("top_divergence"/"bottom_divergence"), date, severity("strong"/"weak"), detail}, ...]
    """
    if segments is None:
        segments = build_segments(klines)
    if not segments or len(segments) < 2:
        return []
    # 计算 MACD 数据（复用 Layer 3 的 calc_macd）
    macd_data = calc_macd(klines)
    if not macd_data:
        return []
    # 建立 K 线日期到 MACD 的映射
    macd_map = {m["date"]: m for m in macd_data}
    # 按 MACD 日期顺序构建索引
    macd_dates = [m["date"] for m in macd_data]
    divergences = []
    # 比较相邻同向走势
    for i in range(len(segments) - 1):
        s1, s2 = segments[i], segments[i + 1]
        if s1["direction"] != s2["direction"]:
            continue
        # 获取两段的起止日期
        s1_start_dt = s1["start_date"]
        s1_end_dt = s1["end_date"]
        s2_start_dt = s2["start_date"]
        s2_end_dt = s2["end_date"]
        # 计算价格幅度
        if s1["direction"] == "up":
            s1_range = s1["high"] - s1["low"]
            s2_range = s2["high"] - s2["low"]
        else:
            s1_range = s1["high"] - s1["low"]
            s2_range = s2["high"] - s2["low"]
        # 计算 MACD 柱面积（绝对值求和）
        def macd_area(start_date: str, end_date: str) -> float:
            area = 0.0
            in_range = False
            for d in macd_dates:
                if d >= start_date:
                    in_range = True
                if in_range:
                    if d > end_date:
                        break
                    m = macd_map.get(d, {})
                    hist = abs(m.get("macd_hist", 0))
                    area += hist
            return area
        s1_area = macd_area(s1_start_dt, s1_end_dt)
        s2_area = macd_area(s2_start_dt, s2_end_dt)
        # 力度比较
        if s1["direction"] == "up":
            # 顶背驰：价格新高但 MACD 面积缩小
            price_higher = s2["high"] > s1["high"]
            macd_weaker = s2_area < s1_area * 0.85  # 15% 阈值
            if price_higher and macd_weaker:
                severity = "strong" if s2_area < s1_area * 0.5 else "weak"
                divergences.append({
                    "type": "top_divergence",
                    "date": s2["end_date"],
                    "segment_1_range": round(s1_range, 2),
                    "segment_2_range": round(s2_range, 2),
                    "segment_1_macd_area": round(s1_area, 2),
                    "segment_2_macd_area": round(s2_area, 2),
                    "severity": severity,
                    "detail": f"顶背驰：{'强' if severity=='strong' else '弱'}，MACD 面积从 {s1_area:.1f} 衰减至 {s2_area:.1f}",
                })
        else:
            # 底背驰：价格新低但 MACD 面积缩小
            price_lower = s2["low"] < s1["low"]
            macd_weaker = s2_area < s1_area * 0.85
            if price_lower and macd_weaker:
                severity = "strong" if s2_area < s1_area * 0.5 else "weak"
                divergences.append({
                    "type": "bottom_divergence",
                    "date": s2["end_date"],
                    "segment_1_range": round(s1_range, 2),
                    "segment_2_range": round(s2_range, 2),
                    "segment_1_macd_area": round(s1_area, 2),
                    "segment_2_macd_area": round(s2_area, 2),
                    "severity": severity,
                    "detail": f"底背驰：{'强' if severity=='strong' else '弱'}，MACD 面积从 {s1_area:.1f} 衰减至 {s2_area:.1f}",
                })
    return divergences
```

### 3.5.8 买卖点定位

```python
def find_buy_sell_points(klines: list[dict], pivots: list[dict] = None,
                          segments: list[dict] = None,
                          divergences: list[dict] = None) -> dict:
    """
    根据缠论三类买卖点定义定位买卖点：
    一买：最后一个中枢后，底背驰终结点（下跌趋势结束点）
    一卖：最后一个中枢后，顶背驰终结点（上涨趋势结束点）
    二买：一买后回调不创新低的点（确认）
    二卖：一卖后反弹不创新高的点（确认）
    三买：中枢上沿突破后，回踩不跌入中枢的点
    三卖：中枢下沿跌破后，反弹不回到中枢的点
    
    简化实现：基于背驰定位一买/一卖，基于回调比例和中枢位置定位二/三买卖点。
    """
    if segments is None:
        segments = build_segments(klines)
    if pivots is None:
        pivots = find_pivots(segments)
    if divergences is None:
        divergences = detect_divergence(klines, segments)
    result = {"buy_points": [], "sell_points": []}
    if not klines or len(klines) < 10:
        return result
    last_price = klines[-1]["close"]
    # ── 一买定位：底背驰的终结点 ──
    for d in divergences:
        if d["type"] == "bottom_divergence":
            result["buy_points"].append({
                "type": "first_buy",
                "date": d["date"],
                "level": "strong" if d["severity"] == "strong" else "weak",
                "price": last_price,
                "detail": f"一买（{d['detail']}）",
            })
    # ── 一卖定位：顶背驰的终结点 ──
    for d in divergences:
        if d["type"] == "top_divergence":
            result["sell_points"].append({
                "type": "first_sell",
                "date": d["date"],
                "level": "strong" if d["severity"] == "strong" else "weak",
                "price": last_price,
                "detail": f"一卖（{d['detail']}）",
            })
    # ── 二买/二卖定位：基于一买/一卖后的回调 ──
    if pivots and segments:
        last_pivot = pivots[-1]
        # 二买：价格位于最后一个中枢上方附近但不属于中枢内部 → 偏多方
        if last_price > last_pivot["zg"]:
            # 价格在中枢上方 → 潜在的三买（当前简化：仍按二买逻辑）
            result["buy_points"].append({
                "type": "third_buy",
                "date": klines[-1]["date"],
                "level": "potential",
                "price": last_price,
                "detail": f"价格 {last_price} 位于中枢上方 {last_pivot['zg']}，回踩不入中枢则构成三买",
            })
        elif last_pivot["zd"] <= last_price <= last_pivot["zg"]:
            # 价格在中枢内 → 盘整，当前不构成买卖点
            pass
        else:
            # 价格在中枢下方 → 若未背驰则观望；若已背驰则为一买区域
            # 一买后的二次确认回调
            if result["buy_points"]:
                first_buy_price = result["buy_points"][0].get("price", last_price)
                if last_price <= first_buy_price * 1.03:  # 回调 3% 内
                    result["buy_points"].append({
                        "type": "second_buy",
                        "date": klines[-1]["date"],
                        "level": "potential",
                        "price": last_price,
                        "detail": f"二买试探：一买后回调不创新低，当前 {last_price}",
                    })
    # ── 三买/三卖：中枢突破回踩 ──
    if pivots and segments:
        last_pivot = pivots[-1]
        if len(segments) >= 3:
            # 三卖：价格持续低于中枢下沿
            if last_price < last_pivot["zd"]:
                result["sell_points"].append({
                    "type": "third_sell",
                    "date": klines[-1]["date"],
                    "level": "potential",
                    "price": last_price,
                    "detail": f"三卖警示：价格 {last_price} 跌破中枢下沿 {last_pivot['zd']}，反弹不回中枢则确认三卖",
                })
    return result
```

### 3.5.9 全功能一键计算

```python
def chan_theory_full(klines: list[dict], min_stroke_span: int = 4) -> dict:
    """
    缠论全流程计算：包含处理 → 分型 → 笔 → 线段 → 中枢 → 背驰 → 买卖点。
    返回完整结构供缠论分析。
    """
    if not klines or len(klines) < 10:
        return {"error": "K线数据不足（至少 10 根）"}
    klines_clean = kline_contain(klines)
    fractals = find_fractals(klines)
    strokes = build_strokes(klines, fractals)
    segments = build_segments(klines, strokes)
    pivots = find_pivots(segments)
    divergences = detect_divergence(klines, segments, strokes)
    buy_sell = find_buy_sell_points(klines, pivots, segments, divergences)
    trend = classify_trend(pivots, segments)
    return {
        "klines_count": len(klines),
        "klines_clean_count": len(klines_clean),
        "fractals_count": len(fractals),
        "fractals": fractals,
        "strokes_count": len(strokes),
        "strokes": strokes,
        "segments_count": len(segments),
        "segments": segments,
        "pivots_count": len(pivots),
        "pivots": pivots,
        "divergences_count": len(divergences),
        "divergences": divergences,
        "buy_sell_points": buy_sell,
        "trend": trend,
        "current_price": klines[-1]["close"] if klines else None,
    }
```

### 3.5.10 缠论风控集成

```python
def chan_risk_assessment(klines: list[dict]) -> dict:
    """
    基于缠论输出风控评估结论：
    - 当前走势类型（单边/盘整/趋势）
    - 是否有背驰信号（顶/底背驰及强度）
    - 当前处于哪类买卖点区域
    - 最近中枢位置（上方/内部/下方）
    """
    result = chan_theory_full(klines)
    if "error" in result:
        return result
    trend = result["trend"]
    pivots = result["pivots"]
    divergences = result["divergences"]
    buy_sell = result["buy_sell_points"]
    price = result["current_price"]
    # 判断当前相对于中枢的位置
    relative_position = "unknown"
    distance_to_pivot = None
    if pivots:
        last_pz = pivots[-1]
        if price > last_pz["zg"]:
            relative_position = "above_pivot"
            distance_to_pivot = round((price - last_pz["zg"]) / last_pz["zg"] * 100, 2)
        elif price < last_pz["zd"]:
            relative_position = "below_pivot"
            distance_to_pivot = round((price - last_pz["zd"]) / last_pz["zd"] * 100, 2)
        else:
            relative_position = "within_pivot"
            distance_to_pivot = 0.0
    # 风控信号
    risk_signals = []
    # 背驰信号
    for d in divergences:
        if d["type"] == "top_divergence":
            risk_signals.append({"signal": "bearish_divergence", "severity": d["severity"], "detail": d["detail"]})
        elif d["type"] == "bottom_divergence":
            risk_signals.append({"signal": "bullish_divergence", "severity": d["severity"], "detail": d["detail"]})
    # 买卖点信号
    if buy_sell.get("buy_points"):
        for bp in buy_sell["buy_points"]:
            risk_signals.append({"signal": f"{bp['type']}", "severity": bp.get("level", "potential"), "detail": bp["detail"]})
    if buy_sell.get("sell_points"):
        for sp in buy_sell["sell_points"]:
            risk_signals.append({"signal": f"{sp['type']}", "severity": sp.get("level", "potential"), "detail": sp["detail"]})
    # 中枢位置信号
    if relative_position == "above_pivot":
        risk_signals.append({"signal": "above_pivot", "severity": "bullish", "detail": f"价格位于中枢上方 {distance_to_pivot}%，偏强"})
    elif relative_position == "below_pivot":
        risk_signals.append({"signal": "below_pivot", "severity": "bearish", "detail": f"价格位于中枢下方 {distance_to_pivot}%，偏弱"})
    else:
        risk_signals.append({"signal": "within_pivot", "severity": "neutral", "detail": "价格在中枢内震荡，等待方向选择"})
    # 综合评分（简化：正=偏多，负=偏空）
    score = 0
    if trend["direction"] == "up":
        score += 2
    elif trend["direction"] == "down":
        score -= 2
    if relative_position == "above_pivot":
        score += 1
    elif relative_position == "below_pivot":
        score -= 1
    bull_div = sum(1 for d in divergences if d["type"] == "bottom_divergence")
    bear_div = sum(1 for d in divergences if d["type"] == "top_divergence")
    score += bull_div * 3 - bear_div * 3
    if score >= 3:
        chan_verdict = "偏多"
    elif score <= -3:
        chan_verdict = "偏空"
    else:
        chan_verdict = "中性"
    return {
        "trend": trend,
        "relative_position": relative_position,
        "distance_to_pivot_pct": distance_to_pivot,
        "risk_signals": risk_signals,
        "chan_score": score,
        "chan_verdict": chan_verdict,
        "pivots": pivots,
        "divergences": divergences,
        "buy_sell_points": buy_sell,
    }
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

### 4.8 A股关键财务指标 — 东财 datacenter

```python
async def cn_key_indicators_async(code: str, page_size: int = 4) -> list[dict]:
    """A股关键财务指标，东财 datacenter。code: 6位代码"""
    secucode = f"{cn_secid(code).replace('.', '.')}"
    # A股 secucode 格式: "0.000858" 或 "1.600519"
    secucode = f"{'SH' if code.startswith(('6','9')) else 'SZ'}{code}"
    # 有些东财接口用 SH/SZ 前缀
    return await eastmoney_datacenter_async(
        "RPT_LICO_FN_CPD", filter_str=f'(SECUCODE="{secucode}")',
        page_size=page_size, sort_columns="REPORT_DATE", sort_types="-1",
    )
```

### 4.9 A股财报三表 — 新浪

```python
async def cn_financial_statements_sina_async(code: str, report_type: str = "lrb",
                                              num: int = 8) -> list[dict]:
    """A股三表。report_type: lrb=利润表, fzb=资产负债表, llb=现金流量表。num=期数"""
    url = f"https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketData.getKLineData"
    d = await _aio_get_json(url, params={
        "symbol": cn_market_prefix(code) + code,
        "scale": num, "datalen": 1, "type": report_type,
    }, headers={"Referer": "https://vip.stock.finance.sina.com.cn/"})
    if not d:
        return []
    return d
```

### 4.10 A股机构一致预期EPS — 同花顺（同步）

```python
try:
    import pandas as pd
    _PANDAS_OK = True
except ImportError:
    _PANDAS_OK = False

def cn_eps_forecast_sync(code: str) -> list[dict]:
    """机构一致预期EPS。走同花顺 basic.10jqka.com.cn。返回 [{year, eps, count}, ...] """
    try:
        url = f"https://basic.10jqka.com.cn/{code}/index.html"
        import requests
        r = requests.get(url, headers={"User-Agent": UA}, timeout=10)
        html = r.text
        # 从HTML中提取数据ID (附注: 同花顺数据ID可能会有变化)
        import urllib.parse
        m = re.search(r'var\s+resData\s*=\s*({.+?});', html, re.DOTALL)
        if not m:
            return []
        import json
        data = json.loads(m.group(1))
        eps = data.get("eps", data.get("EPS", {}))
        if isinstance(eps, dict):
            items = eps.get("data", eps.get("items", eps.get("list", [])))
            if isinstance(items, dict):
                items = list(items.values())
            if isinstance(items, list):
                result = []
                for item in items[:5]:
                    year = item.get("year", item.get("reportDate", item.get("REPORT_DATE", "")))
                    val = item.get("val", item.get("eps", item.get("EPS", 0)))
                    cnt = item.get("count", item.get("num", item.get("NUM", 0)))
                    result.append({
                        "year": str(year)[:4],
                        "eps": float(val) if val else 0,
                        "count": int(cnt) if cnt else 0,
                    })
                return result
    except Exception as e:
        print(f"[WARN] 一致预期EPS失败({code}): {e}")
    return []
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

### 5.1 A股资金流 — 东财 push2his（分钟级）

```python
async def cn_fund_flow_minute_async(code: str) -> list[dict]:
    """A股分钟级资金流向（主力/大单/中单/小单）。code: 6位"""
    secid = cn_secid(code)
    d = (await _aio_get_json("https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get", params={
        "secid": secid, "klt": 101,
        "fields1": "f1,f2,f3,f7", "fields2": "f51,f52,f53,f54,f55,f56,f57", "lmt": 200,
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

### 5.2 A股融资融券 — 东财 datacenter

```python
async def cn_margin_trading_async(code: str, page_size: int = 30) -> list[dict]:
    """融资融券明细（日级）。返回 date/rzye(融资余额)/rzmre(融资买入)/rqyl(融券余额)/rqmc(融券卖出)"""
    market = "SH" if code.startswith(("6", "9")) else "SZ"
    return await eastmoney_datacenter_async(
        "RPTA_WEB_MARGINTRADING_DETAILS",
        filter_str=f'(SECURITY_CODE="{code}")(TRADE_MARKET_CODE="{market}")',
        page_size=page_size, sort_columns="TRADE_DATE", sort_types="-1",
    )
```

### 5.3 A股大宗交易 — 东财 datacenter

```python
async def cn_block_trade_async(code: str, page_size: int = 20) -> list[dict]:
    """大宗交易记录。返回 date/price/volume/premium(溢价率)/buyer(买方)/seller(卖方)"""
    market = "SH" if code.startswith(("6", "9")) else "SZ"
    return await eastmoney_datacenter_async(
        "RPT_DATA_BLOCKTRADE",
        filter_str=f'(SECURITY_CODE="{code}")(MARKET="{market}")',
        page_size=page_size, sort_columns="TRADE_DATE", sort_types="-1",
    )
```

### 5.4 A股股东户数 — 东财 datacenter

```python
async def cn_holder_num_change_async(code: str, page_size: int = 10) -> list[dict]:
    """股东户数变化（季度级）。返回 date/holder_num/change_ratio(环比)/avg_shares(户均持股)"""
    market = "SH" if code.startswith(("6", "9")) else "SZ"
    return await eastmoney_datacenter_async(
        "RPTA_WEB_HOLDERNUM_CHANGE",
        filter_str=f'(SECUCODE="{market}{code}")',
        page_size=page_size, sort_columns="END_DATE", sort_types="-1",
    )
```

### 5.5 A股分红送转 — 东财 datacenter

```python
async def cn_dividend_history_async(code: str, page_size: int = 20) -> list[dict]:
    """分红送转历史。返回 date/bonus(每股派息)/bonus_ratio/transfer(转增)/send(送股)"""
    market = "SH" if code.startswith(("6", "9")) else "SZ"
    return await eastmoney_datacenter_async(
        "RPTA_WEB_DIVIDEND_HISTORY",
        filter_str=f'(SECUCODE="{market}{code}")',
        page_size=page_size, sort_columns="REPORT_DATE", sort_types="-1",
    )
```

---

## Layer 6: A股信号层（独有）

### 6.1 A股强势股 + 题材归因 — 同花顺

```python
async def ths_hot_stocks_async(date: str = None) -> list[dict]:
    """当日强势股 + 题材归因。date: YYYY-MM-DD，默认今日。
    返回每只: code/name/price/pct/reason(题材标签)/high_days(连板天数)"""
    if not date:
        from datetime import date as dt_date
        date = dt_date.today().strftime("%Y%m%d")
    try:
        s = await get_async_session()
        async with s.get("https://data.10jqka.com.cn/dataapi/limit_up/limit_up_pool",
                         params={"page": 1, "limit": 200,
                                 "field": "199112,10,9001,330323,330324,330325,9002,330329,133971,133970,1968584,3475914,9003,9004",
                                 "filter": "HS,GEM2STAR", "order_field": "330324", "order_type": "0", "date": date},
                         headers={"User-Agent": UA}) as resp:
            info = (await resp.json()).get("data", {}).get("info", [])
    except Exception as e:
        print(f"[WARN] 同花顺强势股请求失败: {e}")
        return []
    return [{"code": it.get("code"), "name": it.get("name"),
             "price": it.get("latest"), "pct": it.get("change_rate"),
             "reason": it.get("reason_type", ""),
             "high_days": it.get("high_days", "")}
            for it in info]
```

### 6.2 A股北向资金 — 东财

```python
async def northbound_flow_async() -> dict:
    """北向资金分钟级流向。返回 sh_net(沪股通净流入)/sz_net(深股通净流入)/total(合计)"""
    try:
        s = await get_async_session()
        async with s.get("https://push2.eastmoney.com/api/qt/ulist.np/get",
                         params={"fields": "f62,f184,f66,f69,f72,f75,f78,f81,f84,f87,f204,f205,f124",
                                 "secids": "1.000001,0.399001"},
                         headers={"Referer": "https://quote.eastmoney.com/"}) as resp:
            d = await resp.json()
        diff = (d.get("data") or {}).get("diff") or []
        if isinstance(diff, dict):
            diff = list(diff.values())
        sh_net, sz_net = 0.0, 0.0
        for item in diff:
            code = str(item.get("f12", ""))
            if code == "000001":
                sh_net = (item.get("f62") or 0) / 100
            elif code == "399001":
                sz_net = (item.get("f62") or 0) / 100
        return {"sh_net": round(sh_net, 2), "sz_net": round(sz_net, 2),
                "total": round(sh_net + sz_net, 2)}
    except Exception as e:
        print(f"[WARN] 北向资金获取失败: {e}")
        return {}
```

### 6.3 A股板块归属 — 东财

```python
async def cn_concept_blocks_async(code: str) -> dict:
    """个股所属全部板块（行业/概念/地域）。返回 {industry, concept_tags: [], region}"""
    secid = cn_secid(code)
    try:
        s = await get_async_session()
        async with s.get("https://push2.eastmoney.com/api/qt/slist/get",
                         params={"spt": 3, "secids": secid,
                                 "fields": "f12,f14,f3,f4"},
                         headers={"Referer": "https://quote.eastmoney.com/"}) as resp:
            d = await resp.json()
        diff = (d.get("data") or {}).get("diff") or []
        if isinstance(diff, dict):
            diff = list(diff.values())
        industry, concepts, region = "", [], ""
        for item in diff:
            bk = str(item.get("f12", ""))
            name = item.get("f14", "")
            if bk.startswith("BK"):
                if bk.startswith("BK08") and not industry:
                    industry = name
                elif bk.startswith("BK09"):
                    region = name
                else:
                    concepts.append(name)
        return {"industry": industry, "concept_tags": concepts[:20], "region": region}
    except Exception as e:
        print(f"[WARN] 板块归属获取失败: {e}")
        return {}
```

### 6.4 A股龙虎榜 — 东财 datacenter

```python
async def cn_dragon_tiger_board_async(code: str, look_back: int = 30) -> list[dict]:
    """龙虎榜席位。返回 date/reason(上榜原因)/net_buy(净买入额)"""
    return await eastmoney_datacenter_async(
        "RPTA_WEB_DRAGON_TIGER_LIST",
        filter_str=f'(SECURITY_CODE="{code}")',
        page_size=look_back, sort_columns="TRADE_DATE", sort_types="-1",
    )
```

### 6.5 A股限售解禁 — 东财 datacenter

```python
async def cn_lockup_expiry_async(code: str, forward_days: int = 90) -> list[dict]:
    """限售解禁日历。返回 date/count(解禁股数)/ratio(占总股本比)/holder(持有人)"""
    return await eastmoney_datacenter_async(
        "RPTA_WEB_LOCKUP_EXPIRY",
        filter_str=f'(SECURITY_CODE="{code}")',
        page_size=forward_days, sort_columns="EXPIRE_DATE", sort_types="1",
    )
```

### 6.6 A股行业板块排名 — 东财 push2

```python
async def cn_industry_ranking_async(top_n: int = 20) -> list[dict]:
    """行业板块涨跌排名。返回 rank/industry(行业名)/pct(涨跌幅)/up(涨家数)/down(跌家数)"""
    try:
        s = await get_async_session()
        async with s.get("https://push2.eastmoney.com/api/qt/clist/get",
                         params={"fs": "m:90+t:2", "fields": "f2,f3,f4,f5,f6,f12,f14",
                                 "pn": 1, "pz": top_n, "fid": "f3", "po": 1}) as resp:
            d = await resp.json()
        diff = (d.get("data") or {}).get("diff") or []
        if isinstance(diff, dict):
            diff = list(diff.values())
        return [{"industry": i.get("f14"), "pct": round((i.get("f3") or 0) / 100, 2),
                 "up": i.get("f4"), "down": i.get("f5")}
                for i in diff if i.get("f14")]
    except Exception as e:
        print(f"[WARN] 行业排名获取失败: {e}")
        return []
```

---

## Layer 8: A股公告层（巨潮 cninfo）

### 8.1 A股公告检索 — 巨潮 cninfo

```python
async def cninfo_announcements_async(code: str, page_size: int = 30) -> list[dict]:
    """A股全量公告检索（沪深北）。code: 6位代码。返回 date/title/type/url"""
    try:
        async with aiohttp.ClientSession(headers={"User-Agent": UA}) as sess:
            async with sess.post(
                "http://www.cninfo.com.cn/new/fulltextSearch/full",
                data={"searchkey": code, "sdate": "", "edate": "",
                      "isfulltext": "false", "sortName": "pubdate",
                      "sortType": "desc", "pageNum": 1},
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                data = await resp.json()
        results = data.get("announcements", []) if isinstance(data, dict) else []
        return [{"date": r.get("announcementDate", ""),
                 "title": r.get("announcementTitle", ""),
                 "type": r.get("announcementTypeName", ""),
                 "url": r.get("adjunctUrl", "")}
                for r in results[:page_size]]
    except Exception as e:
        print(f"[WARN] 巨潮公告检索失败: {e}")
        return []
```

---

## Layer 9: 期权层（仅美股）

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

## Layer 10: SEC Filing 层（仅美股）

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

## Layer 11: 工具层

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
| A股行情 | 腾讯 sh/sz（47字段，不封IP） | 东财 push2 secid:0-1 |
| A股日K线 | 腾讯（前复权，不封IP） | 百度（带MA）/ mootdx（多周期）|
| A股资金流 | 东财 push2his | — |
| A股融资融券/大宗/股东 | 东财 datacenter | — |
| A股强势股/题材 | 同花顺 | — |
| A股北向资金 | 东财 push2 ulist | — |
| A股板块归属 | 东财 slist | — |
| A股龙虎榜 | 东财 datacenter | — |
| A股解禁预警 | 东财 datacenter | — |
| A股行业排名 | 东财 push2 clist | — |
| A股公告 | 巨潮 cninfo | — |
| A股一致预期EPS | 同花顺 basic | — |
| A股财务快照 | mootdx finance | 新浪三表 |
| 港股行情 | 腾讯 r_hkXXXXX（78字段） | 新浪/东财 push2 |
| 美股行情 | 新浪 gb_XXXX（36字段） | 腾讯/东财 push2 |
| 美股K线 | 新浪 | Yahoo chart |
| 港股K线 | Yahoo chart | — |
| 关键指标(中文) | 东财 GMAININDICATOR | — |
| 关键指标(英文) | Yahoo quoteSummary | — |
| 财报三表(中文) | 东财 datacenter | — |
| 分析师/机构 | Yahoo quoteSummary | — |
| 资金流 | 东财 push2his | — |
| 技术指标(MA/MACD/RSI/KDJ/BOLL) | 纯 Python 计算（Layer 3） | — |
| 缠论(分型/笔/线段/中枢/背驰) | 纯 Python 计算（Layer 3.5, 基于K线） | — |
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

## 标的池三层筛选逻辑（核心方法论）

选股推荐必须经过以下三层筛选，**不得凭感觉或经验直接推票**。

```
                          ┌─────────────────────┐
                          │  ① 宏观筛选层        │
                          │  全市场扫描 → 热点板块 │
                          └─────────┬───────────┘
                                    ↓
                          ┌─────────────────────┐
                          │  ② 中观过滤层        │
                          │  流动性/市值/基本面过滤 │
                          └─────────┬───────────┘
                                    ↓
                          ┌─────────────────────┐
                          │  ③ 微观精选层        │
                          │  热点+基本面+缠论三维评分 │
                          └─────────┬───────────┘
                                    ↓
                          输出: 综合排序推荐
```

### ① 宏观筛选层 — 全市场扫描

**目标**：找出当前市场热点板块和领涨品种，构建候选池。

| 维度 | 数据源 | 说明 |
|------|--------|------|
| 板块/行业排名 | 东财 push2 clist（港股 `m:116`） | 按涨跌幅排序，取涨幅前 10 行业 |
| 市场指数定位 | HSI / 恒科指 涨跌幅+成交量 | 判断整体市场情绪（强势/弱势/震荡） |
| 板块资金流向 | 南向资金（港股通）净买入 | 确认资金是否持续流入 |
| 宏观催化事件 | 政策发布 / 龙头公司新闻 | 识别关键驱动 |

**候选池生成规则**：
- 从涨幅前 5 的板块中各取成交量前 5 的股票 → 约 25 只
- 从恒生指数 / 恒科指成分股中取近 5 日涨幅前 10（排除已被板块选中的）
- 合计候选池约 **30-40 只**

**代码**：
```python
async def build_candidate_pool(market: str = "hk", top_sectors: int = 5, top_per_sector: int = 5) -> list[dict]:
    """① 宏观筛选：构建候选池"""
    # 1. 获取行业排名
    sectors = await cn_industry_ranking_async(top_n=20)
    hot_sectors = [s for s in sectors if s.get("pct", 0) > 0][:top_sectors]
    # 2. 从各热点行业选股
    candidates = []
    for sec in hot_sectors:
        sector_stocks = await market_stock_list_async(
            market=market, sort_field="f3", sort_desc=True, page=1, page_size=top_per_sector
        )
        for s in (sector_stocks.get("stocks") or [])[:top_per_sector]:
            s["sector"] = sec.get("industry", "")
            s["sector_pct"] = sec.get("pct", 0)
            candidates.append(s)
    return sectored_candidates if (sectored_candidates := candidates) else []
```

### ② 中观过滤层 — 硬约束剔除

**目标**：剔除不合格品种，确保池中标的具备基本投资价值。

| 过滤条件 | 港股 | 美股 | A股 |
|---------|------|------|-----|
| 最小市值 | ≥ 50亿 HKD | ≥ 10亿 USD | ≥ 30亿 CNY |
| 最小日均成交额 | ≥ 1,000万 HKD | ≥ 500万 USD | ≥ 3,000万 CNY |
| 最小股价 | ≥ 1 HKD（非仙股）| ≥ 2 USD | ≥ 2 CNY |
| PE 上限（盈利公司）| ≤ 50（金融≤ 20）| ≤ 80 | ≤ 60 |
| PE 负值（亏损公司）| 标记为"亏损"不自动过滤 | 同左 | 同左 |
| 涨跌停/停牌 | 排除停牌股 | — | 排除涨跌停封板股 |

**代码**：
```python
def filter_candidates(candidates: list[dict]) -> list[dict]:
    """② 中观过滤：硬约束剔除"""
    filtered = []
    for c in candidates:
        price = c.get("price") or 0
        vol = c.get("volume") or 0
        # 最小价格 & 成交额过滤（港股示例）
        if price < 1.0: continue
        if vol < 1_000_0000: continue  # 成交额低于 1000万（东财数据单位需校准）
        filtered.append(c)
    return filtered
```

### ③ 微观精选层 — 三维评分排序

**目标**：对过滤后的候选池按 热点 + 基本面 + 缠论 三维评分，排序输出。

**评分标准（每维 1-5 分）**：

| 维度 | 5分 | 3分 | 1分 |
|------|-----|-----|-----|
| 🔥 **热点** | 处于当前最强主线 + 有明确催化剂 | 处于当前热点但非核心 | 不在当前热点 |
| 📊 **基本面** | PE合理+营收增长+ROE>15%+龙头 | 估值合理但增长平淡 | 估值偏高或亏损 |
| 🔧 **缠论** | 有明确买卖点信号(一买/一卖) | 无买卖点但结构清晰 | 无信号+结构混乱 |

**综合评分公式**：
```
总分 = 热点 × 权重(3) + 基本面 × 权重(5) + 缠论 × 权重(2)
```
权重体现方法论排序：**基本面为主(5) > 热点(3) > 缠论(2)**

**排序输出**：按总分从高到低，并标注风格标签。

**代码**：
```python
def score_candidate(hot_score: int, fundamental_score: int, chan_score: int) -> dict:
    """③ 微观精选：三维评分"""
    weights = {"hot": 3, "fundamental": 5, "chan": 2}
    total = hot_score * weights["hot"] + fundamental_score * weights["fundamental"] + chan_score * weights["chan"]
    return {"hot_score": hot_score, "fundamental_score": fundamental_score, "chan_score": chan_score,
            "total_score": total}

def rank_candidates(scored: list[dict]) -> list[dict]:
    """按总分排序输出"""
    return sorted(scored, key=lambda x: x["total_score"], reverse=True)
```

### 一键调用

```python
def run_stock_selection(market: str = "hk") -> list[dict]:
    """标的池筛选全流程"""
    async def _run():
        # ① 宏观筛选
        pool = await build_candidate_pool(market)
        # ② 中观过滤
        pool = filter_candidates(pool)
        # ③ 微观评分（需人工审核热点+基本面+缠论数据）
        # 此步骤依赖外部行情+基本面+缠论数据，在分析报告中逐票完成
        return pool
    return asyncio.run(_run())
```

### 使用规范

1. **每次选股推荐必须先跑筛选流程**，不得直接从记忆中提取股票
2. 筛选结果输出**候选池数量**（如"从 35 只候选池中筛选……"）
3. 最终推荐原则上不超过 **5 只**
4. 三维评分必须与具体分析对应，不得编造分数
5. 如果当日数据获取失败，标注数据缺失的维度，**不编造**

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

### 缠论技术面

| 指标 | 值 |
|------|----|
| 走势类型 | {趋势/盘整/单边}（{中枢数量} 个中枢） |
| 最近中枢区间 | [{zd} – {zg}] |
| 当前相对中枢位置 | {上方/内部/下方}（距中枢 {distance}%） |
| 分型数量 | {顶分型} 顶 / {底分型} 底 |
| 笔数量 | {x} 笔（最近一笔方向: {方向}） |
| 背驰信号 | {无/顶背驰(强/弱)/底背驰(强/弱)} |
| 买卖点信号 | {一买/二买/三买/一卖/二卖/三卖 或无} |
| 缠论评分 | {score}（偏多/中性/偏空） |

### 基本面评分

| 维度 | 评分(1-5) | 得分依据 |
|------|----------|---------|
| 行业景气度 | {1-5} | {行业上行/平稳/下行 + 政策环境利好/中性/利空} |
| 竞争格局 | {1-5} | {龙头/分散/激烈 + 产业链议价力} |
| 盈利质量 | {1-5} | 毛利率 {x}% / 净利率 {x}% / ROE {x}% |
| 财务健康 | {1-5} | 资产负债率 {x}% / 流动比率 {x} |
| 成长性 | {1-5} | 营收同比 {x}% / 行业增速对比 |

**综合风险等级**: {低/中/较高/高}

### 当前热点匹配

| 检查项 | 状态 |
|--------|------|
| 所属热点板块 | {板块名称} |
| 是否处于当前主线 | {是/否} |
| 近期催化剂 | {AI/政策/并购/财报/回购等} |
| 板块轮动位置 | {领涨/跟涨/补涨/退潮} |

### 三维度综合评估

| 维度 | 评分 | 方向 |
|------|------|------|
| 🔥 热点 | ★★★/★★/★ | {向上/平稳/向下} |
| 📊 基本面 | ★★★/★★/★ | {向上/平稳/向下} |
| 🔧 缠论 | ★★★/★★/★ | {偏多/中性/偏空} |

**综合**: {热点+基本面+缠论 三维共振/分歧判断}

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

### 热点变化追踪

| 检查项 | 上次 | 本次 | 变化方向 |
|--------|------|------|---------|
| 所属热点板块 | {old_sector} | {new_sector} | {持续/切换/退潮} |
| 板块相对大盘 | {old_rel}% | {new_rel}% | {跑赢/跑输} |
| 近期催化剂 | {old_catalyst} | {new_catalyst} | {加强/减弱} |

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
