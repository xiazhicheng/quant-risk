"""
quantrisk — 数据层（Data Layer）

合并五层数据获取：client 会话管理 + quotes 行情 + kline K线 + fundamental 基本面 + TickFlow 备选。
全部 aiohttp 异步，零鉴权（TickFlow 需 API Key）。

用法:
    from scripts.quantrisk.data import hk_stock_quote_tencent_async, stock_kline_yahoo_async, key_statistics_async
    from scripts.quantrisk.data import kline_tickflow_async  # 免费免注册，无需 API Key
    result = await hk_stock_quote_tencent_async("03690")

数据源:
    行情 (L1): 腾讯 > 新浪 > 东财 push2
    K线 (L2): Yahoo > 腾讯(A股) > 新浪(美股) > TickFlow(备选)
    基本面 (L4): 东财 datacenter > Yahoo
    资金面 (L5): 东财 push2
"""
import asyncio, aiohttp, json, re, functools
from datetime import datetime
from typing import Optional

# ═════════════════════════════════════════════════
# HTTP 会话 / 并行执行 / 工具
# ═════════════════════════════════════════════════

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
_async_session: Optional[aiohttp.ClientSession] = None
_yahoo_crumb: Optional[str] = None
_yahoo_session: Optional[aiohttp.ClientSession] = None

# ═════════════════════════════════════════════════
# 数据源调用统计 & retry 装饰器（Failover 基础设施）
# ═════════════════════════════════════════════════

_data_source_stats: dict = {"sources": {}, "total_calls": 0, "total_failures": 0}


def _record_source(name: str, success: bool = True):
    """记录数据源调用结果，用于监控和调试。"""
    s = _data_source_stats.setdefault(name, {"ok": 0, "fail": 0})
    s["ok" if success else "fail"] += 1
    if success:
        _data_source_stats["total_calls"] = _data_source_stats.get("total_calls", 0) + 1
    else:
        _data_source_stats["total_failures"] = _data_source_stats.get("total_failures", 0) + 1


def get_data_source_stats() -> dict:
    """返回各数据源成功/失败统计。"""
    return dict(_data_source_stats)


def reset_data_source_stats():
    """重置数据源统计（测试用）。"""
    _data_source_stats.clear()
    _data_source_stats["sources"] = {}
    _data_source_stats["total_calls"] = 0
    _data_source_stats["total_failures"] = 0


def retry_async(max_attempts: int = 3, delay: float = 1.0, backoff: float = 2.0, logger=None):
    """异步函数重试装饰器，指数退避。

    用法:
        @retry_async(max_attempts=3, delay=1.0)
        async def fetch_data(...): ...
    """
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exc = e
                    if logger:
                        logger(f"{func.__name__} 尝试 {attempt+1}/{max_attempts} 失败: {e}")
                    if attempt < max_attempts - 1:
                        await asyncio.sleep(delay * (backoff ** attempt))
            raise last_exc
        return wrapper
    return decorator

def cn_market_prefix(code: str) -> str:
    """A股代码 → 腾讯前缀: sh/sz/bj"""
    if code.startswith(("6", "9")): return "sh"
    if code.startswith(("0", "3")): return "sz"
    if code.startswith(("4", "8")): return "bj"
    return "sz"

def cn_secid(code: str) -> str:
    """A股代码 → 东财 secid"""
    return f"{'1' if code.startswith(('6','9')) else '0'}.{code}"

async def get_async_session() -> aiohttp.ClientSession:
    global _async_session
    if _async_session is None or _async_session.closed:
        _async_session = aiohttp.ClientSession(
            headers={"User-Agent": UA}, timeout=aiohttp.ClientTimeout(total=20))
    return _async_session

async def close_async_session():
    global _async_session, _yahoo_session
    if _async_session and not _async_session.closed: await _async_session.close()
    if _yahoo_session and not _yahoo_session.closed: await _yahoo_session.close()

async def _get(url: str, **kw) -> str:
    s = await get_async_session()
    async with s.get(url, **kw) as r:
        return await r.text()

async def _get_json(url: str, **kw) -> dict:
    s = await get_async_session()
    async with s.get(url, **kw) as r:
        t = await r.text(); return json.loads(t) if t.strip() else {}

async def _get_gbk(url: str, **kw) -> str:
    s = await get_async_session()
    async with s.get(url, **kw) as r: return (await r.read()).decode("gbk")

async def parallel_map(funcs: list, max_concurrency: int = 30) -> list:
    sem = asyncio.Semaphore(max_concurrency)
    async def _run(f):
        async with sem: return await f()
    return await asyncio.gather(*[_run(f) for f in funcs], return_exceptions=True)

async def _get_yahoo() -> tuple:
    global _yahoo_session, _yahoo_crumb
    if _yahoo_session is None or _yahoo_session.closed:
        _yahoo_session = aiohttp.ClientSession(
            headers={"User-Agent": UA}, timeout=aiohttp.ClientTimeout(total=15))
        await _yahoo_session.get("https://fc.yahoo.com")
        async with _yahoo_session.get("https://query2.finance.yahoo.com/v1/test/getcrumb") as r:
            _yahoo_crumb = (await r.text()).strip()
    return _yahoo_session, _yahoo_crumb

async def yahoo_quote_summary(symbol: str, modules: list[str]) -> dict:
    s, crumb = await _get_yahoo()
    try:
        async with s.get(f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{symbol}",
                         params={"modules": ",".join(modules), "crumb": crumb}) as r:
            if r.status != 200:
                return {}
            js = await r.json()
            return js.get("quoteSummary", {}).get("result", [{}])[0] or {}
    except Exception:
        return {}

async def stock_search(keyword: str, count: int = 10) -> list[dict]:
    """东财股票搜索"""
    d = await _get_json("https://searchapi.eastmoney.com/api/suggest/get", params={
        "input": keyword, "type": 14, "token": "D43BF722C8E33BDC906FB84D85E326E8", "count": count})
    mkts = {"105":"NASDAQ","106":"NYSE","107":"US_OTHER","116":"HK"}
    return [{"code":s.get("Code"),"name":s.get("Name"),"market":mkts.get(str(s.get("MktNum","")),"")}
            for s in d.get("QuotationCodeTable",{}).get("Data",[]) if str(s.get("MktNum","")) in mkts]

async def stock_news(keyword: str, count: int = 10) -> list[dict]:
    s,_ = await _get_yahoo()
    async with s.get("https://query2.finance.yahoo.com/v1/finance/search",
                     params={"q":keyword,"quotesCount":0,"newsCount":count}) as r:
        news = (await r.json()).get("news",[])
    return [{"title":n.get("title"),"publisher":n.get("publisher"),"link":n.get("link")} for n in news]

async def market_stock_list(market:str="hk", sort_field:str="f3", sort_desc:bool=True,
                             page:int=1, page_size:int=20) -> dict:
    mkt_map = {"us_nasdaq":"m:105","us_nyse":"m:106","us_etf":"m:107","hk":"m:116"}
    d = await _get_json("https://push2.eastmoney.com/api/qt/clist/get", params={
        "fs":mkt_map.get(market,market), "fields":"f2,f3,f4,f5,f6,f7,f12,f14,f15,f16,f17,f18",
        "pn":page, "pz":page_size, "fid":sort_field, "po":1 if sort_desc else 0})
    diff = d.get("data",{}).get("diff",[]) or []
    if isinstance(diff, dict): diff = list(diff.values())
    stocks = [{"code":i.get("f12"),"name":i.get("f14"),"price":i.get("f2"),
               "change_pct":round(i["f3"]/100,2) if i.get("f3") is not None else None,
               "volume":i.get("f5"),"amount":i.get("f6")} for i in diff]
    return {"total":d.get("data",{}).get("total",0),"stocks":stocks}

async def ticker_to_cik(ticker: str) -> dict:
    d = await _get_json("https://www.sec.gov/files/company_tickers.json",
                        headers={"User-Agent":"global-stock-data/2.0"})
    for _,v in d.items():
        if v.get("ticker")==ticker.upper():
            return {"ticker":ticker.upper(),"cik":str(v["cik_str"]).zfill(10),"company":v.get("title")}
    return {}

async def eastmoney_datacenter(report_name:str, columns:str="ALL", filter_str:str="",
                                page_size:int=50, sort_columns:str="", sort_types:str="-1") -> list[dict]:
    """东财 datacenter 统一入口（带异常捕获）。"""
    try:
        d = await _get_json(DATACENTER_URL, params={
            "reportName":report_name,"columns":columns,"filter":filter_str,
            "pageNumber":"1","pageSize":str(page_size),"sortColumns":sort_columns,
            "sortTypes":sort_types,"source":"WEB","client":"WEB"})
    except Exception as e:
        print(f"[WARN] 东财datacenter({report_name})失败: {e}")
        return []
    return d.get("result",{}).get("data",[]) if d.get("result") else []

# ═════════════════════════════════════════════════
# L1: 行情层 (Quotes)
# ═════════════════════════════════════════════════

def _sf(v):
    try: return float(v) if v and v!="-" else 0.0
    except: return 0.0

async def hk_stock_quote_tencent_async(code: str) -> dict:
    """港股行情（腾讯 78 字段）。code: 00700, 03690, 09988, 00020"""
    # 腾讯需要5位补零 (e.g. 0020 → 00020)
    code = code.zfill(5)
    text = await _get_gbk(f"https://qt.gtimg.cn/q=r_hk{code}")
    m = re.search(r'"(.+)"', text)
    if not m: return {}
    f = m.group(1).split("~")
    if len(f)<50: return {}
    return {"name":f[1],"price":_sf(f[3]),"change_pct":_sf(f[32]),"pe":_sf(f[39]),
            "pe_ttm":_sf(f[57]) if len(f)>57 else 0,
            "pb":_sf(f[56]),"market_cap_100m":_sf(f[44]),"high":_sf(f[33]),"low":_sf(f[34]),
            "open":_sf(f[5]),"prev_close":_sf(f[4]),"volume_shares":int(_sf(f[6])),
            "amount_100m":_sf(f[37]),"high_52w":_sf(f[35]),"low_52w":_sf(f[36]),
            "amp":_sf(f[43]),"turnover_rate":_sf(f[38]),"dividend_yield":_sf(f[31]) if len(f)>31 else 0,
            "roe":_sf(f[64]) if len(f)>64 else 0,
            "profit_margin":_sf(f[65]) if len(f)>65 else 0,
            "revenue_growth":_sf(f[71]) if len(f)>71 else 0,
            "gross_margin":_sf(f[72]) if len(f)>72 else 0,
            "debt_ratio":_sf(f[74]) if len(f)>74 else 0,
            "timestamp":f[30] if len(f)>30 else ""}

async def us_stock_quote_tencent_async(ticker: str) -> dict:
    """美股行情（腾讯 71 字段）。ticker: AAPL, TSLA"""
    text = await _get_gbk(f"https://qt.gtimg.cn/q=us{ticker.upper()}")
    m = re.search(r'"(.+)"', text)
    if not m: return {}
    f = m.group(1).split("~")
    if len(f)<50: return {}
    return {"name":f[1],"price":_sf(f[3]),"change_pct":_sf(f[32]),"pe":_sf(f[53]),
            "pb":_sf(f[56]),"market_cap":_sf(f[44]),"high":_sf(f[33]),"low":_sf(f[34]),
            "volume":int(_sf(f[6])),"high_52w":_sf(f[35]),"low_52w":_sf(f[36])}

async def us_stock_quote_sina_async(ticker: str) -> dict:
    """美股行情（新浪 36 字段）"""
    text = await _get_gbk(f"https://hq.sinajs.cn/list=gb_{ticker.lower()}",
                          headers={"Referer":"https://finance.sina.com.cn/"})
    m = re.search(r'"(.+)"', text)
    if not m: return {}
    f = m.group(1).split(",")
    if len(f)<30: return {}
    return {"name":f[0],"price":float(f[1]),"change_pct":float(f[2]),
            "open":float(f[5]) if f[5] else 0,"high":float(f[6]) if f[6] else 0,
            "low":float(f[7]) if f[7] else 0,"volume":float(f[10]) if f[10] else 0,
            "high_52w":float(f[8]) if f[8] else 0,"low_52w":float(f[9]) if f[9] else 0,
            "market_cap":float(f[12]) if f[12] else 0,"eps":float(f[13]) if f[13] else 0,
            "pe":float(f[14]) if f[14] else 0}

async def hk_stock_quote_sina_async(code: str) -> dict:
    """港股行情（新浪 25 字段）"""
    text = await _get_gbk(f"https://hq.sinajs.cn/list=rt_hk{code}",
                          headers={"Referer":"https://finance.sina.com.cn/"})
    m = re.search(r'"(.+)"', text)
    if not m: return {}
    f = m.group(1).split(",")
    return {"name":f[1],"open":float(f[2]) if f[2] else 0,"prev_close":float(f[3]) if f[3] else 0,
            "high":float(f[4]) if f[4] else 0,"low":float(f[5]) if f[5] else 0,
            "price":float(f[6]) if f[6] else 0,"change_pct":float(f[8]) if f[8] else 0,
            "volume":float(f[12]) if f[12] else 0}


async def hk_company_profile_async(code: str) -> dict:
    """港股公司资料（新浪 info 页面，提取主营业务描述）。返回 {business: str}"""
    code = code.zfill(5)
    url = f"https://stock.finance.sina.com.cn/hkstock/info/{code}.html"
    try:
        text = await _get_gbk(url, headers={"User-Agent": "Mozilla/5.0"})
    except Exception:
        return {}

    # 提取"公司业务"单元格内容
    m = re.search(r"公司业务</span></td>\s*<td[^>]*>(.*?)</td>", text, re.DOTALL)
    if not m:
        return {}
    raw = m.group(1).strip()
    # 清理 HTML 标签
    business = re.sub(r"<[^>]+>", "", raw).strip()
    if not business:
        return {}
    return {"business": business}


async def stock_quote_eastmoney_async(ticker_or_code: str, secid_prefix: int = 105) -> dict:
    """东财 push2 统一行情。105=NASDA, 106=NYSE, 116=港股"""
    d = (await _get_json("https://push2.eastmoney.com/api/qt/stock/get", params={
        "secid":f"{secid_prefix}.{ticker_or_code}",
        "fields":"f43,f44,f45,f46,f47,f48,f55,f57,f58,f59,f60,f170"})).get("data")
    if not d: return {}
    dec = d.get("f59",3); div = 10**dec
    def _p(k):
        v=d.get(k); return round(v/div,dec) if v is not None and v!="-" else None
    return {"code":d.get("f57"),"name":d.get("f58"),"price":_p("f43"),"high":_p("f44"),
            "low":_p("f45"),"open":_p("f46"),"volume":d.get("f47"),"amount":d.get("f48"),
            "turnover_rate":d.get("f55"),"prev_close":_p("f60"),
            "change_pct":round(d["f170"]/100,2) if d.get("f170") is not None else None}

async def cn_stock_quote_tencent_async(code: str) -> dict:
    """A股实时行情（腾讯主推，不封IP）。code: 688017, 000858

    腾讯A股接口字段单位:
      f[6]  = 成交量（手），需×100转成股
      f[37] = 成交额（万元），需×10000转成元
      f[44] = 总市值（亿），保持
    """
    text = await _get_gbk(f"https://qt.gtimg.cn/q={cn_market_prefix(code)}{code}")
    m = re.search(r'"(.+)"', text)
    if not m: return {}
    f = m.group(1).split("~")
    if len(f)<50: return {}
    return {"name":f[1],"code":f[2],"price":_sf(f[3]),"change_pct":_sf(f[32]),
            "pe_ttm":_sf(f[39]),"pb":_sf(f[46]),"market_cap_100m":_sf(f[44]),
            "total_shares_100m":_sf(f[45]),"high":_sf(f[33]),"low":_sf(f[34]),
            "turnover_rate":_sf(f[38]),
            "volume":int(_sf(f[6]) * 100) if _sf(f[6]) else 0,  # 手→股
            "amount_100m":_sf(f[37]) * 10000,  # 万元→元
            "high_limit":_sf(f[48]),"low_limit":_sf(f[49]),"amp":_sf(f[43]),
            "timestamp":f[30] if len(f)>30 else ""}

async def cn_stock_quote_eastmoney_async(code: str) -> dict:
    """A股行情（东财 push2）"""
    d = (await _get_json("https://push2.eastmoney.com/api/qt/stock/get", params={
        "secid":cn_secid(code),
        "fields":"f43,f44,f45,f46,f47,f48,f55,f57,f58,f59,f60,f170,f116,f117,f100"})).get("data")
    if not d: return {}
    dec = d.get("f59",2); div = 10**dec
    def _p(k):
        v=d.get(k); return round(v/div,dec) if v is not None and v!="-" else None
    return {"code":d.get("f57"),"name":d.get("f58"),"price":_p("f43"),"high":_p("f44"),
            "low":_p("f45"),"open":_p("f46"),"volume":d.get("f47"),"amount":d.get("f48"),
            "turnover_rate":d.get("f55"),"prev_close":_p("f60"),
            "change_pct":round(d["f170"]/100,2) if d.get("f170") is not None else None,
            "total_mv":_p("f116"),"float_mv":_p("f117")}

async def cn_stock_basic_info_async(code: str) -> dict:
    """A股基本信息（行业/市值等）— 使用 curl 避免 aiohttp 连接问题"""
    import json
    url = (f"https://push2.eastmoney.com/api/qt/stock/get?secid={cn_secid(code)}"
           f"&fields=f57,f58,f84,f85,f98,f86,f116,f117,f100,f120,f121,f127,f128,f129")
    try:
        proc = await asyncio.create_subprocess_shell(
            f"/usr/bin/curl -s --max-time 15 -H 'Referer: https://quote.eastmoney.com/' '{url}'",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=20)
        if not stdout or len(stdout) < 50:
            return {}
        d = json.loads(stdout.decode())
        data = d.get("data") or {}
        if not data:
            return {}
        return {"code":data.get("f57"),"name":data.get("f58"),"industry":data.get("f127"),
                "listing_date":str(data.get("f98"))[:10] if data.get("f98") else None,
                "total_mv_100m":(data.get("f116") or 0)/1e8,"float_mv_100m":(data.get("f117") or 0)/1e8}
    except Exception as e:
        print(f"[WARN] cn_stock_basic_info_async({code}) 失败: {e}")
        return {}


async def cn_stock_quote_fallback(code: str) -> dict:
    """A股行情统一入口（腾讯→东财 push2）。任一源返回有效数据即终止。"""
    # 1. 腾讯（主推，不封IP）
    r = await cn_stock_quote_tencent_async(code)
    if r and r.get("name"):
        _record_source("cn_quote_tencent", True)
        return r
    _record_source("cn_quote_tencent", False)

    # 2. 东财 push2（备选）
    try:
        r = await cn_stock_quote_eastmoney_async(code)
        if r and r.get("name"):
            _record_source("cn_quote_eastmoney", True)
            return r
        _record_source("cn_quote_eastmoney", False)
    except Exception as e:
        _record_source("cn_quote_eastmoney", False)
        print(f"[WARN] 东财行情失败({code}): {e}")

    return {}


# ═════════════════════════════════════════════════
# L2: K线层 (Kline)
# ═════════════════════════════════════════════════

async def us_stock_kline_sina_async(ticker: str, num: int = 120) -> list[dict]:
    """美股日K（新浪，可回溯至1984年）"""
    text = await _get("https://stock.finance.sina.com.cn/usstock/api/jsonp.php/var/US_MinKService.getDailyK",
                      params={"symbol":ticker.upper(),"num":num},
                      headers={"Referer":"https://finance.sina.com.cn/"})
    m = re.search(r'\((\[.+\])\)', text)
    if not m: return []
    items = json.loads(m.group(1))
    return [{"date":i.get("d"),"open":float(i.get("o",0)),"high":float(i.get("h",0)),
             "low":float(i.get("l",0)),"close":float(i.get("c",0)),"volume":int(i.get("v",0))}
            for i in items]

async def stock_kline_yahoo_async(symbol: str, interval: str = "1d", range_: str = "1y") -> list[dict]:
    """Yahoo K线（美股+港股通用）。symbol: AAPL 或 0700.HK。
    使用 adjclose（前复权收盘价），兼容所有拆股/分红事件。"""
    # Yahoo 对港股 ticker 格式不统一：部分接受前导零(0020.HK)，部分不接受(09999.HK→9999.HK)。
    # 先试原始格式，再试去前导零格式，确保覆盖两种情况。
    candidates = [symbol]
    parts = symbol.split(".")
    if len(parts) == 2 and parts[0].isdigit():
        stripped = f"{int(parts[0])}.{parts[1]}"
        if stripped != symbol:
            candidates.append(stripped)
    for sym in candidates:
        d = await _get_json(f"https://query2.finance.yahoo.com/v8/finance/chart/{sym}",
                            params={"interval":interval,"range":range_})
        chart = d.get("chart", {})
        if chart.get("result") and chart["result"] and chart["result"][0]:
            break
    chart = d.get("chart", {})
    if not chart or not chart.get("result") or not chart["result"] or not chart["result"][0]:
        return []
    chart = chart["result"][0]
    ts = chart.get("timestamp",[])
    q = chart.get("indicators",{}).get("quote",[{}])[0]
    adj = chart.get("indicators",{}).get("adjclose",[{}])[0].get("adjclose", [])
    sub = "m" in interval or "h" in interval
    result = []
    for i, t in enumerate(ts):
        if q["open"][i] is None: continue
        # 优先用 adjclose（前复权），缺失时回退 close
        close_price = adj[i] if (i < len(adj) and adj[i] is not None) else q["close"][i]
        result.append({"date":datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M" if sub else "%Y-%m-%d"),
                       "open":round(q["open"][i],2),"high":round(q["high"][i],2),
                       "low":round(q["low"][i],2),"close":round(float(close_price),2),
                       "volume":int(q["volume"][i])})
    return result
async def hk_kline_tencent_async(code: str, period: str = "day", count: int = 120) -> list[dict]:
    """腾讯港股K线（日K/周K）。code: 5位数字代码，period: day/week，count: 条数。
    注意：分钟级(5m/60m)只返回当天1根，不建议用于缠论分析。"""
    url = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=hk{code},{period},,,{count},qfq"
    d = await _get_json(url, headers={"Referer": "https://finance.qq.com/"})
    data = d.get("data", {})
    hk_key = f"hk{code}"
    klines_data = data.get(hk_key, {}).get(period, [])
    if not klines_data:
        return []
    result = []
    for item in klines_data:
        if len(item) < 6:
            continue
        bar = {
            "date": str(item[0])[:10],
            "open": float(item[1]),
            "close": float(item[2]),
            "high": float(item[3]),
            "low": float(item[4]),
            "volume": int(float(item[5])),
        }
        # Daily data has an extra metadata dict; minute data doesn't
        if len(item) > 6 and isinstance(item[6], dict):
            bar["metadata"] = item[6]
        result.append(bar)
    return result



async def cn_stock_kline_tencent_async(code: str, days: int = 120) -> list[dict]:
    """A股日K线（腾讯，前复权，不封IP）"""
    url = f"http://ifzq.gtimg.cn/appstock/app/kline/mkline?param={cn_market_prefix(code)}{code},qfq,,{days}"
    d = await _get_json(url, headers={"Referer":"https://finance.qq.com/"})
    data = d.get("data",{})
    key = f"{cn_market_prefix(code)}{code}"
    # 优先前复权 qfq，兜底原始 m
    klines = data.get(key,{}).get("qfq",[]) or data.get(key,{}).get("m",[]) or data.get(key,{}).get("day",[]) or []
    if not klines or not klines[0]:
        klines = data.get(key,{}).get("m",[]) or data.get(key,{}).get("day",[]) or []
    if not klines or not klines[0]: return []
    return [{"date":i[0],"open":float(i[1]),"high":float(i[2]),"low":float(i[3]),
             "close":float(i[4]),"volume":int(i[5])} for i in klines if len(i)>=6]

async def cn_stock_kline_baidu_async(code: str, start: str = "") -> list[dict]:
    """A股日K（百度，带MA5/10/20）"""
    d = await _get_json("https://gupiao.baidu.com/api/single/stockday",
                        params={"code":cn_secid(code),"start":start,"format":"json"},
                        headers={"Referer":"https://gupiao.baidu.com/"})
    items = d.get("data",[]) if isinstance(d,dict) else d
    if not items: return []
    return [{"date":i.get("date"),"open":float(i.get("open",0)),"high":float(i.get("high",0)),
             "low":float(i.get("low",0)),"close":float(i.get("close",0)),"volume":int(i.get("volume",0)),
             "ma5":float(i["ma"][0]) if i.get("ma") and len(i["ma"])>0 else None,
             "ma10":float(i["ma"][1]) if i.get("ma") and len(i["ma"])>1 else None,
             "ma20":float(i["ma"][2]) if i.get("ma") and len(i["ma"])>2 else None}
            for i in items]


async def cn_stock_kline_fallback(code: str, days: int = 365) -> list[dict]:
    """A股日K统一入口（腾讯qfq→百度→TickFlow）。任一源返回≥20根即终止。"""
    kl = []

    # 1. 腾讯前复权（主推）
    try:
        kl = await cn_stock_kline_tencent_async(code, days=days)
        if len(kl) >= 20:
            _record_source("cn_kline_tencent", True)
            return kl
        _record_source("cn_kline_tencent", False)
    except Exception as e:
        _record_source("cn_kline_tencent", False)
        print(f"[WARN] 腾讯K线失败({code}): {e}")

    # 2. 百度（备选，带MA）
    try:
        kl = await cn_stock_kline_baidu_async(code)
        if len(kl) >= 20:
            _record_source("cn_kline_baidu", True)
            return kl
        _record_source("cn_kline_baidu", False)
    except Exception as e:
        _record_source("cn_kline_baidu", False)
        print(f"[WARN] 百度K线失败({code}): {e}")

    # 3. TickFlow（最终备选）
    try:
        from scripts.quantrisk.data import kline_tickflow_async
        # 判断交易所后缀（6/9=SH, 0/3=SZ, 4/8=BJ）
        suffix = "SZ" if not code.startswith(("6", "9")) else "SH"
        kl = await kline_tickflow_async(f"{code}.{suffix}", "1d", days)
        if kl:
            _record_source("cn_kline_tickflow", True)
            return kl
        _record_source("cn_kline_tickflow", False)
    except Exception as e:
        _record_source("cn_kline_tickflow", False)
        print(f"[WARN] TickFlow K线失败({code}): {e}")

    return kl if kl else []


# ── 港股分钟级K线（60min/30min，三级 fallback 链） ──────────

# 东财 push2 周期映射
_EASTMONEY_KLTL_MAP = {"60m": "60", "30m": "30", "15m": "15", "5m": "5", "1m": "1"}

async def hk_kline_eastmoney_async(code: str, interval: str = "60m", limit: int = 500) -> list[dict]:
    """港股分钟K线（东财 push2）。
    code: 5位数字，interval: 60m/30m/15m，limit: 最大返回条数。
    secid 前缀 116=港股，klt=60 表示60分钟，fqt=1 前复权。"""
    klt = _EASTMONEY_KLTL_MAP.get(interval, "60")
    try:
        d = await _get_json(
            "https://push2.eastmoney.com/api/qt/stock/kline/get",
            params={
                "secid": f"116.{code}",
                "fields1": "f1,f2,f3",
                "fields2": "f51,f52,f53,f54,f55,f56,f57",
                "klt": klt,
                "fqt": "1",
                "end": "20500101",
                "lmt": str(limit),
            },
            headers={"Referer": "https://quote.eastmoney.com/"},
        )
    except Exception:
        return []
    klines = (d.get("data") or {}).get("klines") or []
    if not klines:
        return []
    result = []
    for item in klines:
        parts = item.split(",")
        if len(parts) < 7:
            continue
        result.append({
            "date": parts[0],
            "open": float(parts[1]),
            "close": float(parts[2]),
            "high": float(parts[3]),
            "low": float(parts[4]),
            "volume": int(float(parts[5])),
        })
    return result


async def hk_kline_sina_minute_async(code: str, minute_type: int = 60) -> list[dict]:
    """港股分钟K线（新浪财经）。
    code: 5位数字，minute_type: 60/30/15 对应分钟数。
    API 返回最近约 100 根。"""
    try:
        s = await get_async_session()
        url = (f"https://stock.finance.sina.com.cn/hkstock/api/"
               f"jsonp.php/var%20_HK_MinKService_xxx/"
               f"jsonp/HK_MinKService.getMinK")
        params = {"symbol": f"hk{code}", "type": str(minute_type)}
        async with s.get(url, params=params,
                         headers={"Referer": "https://stock.finance.sina.com.cn/"}) as r:
            text = await r.text()
    except Exception:
        return []
    import re
    m = re.search(r'\((\[.+\])\)', text)
    if not m:
        return []
    try:
        items = json.loads(m.group(1))
    except Exception:
        return []
    return [{
        "date": i.get("d", ""),
        "open": float(i.get("o", 0)),
        "high": float(i.get("h", 0)),
        "low": float(i.get("l", 0)),
        "close": float(i.get("c", 0)),
        "volume": int(i.get("v", 0)),
    } for i in items if i.get("c") is not None]


async def hk_kline_minute_async(code: str, interval: str = "60m", min_bars: int = 30) -> list[dict]:
    """港股分钟K线统一入口（三级 fallback 链）。
    优先级: Yahoo → 东财 push2 → 新浪财经。
    确保数据必须获取到，不容缺失。

    code: 5位数字，interval: 60m/30m/15m
    min_bars: 最少需要的K线根数（不足30根认为失败）

    Returns: [{"date", "open", "high", "low", "close", "volume"}, ...]
    """
    _interval_to_yahoo_range = {"60m": "2mo", "30m": "1mo", "15m": "15d"}
    _interval_to_sina_type = {"60m": 60, "30m": 30, "15m": 15}

    # ① Yahoo
    if interval in _interval_to_yahoo_range:
        try:
            kl = await stock_kline_yahoo_async(
                f"{int(code)}.HK",
                interval=interval,
                range_=_interval_to_yahoo_range[interval],
            )
            if kl and len(kl) >= min_bars:
                return kl
        except Exception:
            pass

    # ② 东财 push2
    try:
        kl = await hk_kline_eastmoney_async(code, interval=interval)
        if kl and len(kl) >= min_bars:
            return kl
    except Exception:
        pass

    # ③ 新浪财经
    if interval in _interval_to_sina_type:
        try:
            kl = await hk_kline_sina_minute_async(code, minute_type=_interval_to_sina_type[interval])
            if kl and len(kl) >= min_bars:
                return kl
        except Exception:
            pass

    # 降级：返回能拿到的任何数据（哪怕不足 min_bars）
    # 再次尝试所有源，不要求 min_bars
    try:
        kl = await stock_kline_yahoo_async(f"{int(code)}.HK", interval=interval, range_=_interval_to_yahoo_range.get(interval, "1mo"))
        if kl:
            return kl
    except Exception:
        pass
    try:
        kl = await hk_kline_eastmoney_async(code, interval=interval)
        if kl:
            return kl
    except Exception:
        pass
    try:
        kl = await hk_kline_sina_minute_async(code, minute_type=_interval_to_sina_type.get(interval, 60))
        if kl:
            return kl
    except Exception:
        pass

    return []


# ═════════════════════════════════════════════════
# TickFlow K线（免费免注册，A股+港股+美股，前复权）
# ═════════════════════════════════════════════════
# 官方 SDK: pip install tickflow
# 免费模式: TickFlow.free() — 无需 API Key，提供历史日K/周K/月K
# 完整服务: tickflow.org 注册获取 key，提供实时行情+分钟级K线

_kline_tickflow_session = None

async def _get_tickflow() -> "AsyncTickFlow":
    """懒初始化 TickFlow free session（抑制 TickFlow 输出的 banner）"""
    global _kline_tickflow_session
    if _kline_tickflow_session is None:
        from tickflow import AsyncTickFlow
        import os, sys, contextlib
        devnull = os.devnull
        with open(devnull, 'w') as fnull:
            with contextlib.redirect_stdout(fnull):
                _kline_tickflow_session = await AsyncTickFlow.free().__aenter__()
    return _kline_tickflow_session

async def close_tickflow():
    """关闭 TickFlow session"""
    global _kline_tickflow_session
    if _kline_tickflow_session is not None:
        await _kline_tickflow_session.__aexit__(None, None, None)
        _kline_tickflow_session = None

async def kline_tickflow_async(symbol: str, period: str = "1d", count: int = 365,
                               adjust: str = "forward") -> list[dict]:
    """
    TickFlow K线数据（免费免注册，无需 API Key）

    使用官方 Python SDK 的 free 模式，自动处理认证和重试。
    支持 A股、港股、美股的历史日K/周K/月K/季K/年K。

    参数:
        symbol:   标的代码，如 "600000.SH"、"03690.HK"、"AAPL.US"
        period:   K线周期 1d/1w/1M/1Q/1Y（注意: free 模式不支持分钟级）
        count:    返回条数，最大 10000
        adjust:   复权方式 "forward"/"backward"/"forward_additive"/"backward_additive"/"none"
                 默认 "forward" 前复权

    返回: [{"date", "open", "high", "low", "close", "volume"}, ...]
          格式与 stock_kline_yahoo_async / cn_stock_kline_tencent_async 一致

    文档: https://docs.tickflow.org
    """
    try:
        tf = await _get_tickflow()
        df = await tf.klines.get(symbol, period=period, count=count,
                                  adjust=adjust, as_dataframe=True)
    except Exception as e:
        print(f"[WARN] TickFlow K线失败({symbol}): {e}")
        return []

    if df is None or df.empty:
        return []

    result = []
    for _, row in df.iterrows():
        ts = row.get("timestamp", 0)
        if not isinstance(ts, (int, float)):
            continue
        dt = datetime.fromtimestamp(ts / 1000)
        result.append({
            "date": dt.strftime("%Y-%m-%d" if period in ("1d","1w","1M","1Q","1Y") else "%Y-%m-%d %H:%M"),
            "open": round(float(row.get("open", 0)), 2),
            "high": round(float(row.get("high", 0)), 2),
            "low": round(float(row.get("low", 0)), 2),
            "close": round(float(row.get("close", 0)), 2),
            "volume": int(row.get("volume", 0)),
        })
    return result


async def kline_tickflow_batch_async(symbols: list[str], period: str = "1d", count: int = 365,
                                      adjust: str = "forward") -> dict[str, list[dict]]:
    """
    TickFlow 批量K线（一次取多只标的，避免逐只触发频率限制）

    free 模式有 60 次/分钟的限制，批量请求只计 1 次。

    参数:
        symbols: 标的代码列表，如 ["03690.HK", "00700.HK", "AAPL.US"]
        period:  K线周期 1d/1w/1M/1Q/1Y
        count:   返回条数，最大 10000
        adjust:  复权方式

    返回: {symbol: [{"date","open","high","low","close","volume"}, ...], ...}
    """
    try:
        tf = await _get_tickflow()
        raw = await tf.klines.batch(symbols, period=period, count=count, adjust=adjust)
    except Exception as e:
        print(f"[WARN] TickFlow 批量K线失败: {e}")
        return {}

    if not isinstance(raw, dict):
        return {}

    out: dict[str, list[dict]] = {}
    for sym in symbols:
        data = raw.get(sym)
        if not isinstance(data, dict):
            continue
        timestamps = data.get("timestamp")
        opens = data.get("open")
        highs = data.get("high")
        lows = data.get("low")
        closes = data.get("close")
        volumes = data.get("volume")
        if not timestamps or not closes:
            continue
        n = min(len(timestamps), len(closes))
        rows = []
        for i in range(n):
            ts = timestamps[i]
            if not isinstance(ts, (int, float)):
                continue
            dt = datetime.fromtimestamp(ts / 1000)
            rows.append({
                "date": dt.strftime("%Y-%m-%d" if period in ("1d","1w","1M","1Q","1Y") else "%Y-%m-%d %H:%M"),
                "open": round(float(opens[i]) if opens and i < len(opens) else 0, 2),
                "high": round(float(highs[i]) if highs and i < len(highs) else 0, 2),
                "low": round(float(lows[i]) if lows and i < len(lows) else 0, 2),
                "close": round(float(closes[i]), 2),
                "volume": int(volumes[i]) if volumes and i < len(volumes) else 0,
            })
        if rows:
            out[sym] = rows
    return out


# mootdx A股K线（同步，TCP直连）
try:
    from mootdx.quotes import Quotes as _MootdxQuotes; _MOOTDX_OK = True
except ImportError: _MOOTDX_OK = False

def _tdx_client():
    if not _MOOTDX_OK: raise ImportError("mootdx 未安装: uv add mootdx")
    servers = [("119.147.212.81",7709),("180.153.18.170",7709),
               ("59.175.238.38",7709),("112.74.214.43",7709)]
    import socket
    for ip,port in servers:
        s=socket.socket(socket.AF_INET,socket.SOCK_STREAM); s.settimeout(1.5)
        try: s.connect((ip,port)); s.close(); return _MootdxQuotes.factory(market="std",server=(ip,port))
        except: s.close(); continue
    return _MootdxQuotes.factory(market="std")

def cn_stock_kline_tdx_sync(code:str,frequency:int=9,start:int=0,count:int=200) -> list[dict]:
    """A股K线（mootdx TCP）。frequency: 9=日线, 10=周, 11=月, 8=1分钟等"""
    try:
        client = _tdx_client(); df = client.bars(symbol=code,frequency=frequency,start=start,count=count)
        if df is None or df.empty: return []
        return [{"date":str(r.get("date",""))[:19],"open":round(float(r.get("open",0)),2),
                 "high":round(float(r.get("high",0)),2),"low":round(float(r.get("low",0)),2),
                 "close":round(float(r.get("close",0)),2),"volume":int(r.get("volume",0)),
                 "amount":round(float(r.get("amount",0)),2)} for _,r in df.iterrows()]
    except Exception as e:
        print(f"[WARN] mootdx K线失败({code}): {e}"); return []

def cn_financial_snapshot_sync(code:str) -> dict:
    """A股最新季报财务快照（mootdx）"""
    try:
        client = _tdx_client(); df = client.finance(symbol=code)
        if df is None or df.empty: return {}
        r = df.iloc[-1].to_dict()
        return {"eps":round(float(r.get("eps",0)),4),"total_equity":float(r.get("equity",0)),
                "revenue_total":float(r.get("revenue",0)),"net_profit":float(r.get("net_profit",0)),
                "roe_pct":round(float(r.get("roe",0))*100,2)}
    except Exception as e:
        print(f"[WARN] mootdx 财务快照失败({code}): {e}"); return {}

# ═════════════════════════════════════════════════
# L4-L11: 基本面 / 资金面 / 信号 / 工具 (Fundamental)
# ═════════════════════════════════════════════════

# L4 — 基本面
async def key_indicators_eastmoney_async(secucode:str, page_size:int=4) -> list[dict]:
    """关键财务指标（东财 GMAININDICATOR）。港股/美股。东财没有银行保险数据的会返回空列表"""
    market = "hk" if secucode.endswith(".HK") else "us"
    return await eastmoney_datacenter(
        f"RPT_{'HK' if market=='hk' else 'US'}F10_FN_GMAININDICATOR",
        filter_str=f'(SECUCODE="{secucode}")', page_size=page_size,
        sort_columns="REPORT_DATE", sort_types="-1")

async def hk_fundamentals_async(code: str) -> dict:
    """
    港股基本面统一入口（东财 → 腾讯78字段 → Yahoo统计 → Yahoo三表，四级fallback）

    返回:
        {"secucode": "03690.HK", "source": "eastmoney/tencent/yahoo", "latest": {...}, "error": None}
    latest 包含 ROE/GROSS_PROFIT_RATIO/DEBT_ASSET_RATIO/PE/营收增速/净利增速 等字段
    """
    secucode = f"{code}.HK" if not code.endswith(".HK") else code
    symbol = secucode.replace(".HK", "")

    # 1️⃣ 东财（最详细，有营收/净利/ROE/毛利率/负债率等）
    try:
        data = await key_indicators_eastmoney_async(secucode)
        if data and isinstance(data, list) and len(data) > 0:
            return {"secucode": secucode, "source": "eastmoney", "latest": data[0],
                    "history": data, "error": None}
    except Exception:
        pass

    # 2️⃣ 腾讯78字段（覆盖所有港股，含银行保险，有PE/ROE/毛利率/净利率/营收增速）
    try:
        q = await hk_stock_quote_tencent_async(symbol)
        if q and q.get("pe") and q["pe"] != 0:
            return {"secucode": secucode, "source": "tencent",
                    "latest": {
                        "PE": q.get("pe"), "PE_TTM": q.get("pe_ttm"),
                        "PB": q.get("pb"),
                        "ROE": q.get("roe"),
                        "GROSS_PROFIT_RATIO": q.get("gross_margin"),
                        "NET_PROFIT_RATIO": q.get("profit_margin"),
                        "OPERATE_INCOME_YOY": q.get("revenue_growth"),
                        "DEBT_ASSET_RATIO": q.get("debt_ratio"),
                        "DIVIDEND_YIELD": q.get("dividend_yield"),
                        "MARKET_CAP": q.get("market_cap_100m"),
                    }, "error": None}
    except Exception:
        pass

    # 3️⃣ Yahoo keyStatistics
    try:
        ydata = await key_statistics_async(secucode)
        if ydata and ydata.get("forward_pe") is not None:
            return {"secucode": secucode, "source": "yahoo_stats",
                    "latest": {"current_price": ydata.get("current_price"),
                               "forward_pe": ydata.get("forward_pe"),
                               "pb": ydata.get("price_to_book"),
                               "roe": ydata.get("return_on_equity"),
                               "revenue_growth": ydata.get("revenue_growth"),
                               "earnings_growth": ydata.get("earnings_growth"),
                               "total_revenue": ydata.get("total_revenue")},
                    "error": None}
    except Exception:
        pass

    # 4️⃣ Yahoo 三表计算
    try:
        fdata = await financial_statements_yahoo_async(secucode)
    except Exception:
        fdata = {}
    if fdata and fdata.get("income"):
        inc = fdata["income"][0] if fdata["income"] else {}
        bal = fdata["balance"][0] if fdata.get("balance") else {}
        rev = inc.get("totalRevenue", 0) or 0
        ni = inc.get("netIncome", 0) or 0
        gp = inc.get("grossProfit", 0) or 0
        te = bal.get("totalStockholderEquity", 0) or 0
        ta = bal.get("totalAssets", 0) or 0
        td = bal.get("totalLiabilities", 0) or 0
        return {"secucode": secucode, "source": "yahoo_financials",
                "latest": {
                    "OPERATE_INCOME": rev, "HOLDER_PROFIT": ni,
                    "GROSS_PROFIT_RATIO": round(gp / rev * 100, 2) if rev else 0,
                    "ROE": round(ni / te * 100, 2) if te else 0,
                    "DEBT_ASSET_RATIO": round(td / ta * 100, 2) if ta else 0,
                }, "error": None}

    return {"secucode": secucode, "source": None, "latest": {},
            "error": "所有数据源均失败"}
    try:
        fdata = await financial_statements_yahoo_async(secucode)
    except Exception:
        fdata = {}
    if fdata and fdata.get("income"):
        inc = fdata["income"][0] if fdata["income"] else {}
        bal = fdata["balance"][0] if fdata.get("balance") else {}
        rev = inc.get("totalRevenue", 0) or inc.get("TotalRevenue", 0) or 0
        ni = inc.get("netIncome", 0) or inc.get("NetIncome", 0) or 0
        gp = inc.get("grossProfit", 0) or inc.get("GrossProfit", 0) or 0
        te = bal.get("totalStockholderEquity", 0) or bal.get("TotalStockholderEquity", 0) or 0
        ta = bal.get("totalAssets", 0) or bal.get("TotalAssets", 0) or 0
        td = bal.get("totalLiabilities", 0) or bal.get("TotalLiabilities", 0) or 0
        return {"secucode": secucode, "source": "yahoo_financials",
                "latest": {
                    "OPERATE_INCOME": rev,
                    "HOLDER_PROFIT": ni,
                    "GROSS_PROFIT_RATIO": round(gp / rev * 100, 2) if rev else 0,
                    "ROE": round(ni / te * 100, 2) if te else 0,
                    "DEBT_ASSET_RATIO": round(td / ta * 100, 2) if ta else 0,
                    "NET_PROFIT_RATIO": round(ni / rev * 100, 2) if rev else 0,
                    "total_revenue": rev, "net_income": ni,
                    "total_equity": te, "total_assets": ta,
                },
                "error": None}

    return {"secucode": secucode, "source": None, "latest": {},
            "error": "所有数据源均失败"}

async def financial_statements_eastmoney_async(secucode:str, statement:str="balance", page_size:int=200) -> list[dict]:
    """财报三表（东财 datacenter）"""
    rmap = {"balance":{"us":"RPT_USF10_FN_BALANCE","hk":"RPT_HKF10_FN_BALANCE"},
            "income":{"us":"RPT_USF10_FN_INCOME","hk":"RPT_HKF10_FN_INCOME"},
            "cashflow":{"us":"RPT_USSK_FN_CASHFLOW","hk":"RPT_HKSK_FN_CASHFLOW"}}
    market = "hk" if secucode.endswith(".HK") else "us"
    return await eastmoney_datacenter(rmap[statement][market],
        filter_str=f'(SECUCODE="{secucode}")', page_size=page_size,
        sort_columns="REPORT_DATE", sort_types="-1")

async def key_statistics_async(symbol:str) -> dict:
    """Yahoo 关键指标（英文）"""
    data = await yahoo_quote_summary(symbol, ["financialData","defaultKeyStatistics","summaryDetail"])
    fd,ks,sd = data.get("financialData",{}),data.get("defaultKeyStatistics",{}),data.get("summaryDetail",{})
    def _v(d,k): v=d.get(k,{}); return v.get("raw") if isinstance(v,dict) else v
    return {"current_price":_v(fd,"currentPrice"),"target_mean":_v(fd,"targetMeanPrice"),
            "recommendation":fd.get("recommendationKey"),"trailing_pe":_v(sd,"trailingPE"),
            "forward_pe":_v(ks,"forwardPE"),"peg_ratio":_v(ks,"pegRatio"),
            "price_to_book":_v(ks,"priceToBook"),"enterprise_value":_v(ks,"enterpriseValue"),
            "profit_margins":_v(ks,"profitMargins"),"return_on_equity":_v(fd,"returnOnEquity"),
            "return_on_assets":_v(fd,"returnOnAssets"),"earnings_growth":_v(fd,"earningsGrowth"),
            "revenue_growth":_v(fd,"revenueGrowth"),"beta":_v(ks,"beta"),
            "dividend_yield":_v(sd,"dividendYield"),"market_cap":_v(sd,"marketCap"),
            "total_revenue":_v(fd,"totalRevenue"),"total_cash":_v(fd,"totalCash"),
            "total_debt":_v(fd,"totalDebt")}

async def cross_validate_hk_quote(code: str) -> dict:
    """港股关键数据多源交叉验证。

    从腾讯（主源）和东财/Yahoo（副源，通过 hk_fundamentals_async 四级fallback）获取数据对比。
    遵循 ai-berkshire financial-data.md 规范：
      - ≤1%: ✅ 一致
      - 1%~5%: ⚠️ 存在差异
      - >5%: ❌ 重大差异

    Args:
        code: 港股代码，如 "03690"

    Returns:
        {"code": str, "fields": [{"name": str, "primary": val, "secondary": val,
                                   "deviation_pct": float, "status": str}, ...],
         "summary": ...}
    """
    # 1️⃣ 主源：腾讯78字段
    primary = await hk_stock_quote_tencent_async(code)
    if not primary or not primary.get("pe"):
        return {"code": code, "fields": [], "summary": {"total": 0, "ok": 0, "warn": 0, "error": 0, "error_msg": "腾讯数据获取失败"}}

    # 2️⃣ 副源：东财/Yahoo（通过 hk_fundamentals_async 四级fallback）
    secondary_raw = {}
    try:
        sec_data = await hk_fundamentals_async(code)
        if sec_data and sec_data.get("latest"):
            secondary_raw = sec_data["latest"]
    except Exception:
        pass

    if not secondary_raw:
        return {"code": code, "fields": [], "summary": {"total": 0, "ok": 0, "warn": 0, "error": 0, "error_msg": "副源(Yahoo/东财)数据获取失败"}}

    # 3️⃣ 定义字段映射（只包含单位一致的字段：PE, PB, ROE, 股息率）
    # 毛利率和负债率在腾讯和东财间的单位不一致，跳过
    field_map = [
        ("PE", "pe", None),
        ("PB", "pb", None),
        ("股息率", "dividend_yield", None),
        ("ROE", "roe", None),
    ]

    def _safe_float(v):
        if v is None: return None
        try: return float(v)
        except (ValueError, TypeError): return None
        except: return None

    # 尝试从副源数据中匹配字段（多种命名规则）
    def _match_secondary(name):
        """尝试多种命名方式匹配副源字段"""
        key_map = {
            "PE": ["PE", "pe", "forward_pe", "trailing_pe", "PE_TTM"],
            "PB": ["PB", "pb", "price_to_book"],
            "ROE": ["ROE", "roe", "return_on_equity"],
            "股息率": ["DIVIDEND_YIELD", "dividend_yield", "dividendYield", "DPS_HKD"],
            "毛利率": ["GROSS_PROFIT_RATIO", "gross_profit_margin", "gross_margin"],
            "负债率": ["DEBT_ASSET_RATIO", "debt_ratio", "debt_to_equity"],
        }
        candidates = key_map.get(name, [])
        for c in candidates:
            v = secondary_raw.get(c)
            if v is not None:
                return _safe_float(v)
        return None

    fields = []
    for name, pk, _ in field_map:
        pv = _safe_float(primary.get(pk))
        sv = _match_secondary(name)
        if pv is None or sv is None or pv == 0:
            continue

        deviation = abs(pv - sv) / abs(pv) * 100
        if deviation <= 1.0:
            status = "✅"
        elif deviation <= 5.0:
            status = "⚠️"
        else:
            status = "❌"

        fields.append({
            "name": name,
            "primary": pv,
            "secondary": sv,
            "deviation_pct": round(deviation, 2),
            "status": status,
        })

    ok_count = sum(1 for f in fields if f["status"] == "✅")
    warn_count = sum(1 for f in fields if f["status"] == "⚠️")
    error_count = sum(1 for f in fields if f["status"] == "❌")

    return {
        "code": code,
        "fields": fields,
        "summary": {
            "total": len(fields),
            "ok": ok_count,
            "warn": warn_count,
            "error": error_count,
            "error_msg": "",
        },
    }


async def batch_cross_validate_hk(codes: list) -> list:
    """批量交叉验证"""
    tasks = [asyncio.create_task(cross_validate_hk_quote(c)) for c in codes]
    return await asyncio.gather(*tasks)


async def analyst_estimates_async(symbol:str) -> dict:
    data = await yahoo_quote_summary(symbol, ["earningsTrend","recommendationTrend","upgradeDowngradeHistory"])
    return {"eps_trend":[{"period":t.get("period"),"eps_estimate":t.get("earningsEstimate",{}).get("avg",{}).get("raw"),
                         "revenue_estimate":t.get("revenueEstimate",{}).get("avg",{}).get("raw"),
                         "num_analysts":t.get("earningsEstimate",{}).get("numberOfAnalysts",{}).get("raw")}
                        for t in data.get("earningsTrend",{}).get("trend",[])],
            "rating_trend":data.get("recommendationTrend",{}).get("trend",[])}

async def institutional_holders_async(symbol:str) -> dict:
    data = await yahoo_quote_summary(symbol, ["institutionOwnership","majorHoldersBreakdown"])
    mhb = data.get("majorHoldersBreakdown",{})
    def _v(d,k): v=d.get(k,{}); return v.get("raw") if isinstance(v,dict) else v
    overview = {"insiders_pct":_v(mhb,"insidersPercentHeld"),"institutions_pct":_v(mhb,"institutionsPercentHeld"),
                "institutions_float_pct":_v(mhb,"institutionsFloatPercentHeld"),"institutions_count":_v(mhb,"institutionsCount")}
    holders = [{"name":h.get("organization"),"shares":_v(h,"position"),"value":_v(h,"value"),"pct_held":_v(h,"pctHeld")}
               for h in data.get("institutionOwnership",{}).get("ownershipList",[])[:10]]
    return {"overview":overview,"top_holders":holders}

async def financial_statements_yahoo_async(symbol:str, quarterly:bool=False) -> dict:
    sfx = "Quarterly" if quarterly else ""
    data = await yahoo_quote_summary(symbol, [f"incomeStatementHistory{sfx}",f"balanceSheetHistory{sfx}",f"cashflowStatementHistory{sfx}"])
    def _ext(k):
        stmts = data.get(k,{}).get("incomeStatementHistory" if "income" in k else "balanceSheetStatements" if "balance" in k else "cashflowStatements",[])
        return [{k2:v["raw"] if isinstance(v,dict) and "raw" in v else v for k2,v in stmt.items()} for stmt in stmts]
    return {"income":_ext(f"incomeStatementHistory{sfx}"),"balance":_ext(f"balanceSheetHistory{sfx}"),"cashflow":_ext(f"cashflowStatementHistory{sfx}")}

def _normalize_cn_indicators(data: list[dict]) -> list[dict]:
    """将东财 datacenter RPT_LICO_FN_CPD 字段名映射为评分器可识别的标准化字段名。

    RPT_LICO_FN_CPD 使用中文拼音缩写（如 XSMLL=销货毛利率、SJLTZ=净利增长率），
    而 fb_score/meso_filter 期望英文字段名（GROSS_PROFIT_RATIO、HOLDER_PROFIT_YOY）。
    此函数建立映射，保留原始字段不覆盖已有值，并对小数位做合理裁剪。
    """
    FIELD_MAP = {
        "ROE": ("ROE", "WEIGHTAVG_ROE"),            # 加权净资产收益率
        "JQROE": ("JQROE", "WEIGHTAVG_ROE"),        # 同上
        "GROSS_PROFIT_RATIO": ("GROSS_PROFIT_RATIO", "XSMLL"),  # 销货毛利率
        "DEBT_ASSET_RATIO": ("DEBT_ASSET_RATIO", "YSHZ", "SJLHZ"),  # 资产利润率/净资产利润率
        "HOLDER_PROFIT_YOY": ("HOLDER_PROFIT_YOY", "SJLTZ"),     # 净利润增长率
    }
    PRECISION = {"ROE": 2, "JQROE": 2, "GROSS_PROFIT_RATIO": 2,
                 "DEBT_ASSET_RATIO": 2, "HOLDER_PROFIT_YOY": 2}
    result = []
    for record in data:
        n = dict(record)
        for target_key, sources in FIELD_MAP.items():
            if target_key in n:
                continue  # 已有值不覆盖
            for src in sources:
                if src in n and n[src] is not None:
                    v = n[src]
                    # 裁剪小数位（东财原始精度常为 10+ 位）
                    prec = PRECISION.get(target_key, 2)
                    if isinstance(v, float):
                        v = round(v, prec)
                    n[target_key] = v
                    break
        result.append(n)
    return result


async def cn_key_indicators_async(code:str, page_size:int=4) -> list[dict]:
    """A股关键财务指标（东财）。SECUCODE 格式: 600519.SH（交易所后缀在后）"""
    secucode = f"{code}.{'SH' if code.startswith(('6','9')) else 'SZ'}"
    data = await eastmoney_datacenter("RPT_LICO_FN_CPD", filter_str=f'(SECUCODE="{secucode}")',
                                      page_size=page_size, sort_columns="REPORTDATE", sort_types="-1")
    return _normalize_cn_indicators(data)


async def cn_key_indicators_fallback(code: str) -> list[dict]:
    """A股基本面统一入口（东财 datacenter → Yahoo keyStatistics → mootdx 同步快照）。

    返回与 cn_key_indicators_async 兼容的 list[dict] 格式。
    当东财 datacenter 因限流/宕机返回空数据时，自动降级到备选源。
    """
    # 注: SECUCODE 格式为 600519.SH（交易所后缀在后）
    secucode = f"{code}.{'SH' if code.startswith(('6','9')) else 'SZ'}"

    # 1. 东财 datacenter（主推，字段最全：营收增速/净利同比/ROE/毛利率/负债率）
    data = await eastmoney_datacenter("RPT_LICO_FN_CPD",
        filter_str=f'(SECUCODE="{secucode}")', page_size=4,
        sort_columns="REPORTDATE", sort_types="-1")
    if data:
        _record_source("cn_indicator_eastmoney", True)
        return _normalize_cn_indicators(data)
    _record_source("cn_indicator_eastmoney", False)

    # 2. Yahoo keyStatistics（备选，字段：PE/市值/营收/毛利率/ROE）
    try:
        ks = await yahoo_quote_summary(f"{secucode}", ["keyStatistics"])
        if ks and ks.get("defaultKeyStatistics"):
            _record_source("cn_indicator_yahoo", True)
            return [ks["defaultKeyStatistics"]]
        _record_source("cn_indicator_yahoo", False)
    except Exception as e:
        _record_source("cn_indicator_yahoo", False)
        print(f"[WARN] Yahoo基本面失败({code}): {e}")

    # 3. mootdx 同步快照（最后兜底：EPS/ROE/净利润/营收）
    #    注意：mootdx 是 TCP 同步调用，必须在线程池执行避免阻塞 event loop
    try:
        loop = asyncio.get_running_loop()
        snap = await loop.run_in_executor(None, lambda: cn_financial_snapshot_sync(code))
        if snap:
            _record_source("cn_indicator_mootdx", True)
            return [snap]
        _record_source("cn_indicator_mootdx", False)
    except Exception as e:
        _record_source("cn_indicator_mootdx", False)
        print(f"[WARN] mootdx快照失败({code}): {e}")

    return []

async def cn_financial_statements_sina_async(code:str, report_type:str="lrb", num:int=8) -> list[dict]:
    """A股三表（新浪）。lrb=利润表, fzb=资产负债表, llb=现金流量表"""
    d = await _get_json("https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketData.getKLineData", params={
        "symbol":cn_market_prefix(code)+code,"scale":num,"datalen":1,"type":report_type},
        headers={"Referer":"https://vip.stock.finance.sina.com.cn/"})
    return d if isinstance(d,list) else []

def cn_eps_forecast_sync(code:str) -> list[dict]:
    """机构一致预期EPS（同花顺）"""
    import requests
    try:
        html = requests.get(f"https://basic.10jqka.com.cn/{code}/index.html",
                            headers={"User-Agent":UA}, timeout=10).text
        m = re.search(r'var\s+resData\s*=\s*({.+?});', html, re.DOTALL)
        if not m: return []
        data = json.loads(m.group(1))
        eps = data.get("eps",data.get("EPS",{}))
        items = eps.get("data",eps.get("items",eps.get("list",[]))) if isinstance(eps,dict) else []
        if isinstance(items,dict): items = list(items.values())
        return [{"year":str(i.get("year",i.get("reportDate","")))[:4],"eps":float(i.get("val",i.get("eps",0))),
                 "count":int(i.get("count",i.get("num",0)))} for i in items[:5] if isinstance(i,dict)]
    except Exception as e:
        print(f"[WARN] 一致预期EPS失败({code}): {e}"); return []

# L5 — 资金面
async def fund_flow_daily_async(ticker_or_code:str, secid_prefix:int=105, limit:int=100) -> list[dict]:
    """获取个股日度资金流向。

    A股使用 daykline/get 端点，港股(secid_prefix=116)使用 kline/get 端点（daykline/get对港股返回空）。
    东财 fflow/kline/get 对部分港股覆盖不全，有数据的返回主力资金净流入，无数据的返回空数组。
    """
    import json as _json
    s = await get_async_session()

    # 港股走 kline/get（daykline/get 对港股返回空数据）
    urls = ["https://push2.eastmoney.com/api/qt/stock/fflow/kline/get",
            "https://push2.eastmoney.com/api/qt/stock/fflow/daykline/get"]
    if secid_prefix == 116:
        urls = urls  # kline/get 优先
    else:
        urls = list(reversed(urls))  # daykline/get 优先（A股）

    for attempt in range(3):
        for url in urls:
            try:
                async with s.get(url, params={
                    "secid":f"{secid_prefix}.{ticker_or_code}","klt":101,
                    "fields1":"f1,f2,f3,f7","fields2":"f51,f52,f53,f54,f55,f56,f57","lmt":limit},
                    headers={"Referer":"https://quote.eastmoney.com/"}) as r:
                    text = await r.text()
                    d = (_json.loads(text) if text else {}).get("data")
                if d and d.get("klines"):
                    break
            except aiohttp.ServerDisconnectedError:
                # 东财 fflow 端点高并发下经常触发 ServerDisconnectedError
                # 尝试关闭旧会话后重试（下次 _fetch 会通过 get_async_session 重建会话）
                s2 = await get_async_session()
                if s2.closed:
                    await close_async_session()
                continue
            except Exception:
                continue
        else:
            if attempt < 2:
                import asyncio
                await asyncio.sleep(1 + attempt * 2)
                continue
            return []
        break  # 成功获取数据，跳出外层循环
    if not d or not d.get("klines"): return []
    return [{"date":p[0],"main_net":float(p[1]),"small_net":float(p[2]),"mid_net":float(p[3]),
             "big_net":float(p[4]),"super_big_net":float(p[5]),
             "main_pct":float(p[6]) if len(p)>6 and p[6] else 0} for p in [l.split(",") for l in d["klines"]]]

async def cn_fund_flow_minute_async(code:str) -> list[dict]:
    """A股分钟级资金流向"""
    return await fund_flow_daily_async(code, secid_prefix=int(cn_secid(code).split(".")[0]), limit=200)

async def cn_margin_trading_async(code:str, page_size:int=30) -> list[dict]:
    """融资融券"""
    market = "SH" if code.startswith(("6","9")) else "SZ"
    return await eastmoney_datacenter("RPTA_WEB_MARGINTRADING_DETAILS",
        filter_str=f'(SECURITY_CODE="{code}")(TRADE_MARKET_CODE="{market}")',
        page_size=page_size, sort_columns="TRADE_DATE", sort_types="-1")

async def cn_block_trade_async(code:str, page_size:int=20) -> list[dict]:
    market="SH" if code.startswith(("6","9")) else "SZ"
    return await eastmoney_datacenter("RPT_DATA_BLOCKTRADE",
        filter_str=f'(SECURITY_CODE="{code}")(MARKET="{market}")',
        page_size=page_size, sort_columns="TRADE_DATE", sort_types="-1")

async def cn_holder_num_change_async(code:str, page_size:int=10) -> list[dict]:
    market="SH" if code.startswith(("6","9")) else "SZ"
    return await eastmoney_datacenter("RPTA_WEB_HOLDERNUM_CHANGE",
        filter_str=f'(SECUCODE="{market}{code}")', page_size=page_size,
        sort_columns="END_DATE", sort_types="-1")

async def cn_dividend_history_async(code:str, page_size:int=20) -> list[dict]:
    market="SH" if code.startswith(("6","9")) else "SZ"
    return await eastmoney_datacenter("RPTA_WEB_DIVIDEND_HISTORY",
        filter_str=f'(SECUCODE="{market}{code}")', page_size=page_size,
        sort_columns="REPORT_DATE", sort_types="-1")

# L6 — A股信号
async def ths_hot_stocks_async(date:str=None) -> list[dict]:
    """当日强势股+题材归因（同花顺）"""
    if not date:
        date = datetime.now().strftime("%Y%m%d")
    try:
        s = await get_async_session()
        async with s.get("https://data.10jqka.com.cn/dataapi/limit_up/limit_up_pool", params={
            "page":1,"limit":200,"field":"199112,10,9001,330323,330324,330325,9002,330329,133971,133970,1968584,3475914,9003,9004",
            "filter":"HS,GEM2STAR","order_field":"330324","order_type":"0","date":date}) as r:
            info = (await r.json()).get("data",{}).get("info",[])
    except Exception as e:
        print(f"[WARN] 同花顺强势股失败: {e}"); return []
    return [{"code":i.get("code"),"name":i.get("name"),"price":i.get("latest"),
             "pct":i.get("change_rate"),"reason":i.get("reason_type",""),"high_days":i.get("high_days","")}
            for i in info]

async def northbound_flow_async() -> dict:
    """北向资金分钟级流向"""
    try:
        s = await get_async_session()
        async with s.get("https://push2.eastmoney.com/api/qt/ulist.np/get", params={
            "fields":"f62,f184,f66,f69,f72,f75,f78,f81,f84,f87,f204,f205,f124",
            "secids":"1.000001,0.399001"}, headers={"Referer":"https://quote.eastmoney.com/"}) as r:
            d = await r.json()
        diff = (d.get("data") or {}).get("diff") or []
        if isinstance(diff,dict): diff = list(diff.values())
        sh,sz = 0.0,0.0
        for i in diff:
            c=str(i.get("f12",""))
            if c=="000001": sh=(i.get("f62") or 0)/100
            elif c=="399001": sz=(i.get("f62") or 0)/100
        return {"sh_net":round(sh,2),"sz_net":round(sz,2),"total":round(sh+sz,2)}
    except: return {}

async def cn_concept_blocks_async(code:str) -> dict:
    """个股所属板块（行业/概念/地域）"""
    try:
        s = await get_async_session()
        async with s.get("https://push2.eastmoney.com/api/qt/slist/get", params={
            "spt":3,"secids":cn_secid(code),"fields":"f12,f14,f3,f4"},
            headers={"Referer":"https://quote.eastmoney.com/"}) as r:
            d = await r.json()
        diff = (d.get("data") or {}).get("diff") or []
        if isinstance(diff,dict): diff = list(diff.values())
        industry,concepts,region = "",[],""
        for i in diff:
            bk=str(i.get("f12","")); name=i.get("f14","")
            if bk.startswith("BK"):
                if bk.startswith("BK08") and not industry: industry=name
                elif bk.startswith("BK09"): region=name
                else: concepts.append(name)
        return {"industry":industry,"concept_tags":concepts[:20],"region":region}
    except: return {}

async def cn_dragon_tiger_board_async(code:str, look_back:int=30) -> list[dict]:
    """龙虎榜"""
    return await eastmoney_datacenter("RPTA_WEB_DRAGON_TIGER_LIST",
        filter_str=f'(SECURITY_CODE="{code}")', page_size=look_back,
        sort_columns="TRADE_DATE", sort_types="-1")

async def cn_lockup_expiry_async(code:str, forward_days:int=90) -> list[dict]:
    """限售解禁"""
    return await eastmoney_datacenter("RPTA_WEB_LOCKUP_EXPIRY",
        filter_str=f'(SECURITY_CODE="{code}")', page_size=forward_days,
        sort_columns="EXPIRE_DATE", sort_types="1")

async def cn_industry_ranking_async(top_n:int=20) -> list[dict]:
    """行业板块涨跌排名"""
    try:
        s = await get_async_session()
        async with s.get("https://push2.eastmoney.com/api/qt/clist/get", params={
            "fs":"m:90+t:2","fields":"f2,f3,f4,f5,f6,f12,f14","pn":1,"pz":top_n,"fid":"f3","po":1}) as r:
            d = await r.json()
        diff = (d.get("data") or {}).get("diff") or []
        if isinstance(diff,dict): diff = list(diff.values())
        return [{"industry":i.get("f14"),"pct":round((i.get("f3") or 0)/100,2),
                 "up":i.get("f4"),"down":i.get("f5")} for i in diff if i.get("f14")]
    except Exception as e:
        print(f"[WARN] 行业排名失败: {e}"); return []

async def hk_industry_ranking_async(top_n:int=20) -> list[dict]:
    """港股行业板块涨跌排名（东财 push2, fs=m:0+t:3 表示港股板块）"""
    try:
        s = await get_async_session()
        async with s.get("https://push2.eastmoney.com/api/qt/clist/get", params={
            "fs":"m:0+t:3","fields":"f2,f3,f4,f5,f6,f12,f14","pn":1,"pz":top_n,"fid":"f3","po":1},
            headers={"Referer":"https://quote.eastmoney.com/"}) as r:
            d = await r.json()
        diff = (d.get("data") or {}).get("diff") or []
        if isinstance(diff,dict): diff = list(diff.values())
        return [{"industry":i.get("f14"),"pct":round((i.get("f3") or 0)/100,2),
                 "up":i.get("f4"),"down":i.get("f5")} for i in diff if i.get("f14")]
    except Exception as e:
        print(f"[WARN] 港股行业排名失败: {e}"); return []

# L8 — 公告
async def cninfo_announcements_async(code:str, page_size:int=30) -> list[dict]:
    """A股公告检索（巨潮 cninfo）"""
    try:
        async with aiohttp.ClientSession(headers={"User-Agent":UA}) as sess:
            async with sess.post("http://www.cninfo.com.cn/new/fulltextSearch/full", data={
                "searchkey":code,"sdate":"","edate":"","isfulltext":"false",
                "sortName":"pubdate","sortType":"desc","pageNum":1}) as r:
                data = await r.json()
        results = data.get("announcements",[]) if isinstance(data,dict) else []
        return [{"date":r.get("announcementDate",""),"title":r.get("announcementTitle",""),
                 "type":r.get("announcementTypeName",""),"url":r.get("adjunctUrl","")}
                for r in results[:page_size]]
    except: return []

# L9 — 期权（仅美股）
async def options_chain_async(symbol:str, expiration:int=None) -> dict:
    s,crumb = await _get_yahoo()
    params = {"crumb":crumb}
    if expiration: params["date"] = expiration
    async with s.get(f"https://query2.finance.yahoo.com/v7/finance/options/{symbol}", params=params) as r:
        oc = (await r.json()).get("optionChain",{}).get("result",[{}])[0]
    opts = oc.get("options",[{}])[0] if oc.get("options") else {}
    def _po(os):
        def _v(k): v=o.get(k,{}); return v.get("raw") if isinstance(v,dict) else v
        return [{"strike":_v("strike"),"last_price":_v("lastPrice"),"bid":_v("bid"),
                 "ask":_v("ask"),"volume":_v("volume"),"open_interest":_v("openInterest"),
                 "implied_volatility":_v("impliedVolatility"),"in_the_money":o.get("inTheMoney")}
                for o in os]
    return {"expiration_dates":oc.get("expirationDates",[]),"calls":_po(opts.get("calls",[])),
            "puts":_po(opts.get("puts",[])),"underlying_price":oc.get("quote",{}).get("regularMarketPrice")}

# L10 — SEC Filing（仅美股）
async def sec_filings_async(cik:str, form_type:str=None) -> dict:
    async with aiohttp.ClientSession(headers={"User-Agent":"global-stock-data/2.0"}) as sess:
        async with sess.get(f"https://data.sec.gov/submissions/CIK{cik}.json") as r:
            data = await r.json()
    recent = data.get("filings",{}).get("recent",{})
    filings = []
    for i in range(len(recent.get("form",[]))):
        if form_type and recent["form"][i]!=form_type: continue
        filings.append({"form":recent["form"][i],"date":recent["filingDate"][i],
                        "accession_number":recent["accessionNumber"][i]})
    return {"company_name":data.get("name"),"cik":cik,"filings":filings[:50]}

async def sec_xbrl_facts_async(cik:str, metrics:list[str]=None) -> dict:
    async with aiohttp.ClientSession(headers={"User-Agent":"global-stock-data/2.0"}) as sess:
        async with sess.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json") as r:
            facts = await r.json()
    us_gaap = facts.get("facts",{}).get("us-gaap",{})
    if not metrics:
        return {"company":facts.get("entityName"),"total_metrics":len(us_gaap),
                "available_metrics":[{"name":k,"label":v.get("label")} for k,v in us_gaap.items()]}
    result = {}
    for mn in metrics:
        m = us_gaap.get(mn,{})
        if not m: result[mn]=[]; continue
        unit_key = "USD" if "USD" in m.get("units",{}) else (list(m["units"].keys())[0] if m.get("units") else None)
        if not unit_key: result[mn]=[]; continue
        result[mn] = [{"end":e.get("end"),"val":e.get("val"),"form":e.get("form")}
                      for e in m["units"][unit_key] if e.get("form") in ("10-K","10-Q")][-20:]
    return {"company":facts.get("entityName"),"metrics":result}

# ── Layer 7: 新闻层 ──────────────────────────

async def jin10_flash_async(count: int = 20) -> list[dict]:
    """金十数据快讯（API可能不可达，保留接口备用）"""
    try:
        d = await _get_json("https://flash-api.jin10.com/get_flash_list",
                             params={"channel":"-8200","vip":"1","max_time":"0"})
        return [{"time":i.get("time",""),"content":i.get("content",""),"title":i.get("title","")}
                for i in (d.get("data") or [])[:count]]
    except:
        return []

async def wallstreetcn_flash_async(channel: str = "global-channel", count: int = 20) -> list[dict]:
    """华尔街见闻快讯。
    channel: global-channel(全球/宏观) / us-stock-channel(美股) / a-stock-channel(A股)
             forex-channel(外汇) / goldc-channel(黄金) / oil-channel(原油)"""
    d = await _get_json("https://api-one.wallstcn.com/apiv1/content/lives",
                         params={"channel":channel,"limit":count})
    items = d.get("data",{}).get("items",[])
    return [{"title":i.get("title","").strip(),
             "content":(i.get("content_text") or "").strip(),
             "time":i.get("display_time",i.get("created_at","")),
             "channels":i.get("channels",[]),
             "author":i.get("author",{}).get("display_name","") if i.get("author") else ""}
            for i in items]

async def stock_news_sentiment_async(code: str, name: str = "") -> dict:
    """个股新闻热度检测（基于Yahoo搜索）"""
    try:
        news = await stock_news(f"{code} {name}".strip(), count=5)
        return {"news_count":len(news),"recent_titles":[n.get("title","") for n in news]}
    except:
        return {"news_count":0,"recent_titles":[]}

async def batch_hk_capital_flow_async(codes: list[str]) -> dict[str, float]:
    """并行获取港股主力资金净流入。返回 {code: main_net_inflow (元)}"""
    async def _fetch(code):
        try:
            d = await fund_flow_daily_async(code, secid_prefix=116, limit=1)
            if d:
                return code, d[-1].get("main_net", 0.0)
        except:
            pass
        return code, 0.0
    funcs = [lambda c=code: _fetch(c) for code in codes]
    results = await parallel_map(funcs, max_concurrency=20)
    return {c: v for c, v in results if isinstance(v, (int, float))}


async def batch_hk_capital_flow_20d_async(codes: list[str]) -> dict[str, dict]:
    """并行获取港股 20 日累计主力资金流向。

    返回 {code: {"cumulative": 累计净流入, "avg": 日均净流入,
                  "positive_days": 正流入天数, "total_days": 实际返回天数}}
    """
    async def _fetch(code):
        try:
            d = await fund_flow_daily_async(code, secid_prefix=116, limit=20)
            if d and len(d) >= 2:
                cum = sum(item.get("main_net", 0.0) for item in d)
                avg = cum / len(d)
                pos_days = sum(1 for item in d if item.get("main_net", 0.0) > 0)
                return code, {
                    "cumulative": cum, "avg": avg,
                    "positive_days": pos_days, "total_days": len(d),
                }
        except:
            pass
        return code, {"cumulative": 0.0, "avg": 0.0, "positive_days": 0, "total_days": 0}
    funcs = [lambda c=code: _fetch(c) for code in codes]
    results = await parallel_map(funcs, max_concurrency=20)
    return {c: v for c, v in results if isinstance(v, dict)}
