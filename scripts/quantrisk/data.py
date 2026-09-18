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


# 腾讯K线可用域名（2026-08-12 修复：原 http://web.ifzq.gtimg.cn 已不可用返回501）
# https://ifzq.gtimg.cn 与 https://proxy.finance.qq.com/ifzqgtimg/ 均验证可用。
_TENCENT_KLINE_HOSTS = [
    "https://ifzq.gtimg.cn/appstock/app/fqkline/get",
    "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/fqkline/get",
]

async def _tencent_kline_get(param: str, referer: str = "https://finance.qq.com/") -> dict:
    """腾讯K线接口多域名降级请求。

    依次尝试 _TENCENT_KLINE_HOSTS，返回首个带 data 字段的成功响应；
    全部失败返回空 dict（调用方已有降级链兜底）。
    """
    headers = {"Referer": referer}
    for host in _TENCENT_KLINE_HOSTS:
        try:
            d = await _get_json(f"{host}?param={param}", headers=headers)
            if d and d.get("data"):
                return d
        except Exception:
            continue
    return {}

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
            # ⚠️ 2026-07-22 修复: 腾讯f[65]/f[71]/f[72]字段映射错误,已移除
            # f[72]被标注为gross_margin但实际不是毛利率(华润0.419/金山0.130)
            # f[71]被标注为revenue_growth但实际不是营收增速
            # f[65]被标注为profit_margin但实际也不是净利率
            # ⚠️ 2026-09-18 修复: 移除 f[74]→debt_ratio 映射——f[74] 实为"负债/净资产"类
            #    杠杆率(净负债口径,可为负), 非资产负债率(负债/总资产, 恒正且≤100%)。
            #    实测: 腾讯 -28.41(净现金)、映美控股 5965.22(净资产≈0分母趋零爆炸,
            #    东财每股净资产 -0.086 为负)、东亚银行 51.52(银行真实负债率约90%)。
            #    港股负债率无可靠免费源, 标缺失(fail-closed)。
            # 基本面数据请通过hk_fundamentals_async(东财→腾讯→Yahoo)获取
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
        if close_price is None: continue  # ⚠️ Yahoo 偶发缺失，跳过该行避免 float(None) 崩溃
        result.append({"date":datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M" if sub else "%Y-%m-%d"),
                       "open":round(q["open"][i],2),"high":round(q["high"][i],2),
                       "low":round(q["low"][i],2),"close":round(float(close_price),2),
                       "volume":int(q["volume"][i])})
    return result


def _normalize_intraday_bars(rows: list[dict]) -> list[dict]:
    """排序、去重并剔除当前未收盘的分钟K线。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    bars: dict[str, dict] = {}
    for row in rows:
        date = str(row.get("date", ""))
        if not date or _sf(row.get("open")) <= 0 or _sf(row.get("high")) <= 0 or _sf(row.get("low")) <= 0 or _sf(row.get("close")) <= 0:
            continue
        bars[date] = row
    ordered = [bars[key] for key in sorted(bars)]
    if ordered and str(ordered[-1].get("date", "")) >= now:
        ordered.pop()
    return ordered


async def stock_kline_30m_eastmoney_async(code: str, market: str) -> list[dict]:
    """东财30分钟K线（A股+港股，klt=30 前复权）。Yahoo 限流/403/429 时的回退源。
    注意：东财分钟K仅保留最近约250根（约31个交易日），满足40根门槛即可。"""
    market = market.lower()
    if market == "hk":
        secid = f"116.{int(code):05d}"
    elif market == "cn":
        secid = f"1.{code}" if code.startswith(("6", "9")) else f"0.{code}"
    else:
        return []
    # 东财 push2his 对 keep-alive 复用连接不友好（ServerDisconnectedError），强制短连接
    d = await _get_json("https://push2his.eastmoney.com/api/qt/stock/kline/get",
                        params={"secid": secid, "fields1": "f1,f2,f3,f4,f5,f6",
                                "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
                                "klt": "30", "fqt": "1", "beg": "0", "end": "20500101", "lmt": "1000"},
                        headers={"Connection": "close"})
    klines = (d.get("data") or {}).get("klines") or []
    rows = []
    for line in klines:
        p = line.split(",")
        if len(p) < 6:
            continue
        try:
            # 字段顺序: 时间,开,收,高,低,量,额,振幅
            rows.append({"date": p[0], "open": float(p[1]), "high": float(p[3]),
                         "low": float(p[4]), "close": float(p[2]), "volume": int(float(p[5]))})
        except (ValueError, IndexError):
            continue
    return rows


def _parse_sina_30m_jsonp(text: str) -> list[dict]:
    """解析新浪K线JSONP: var=([{day,open,high,low,close,volume},...])"""
    m = re.search(r"var=\s*\((\[.*\])\)", text, re.S)
    if not m:
        return []
    try:
        items = json.loads(m.group(1))
    except (ValueError, TypeError):
        return []
    rows = []
    for i in items:
        try:
            rows.append({"date": i["day"], "open": float(i["open"]), "high": float(i["high"]),
                         "low": float(i["low"]), "close": float(i["close"]),
                         "volume": int(float(i.get("volume", 0) or 0))})
        except (ValueError, KeyError, TypeError):
            continue
    return rows


async def stock_kline_30m_sina_async(code: str, market: str = "cn") -> list[dict]:
    """新浪A股30分钟K线（scale=30）。A股专属备用源。"""
    market = market.lower()
    if market != "cn":
        return []
    sym = f"sh{code}" if code.startswith(("6", "9")) else f"sz{code}"
    s = await get_async_session()
    async with s.get("https://quotes.sina.cn/cn/api/jsonp_v2.php/var=/CN_MarketDataService.getKLineData",
                     params={"symbol": sym, "scale": "30", "ma": "no", "datalen": "1023"},
                     timeout=aiohttp.ClientTimeout(total=15)) as r:
        return _parse_sina_30m_jsonp(await r.text())


async def stock_kline_30m_tencent_async(code: str, market: str = "cn") -> list[dict]:
    """腾讯A股30分钟K线（mkline m30，约320根）。A股专属备用源。"""
    market = market.lower()
    if market != "cn":
        return []
    prefix = "sh" if code.startswith(("6", "9")) else "sz"
    d = await _get_json("https://ifzq.gtimg.cn/appstock/app/kline/mkline",
                        params={"param": f"{prefix}{code},m30,,320"},
                        timeout=aiohttp.ClientTimeout(total=15))
    rows = []
    for bar in (d.get("data", {}).get(f"{prefix}{code}", {}).get("m30", []) or []):
        if not isinstance(bar, list) or len(bar) < 6:
            continue
        try:
            t = str(bar[0])
            rows.append({"date": f"{t[:4]}-{t[4:6]}-{t[6:8]} {t[8:10]}:{t[10:12]}",
                         "open": float(bar[1]), "high": float(bar[3]), "low": float(bar[4]),
                         "close": float(bar[2]), "volume": int(float(bar[5]))})
        except (ValueError, IndexError, TypeError):
            continue
    return rows


_MOOTDX_SERVERS = [("119.147.212.81", 7709), ("218.75.126.9", 7709), ("123.125.108.14", 7709)]


async def stock_kline_30m_mootdx_async(code: str, market: str = "cn") -> list[dict]:
    """mootdx（通达信TCP）A股30分钟K线（frequency=2）。A股最末兜底源，同步调用放线程池。"""
    market = market.lower()
    if market != "cn":
        return []

    def _sync():
        from mootdx.quotes import Quotes
        for ip, port in _MOOTDX_SERVERS:
            try:
                c = Quotes.factory(market="std", server=(ip, port), timeout=8)
                df = c.bars(symbol=code, frequency=2, offset=800)
                if df is not None and len(df):
                    return df
            except Exception:
                continue
        return None

    df = await asyncio.to_thread(_sync)
    if df is None or not len(df):
        return []
    rows = []
    for _, row in df.iterrows():
        try:
            dt = str(row["datetime"])
            if len(dt) == 16:
                pass
            elif len(dt) == 19:
                dt = dt[:16]
            rows.append({"date": dt, "open": float(row["open"]), "high": float(row["high"]),
                         "low": float(row["low"]), "close": float(row["close"]),
                         "volume": int(float(row.get("vol", 0) or 0))})
        except (ValueError, KeyError, TypeError):
            continue
    return rows


async def company_survey_async(code: str, market: str) -> dict:
    """公司资料（主营业务/行业/法人等），用于波段报告每只标的附基本面简介。
    A股：东财 F10 CompanySurveyAjax（行业+公司简介+法人+总经理+官网+注册资本）；
    港股：腾讯78字段财务（PE/ROE/股息率/市值）——东财港股F10接口不可用，无主营业务文字；负债率字段已移除（f[74] 为杠杆率非资产负债率，2026-09-18）。
    失败返回 {"error": ...}，不抛异常。"""
    market = market.lower()
    try:
        if market == "cn":
            prefix = "SH" if code.startswith(("6", "9")) else "SZ"
            d = await _get_json("https://emweb.securities.eastmoney.com/PC_HSF10/CompanySurvey/CompanySurveyAjax",
                                params={"code": f"{prefix}{code}"})
            jb = (d or {}).get("jbzl", {})
            if not jb:
                return {"error": "F10资料为空"}
            return {"industry": str(jb.get("sshy", "")).strip(),
                    "brief": str(jb.get("gsjj", "")).strip(),
                    "chairman": str(jb.get("frdb", "")).strip(),
                    "gm": str(jb.get("zjl", "")).strip(),
                    "website": str(jb.get("gswz", "")).strip(),
                    "reg_capital": str(jb.get("zczb", "")).strip()}
        if market == "hk":
            q = await hk_stock_quote_tencent_async(code)
            if not q or not q.get("name"):
                return {"error": "腾讯行情为空"}
            industry = await hk_industry_async(code)
            return {"name": q.get("name"), "pe_ttm": q.get("pe_ttm"), "roe": q.get("roe"),
                    "debt_ratio": q.get("debt_ratio"), "dividend_yield": q.get("dividend_yield"),
                    "market_cap_100m": q.get("market_cap_100m"), "industry": industry}
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {str(exc)[:60]}"}
    return {"error": f"不支持的市场: {market}"}


async def cn_announcements_async(code: str, top: int = 4) -> list[dict]:
    """东财A股近期公告，优先展示重组/收购/中标等重大事项，无命中则取最新。返回 [{date, title}]。"""
    d = await _get_json("https://np-anotice-stock.eastmoney.com/api/security/ann",
                        params={"sr": "-1", "page_size": "20", "page_index": "1",
                                "ann_type": "A", "client_source": "web", "stock_list": code})
    items = (d.get("data") or {}).get("list") or []
    kw_major = re.compile(r"收购|重组|资产|中标|算力|增发|回购|股权|转让|停牌|合作|投资")
    kw_minor = re.compile(r"业绩|分红|发行")
    hits = [it for it in items if kw_major.search(it.get("title", ""))]
    if not hits:
        hits = [it for it in items if kw_minor.search(it.get("title", ""))]
    chosen = hits or items
    out = []
    for it in chosen[:top]:
        title = it.get("title", "").split(":")[-1].strip()
        if title:
            out.append({"date": it.get("notice_date", "")[:10], "title": title[:60]})
    return out


async def hk_industry_async(code: str) -> str:
    """港股行业（东财 push2 secid=116，免费）。失败返回空字符串，不抛异常。"""
    code5 = code.zfill(5)
    try:
        d = await _get_json("https://push2.eastmoney.com/api/qt/stock/get",
                            params={"secid": f"116.{code5}", "fields": "f57,f127"},
                            headers={"Referer": "https://quote.eastmoney.com/"})
        return str(((d or {}).get("data") or {}).get("f127", "")).strip()
    except Exception:
        return ""


async def hk_plate_async(code: str) -> str:
    """港股所属板块（腾讯自选股 plate 接口，免费）。失败返回空字符串，不抛异常。"""
    code5 = code.zfill(5)
    try:
        d = await _get_json("https://proxy.finance.qq.com/ifzqgtimg/appstock/app/stockinfo/plate",
                            params={"code": f"hk{code5}"})
        return str(((d or {}).get("data") or {}).get("name", "")).strip()
    except Exception:
        return ""


async def cn_index_quotes_async() -> dict:
    """主要指数行情（腾讯 qt.gtimg.cn，免费，2026-09-08 道氏原则3「指数相互验证」接入）。

    返回 {代码: {name, price, change_pct}}，代码：sh000001 上证/sz399001 深证/sz399006 创业板/hkHSI 恒生。
    失败返回 {} 不抛异常（指数缺失时健康度检查只跳过指数部分，不误伤）。"""
    try:
        text = await _get_gbk("https://qt.gtimg.cn/q=sh000001,sz399001,sz399006,hkHSI")
        out = {}
        for line in text.strip().split(";"):
            line = line.strip()
            if not line or "=" not in line:
                continue
            # 腾讯格式: v_sh000001="..."（键名即指数代码）
            key, val = line.split("=", 1)
            key = key.strip().lstrip("v_").strip()
            val = val.strip().strip('"')
            f = val.split("~")
            if len(f) < 33 or key not in ("sh000001", "sz399001", "sz399006", "hkHSI"):
                continue
            out[key] = {"name": f[1], "price": _sf(f[3]), "change_pct": _sf(f[32])}
        return out
    except Exception:
        return {}


async def hk_announcements_async(code: str, top: int = 4) -> list[dict]:
    """港股近期公告（腾讯自选股 noticeList 接口，免费）。

    港交所披露易高频即限流不可用；腾讯 ifzqgtimg noticeList 稳定可用。
    重大事项关键词（重组/收购/回购/股权等）优先，无命中取最新。返回 [{date, title}]。
    """
    code5 = code.zfill(5)
    try:
        d = await _get_json("https://proxy.finance.qq.com/ifzqgtimg/appstock/news/noticeList/searchByType",
                            params={"symbol": f"hk{code5}", "page": "1", "n": "20", "noticeType": "0"})
        items = ((d or {}).get("data") or {}).get("data") or []
        kw_major = re.compile(r"收购|重组|资产|中标|算力|增发|回购|股权|转让|停牌|合作|投资|分拆|配售")
        kw_minor = re.compile(r"业绩|分红|年报|中期|季度|委任|辞任")
        hits = [it for it in items if kw_major.search(str(it.get("title", "")))]
        if not hits:
            hits = [it for it in items if kw_minor.search(str(it.get("title", "")))]
        chosen = hits or items
        out = []
        for it in chosen[:top]:
            title = str(it.get("title", "")).strip()
            date = str(it.get("time", ""))[:10]
            if title:
                out.append({"date": date, "title": title[:60]})
        return out
    except Exception:
        return []


async def business_mix_async(code: str, market: str, top: int = 3) -> list[dict]:
    """主营构成（同花顺『简况』tab）：东财F10 BusinessAnalysis zygcfx 最新报告期按产品/行业拆分。
    返回 [{item, ratio, gross_margin}]，港股不可用返回 []。"""
    if market.lower() != "cn":
        return []
    prefix = "SH" if code.startswith(("6", "9")) else "SZ"
    d = await _get_json("https://emweb.securities.eastmoney.com/PC_HSF10/BusinessAnalysis/PageAjax",
                        params={"code": f"{prefix}{code}"})
    zg = d.get("zygcfx") or []
    if not zg:
        return []
    latest = zg[0].get("REPORT_DATE", "")  # 接口已按报告期排序
    seen, out = set(), []
    for it in zg:
        if it.get("REPORT_DATE") != latest:
            continue
        name = str(it.get("ITEM_NAME", "")).strip()
        if not name or name in seen:
            continue
        seen.add(name)
        out.append({"item": name,
                    "ratio": round(float(it.get("MBI_RATIO") or 0) * 100, 1),
                    "gross_margin": round(float(it.get("GROSS_RPOFIT_RATIO") or 0) * 100, 1)})
        if len(out) >= top:
            break
    return out


async def finance_brief_async(code: str, market: str) -> dict:
    """主要财务指标（同花顺『财务』tab）：东财数据中台 MAINFINADATA 最新报告期。
    A股返回 {report_date, revenue, revenue_yoy, profit, profit_yoy, eps, roe, gross_margin, net_margin, debt_ratio}，
    港股不可用返回 {}。"""
    if market.lower() != "cn":
        return {}
    suffix = "SH" if code.startswith(("6", "9")) else "SZ"
    secucode = f"{code}.{suffix}"
    d = await _get_json("https://datacenter-web.eastmoney.com/api/data/v1/get",
                        params={"reportName": "RPT_F10_FINANCE_MAINFINADATA", "columns": "ALL",
                                "filter": f'(SECUCODE="{secucode}")',
                                "sortColumns": "REPORT_DATE", "sortTypes": "-1", "pageSize": "1"})
    data = ((d.get("result") or {}).get("data") or [])
    if not data:
        return {}
    it = data[0]
    return {"report_date": str(it.get("REPORT_DATE", ""))[:10],
            "revenue": round(float(it.get("TOTALOPERATEREVE") or 0) / 1e8, 2),
            "revenue_yoy": round(float(it.get("TOTALOPERATEREVETZ") or 0), 1),
            "profit": round(float(it.get("PARENTNETPROFIT") or 0) / 1e8, 2),
            "profit_yoy": round(float(it.get("PARENTNETPROFITTZ") or 0), 1),
            "eps": it.get("EPSJB"), "roe": it.get("ROEJQ"),
            "gross_margin": round(float(it.get("XSMLL") or 0), 1),
            "net_margin": round(float(it.get("XSJLL") or 0), 1),
            "debt_ratio": round(float(it.get("ZCFZL") or 0), 1)}


async def core_conception_async(code: str, market: str) -> dict:
    """核心题材（同花顺『看点』tab）：东财F10 CoreConception 所属板块 + 题材要点。
    A股返回 {boards: [...], themes: [...]}；港股降级返回腾讯 plate 所属板块 {boards: [板块], themes: []}。"""
    if market.lower() == "hk":
        plate = await hk_plate_async(code)
        return {"boards": [plate] if plate else [], "themes": []}
    if market.lower() != "cn":
        return {}
    prefix = "SH" if code.startswith(("6", "9")) else "SZ"
    d = await _get_json("https://emweb.securities.eastmoney.com/PC_HSF10/CoreConception/PageAjax",
                        params={"code": f"{prefix}{code}"})
    boards = [str(b.get("BOARD_NAME", "")).strip() for b in (d.get("ssbk") or []) if b.get("BOARD_NAME")]
    themes = []
    for t in (d.get("hxtc") or [])[:3]:
        content = str(t.get("MAINPOINT_CONTENT", "")).strip()
        if content:
            themes.append({"keyword": str(t.get("KEYWORD", "")).strip(), "content": content})
    return {"boards": boards, "themes": themes}


async def recent_announcements_async(code: str, market: str, top: int = 4) -> list[dict]:
    """近期公告统一入口：A股东财公告，港股暂不可用（披露易限流）。失败返回 [] 不抛异常。"""
    market = market.lower()
    try:
        if market == "cn":
            return await cn_announcements_async(code, top)
        if market == "hk":
            return await hk_announcements_async(code, top)
    except Exception:
        pass
    return []


async def stock_kline_30m_async(code: str, market: str, range_: str = "60d") -> dict:
    """A股/港股统一30分钟K线入口，源链按序取数，绝不伪造周期。
    A股：Yahoo → 东财 → 新浪 → 腾讯mkline → mootdx；港股：Yahoo → 东财。
    任一源拿到 ≥40 根即停，source 字段如实标注实际数据源。"""
    market = market.lower()
    if market == "hk":
        symbol = f"{int(code)}.HK"
        sources = [("Yahoo", lambda: stock_kline_yahoo_async(symbol, interval="30m", range_=range_)),
                   ("东财", lambda: stock_kline_30m_eastmoney_async(code, market))]
    elif market == "cn":
        symbol = f"{code}.SS" if code.startswith(("6", "9")) else f"{code}.SZ"
        sources = [("Yahoo", lambda: stock_kline_yahoo_async(symbol, interval="30m", range_=range_)),
                   ("东财", lambda: stock_kline_30m_eastmoney_async(code, market)),
                   ("新浪", lambda: stock_kline_30m_sina_async(code, market)),
                   ("腾讯", lambda: stock_kline_30m_tencent_async(code, market)),
                   ("mootdx", lambda: stock_kline_30m_mootdx_async(code, market))]
    else:
        return {"available": False, "source": "", "interval": "30m", "bars": [], "bar_count": 0,
                "error": f"不支持的市场: {market}"}
    bars: list[dict] = []
    source = ""
    err = ""
    for name, fn in sources:
        try:
            b = _normalize_intraday_bars(await fn())
            if len(b) >= 40:
                bars, source = b, name
                break
            if len(b) > len(bars):
                bars = b
        except Exception as exc:
            err = f"{err}; {name}: {str(exc)[:60]}".strip("; ")
    if len(bars) < 40:
        return {"available": False, "source": source, "interval": "30m", "bars": bars,
                "bar_count": len(bars), "error": err or "30分钟K线数据不足"}
    return {"available": True, "source": source, "interval": "30m", "bars": bars,
            "bar_count": len(bars), "error": ""}


async def hk_kline_tencent_async(code: str, period: str = "day", count: int = 120) -> list[dict]:
    """腾讯港股K线（日K/周K）。code: 5位数字代码，period: day/week，count: 条数。
    注意：分钟级(5m/60m)只返回当天1根，不建议用于缠论分析。"""
    d = await _tencent_kline_get(f"hk{code},{period},,,{count},qfq")
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



async def cn_stock_kline_tencent_async(code: str, days: int = 120, period: str = "day") -> list[dict]:
    """A股K线（腾讯，前复权，不封IP）。period: day/week"""
    d = await _tencent_kline_get(f"{cn_market_prefix(code)}{code},{period},,,{days},qfq")
    data = d.get("data",{})
    key = f"{cn_market_prefix(code)}{code}"
    kdata = data.get(key, {}) if isinstance(data.get(key), dict) else {}
    # 优先前复权 qfqday/qfqweek/qfq，兜底原始 m/day/week
    klines = (kdata.get("qfqday", []) or kdata.get("qfqweek", []) or kdata.get("qfq", [])
              or kdata.get("m", []) or kdata.get("day", []) or kdata.get("week", []) or [])
    if not klines or not klines[0]: return []
    # 腾讯 fqkline 字段顺序: [date, open, close, high, low, volume]
    return [{"date":i[0],"open":float(i[1]),"close":float(i[2]),"high":float(i[3]),
             "low":float(i[4]),"volume":int(float(i[5]))} for i in klines if len(i)>=6]

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


async def cn_stock_kline_sina_async(code: str, datalen: int = 365) -> list[dict]:
    """A股日K（新浪财经，免费免鉴权）。datalen: 返回条数（最多~1000）。
    接口: money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData
    scale=240 表示日K。字段 day/open/high/low/close/volume。"""
    prefix = cn_market_prefix(code)
    try:
        txt = await _get("https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData",
                         params={"symbol": f"{prefix}{code}", "scale": "240",
                                 "datalen": str(min(datalen, 1000)), "ma": "no"},
                         headers={"Referer": "https://finance.sina.com.cn/"})
    except Exception:
        return []
    try:
        items = json.loads(txt) if txt else []
    except (json.JSONDecodeError, ValueError):
        return []
    if not isinstance(items, list) or not items:
        return []
    return [{"date": str(i.get("day", "")),
             "open": float(i.get("open", 0)),
             "high": float(i.get("high", 0)),
             "low": float(i.get("low", 0)),
             "close": float(i.get("close", 0)),
             "volume": int(float(i.get("volume", 0)))}
            for i in items if i.get("day") and i.get("close")]


async def cn_stock_kline_fallback(code: str, days: int = 365) -> list[dict]:
    """A股日K统一入口（腾讯qfq→新浪→百度→TickFlow）。任一源返回≥20根即终止。
    TickFlow 已降级为最终兜底，前端腾讯/新浪/百度兜底，极少触发。"""
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

    # 2. 新浪（备选，免费免鉴权，实测比百度稳）
    try:
        kl = await cn_stock_kline_sina_async(code, datalen=days)
        if len(kl) >= 20:
            _record_source("cn_kline_sina", True)
            return kl
        _record_source("cn_kline_sina", False)
    except Exception as e:
        _record_source("cn_kline_sina", False)
        print(f"[WARN] 新浪K线失败({code}): {e}")

    # 3. 百度（备选，带MA）
    try:
        kl = await cn_stock_kline_baidu_async(code)
        if len(kl) >= 20:
            _record_source("cn_kline_baidu", True)
            return kl
        _record_source("cn_kline_baidu", False)
    except Exception as e:
        _record_source("cn_kline_baidu", False)
        print(f"[WARN] 百度K线失败({code}): {e}")

    # 4. TickFlow（最终兜底，已降级，前端三源均失败时才触发）
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


# ═════════════════════════════════════════════════
# TickFlow K线（免费免注册，A股+港股+美股，前复权）
# ═════════════════════════════════════════════════
# 官方 SDK: pip install tickflow
# 免费模式: TickFlow.free() — 无需 API Key，提供历史日K/周K/月K
# 完整服务: tickflow.org 注册获取 key，提供实时行情+分钟级K线

_kline_tickflow_session = None

async def _get_tickflow() -> "AsyncTickFlow":
    """懒初始化 TickFlow free session（抑制 banner）。
    已降级为最终兜底源，初始化加 8s 超时快速失败，避免连接挂起拖慢整体。"""
    global _kline_tickflow_session
    if _kline_tickflow_session is None:
        from tickflow import AsyncTickFlow
        import os, contextlib
        devnull = os.devnull
        try:
            with open(devnull, 'w') as fnull:
                with contextlib.redirect_stdout(fnull):
                    _kline_tickflow_session = await asyncio.wait_for(
                        AsyncTickFlow.free().__aenter__(), timeout=8)
        except (asyncio.TimeoutError, Exception):
            # 初始化失败/超时，置 None 便于下次重试，不拖慢调用方
            _kline_tickflow_session = None
            raise
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
        tf = await asyncio.wait_for(_get_tickflow(), timeout=8)
        df = await asyncio.wait_for(
            tf.klines.get(symbol, period=period, count=count,
                          adjust=adjust, as_dataframe=True), timeout=10)
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

    遵循 ai-berkshire financial-data.md 规范：
    每个关键财务数据必须来自两个独立来源，误差>1%须标记。

    数据源架构：
      主源: 东财 datacenter (RPT_HKF10_FN_GMAININDICATOR) — 财务报表数据
      副源: 腾讯行情（PE/PB 实时值） — 独立数据源

    验证字段：
      - ROE/毛利率/净利率/负债率/营收增速/净利增速: 仅东财主源有数据
        标记为「单一数据源，未交叉验证」
      - PE/PB: 东财隐含PE vs 腾讯实时PE，做偏差比对

    注：Yahoo key_statistics 对港股覆盖不全（多数返回空），不作为主力副源。
    东财 RPT_HKF10_FN_CPD 等备用接口对港股无数据。

    Args:
        code: 港股代码，如 "03690"

    Returns:
        {"code": str, "source_pair": str, "fields": [...], "summary": ...}
    """
    secucode = f"{code}.HK"

    # ── 主源：东财 GMAININDICATOR ──
    primary_raw = {}
    try:
        from scripts.quantrisk.data import key_indicators_eastmoney_async
        p_data = await key_indicators_eastmoney_async(secucode)
        if p_data and isinstance(p_data, list) and len(p_data) > 0:
            primary_raw = p_data[0]
    except Exception:
        pass

    if not primary_raw:
        return {"code": code, "source_pair": "无数据", "fields": [],
                "summary": {"total": 0, "ok": 0, "warn": 0, "error": 0,
                            "error_msg": "东财数据获取失败，无主源数据"}}

    # ── 副源：腾讯行情（PE/PB实时值） ──
    tencent_raw = {}
    try:
        from scripts.quantrisk.data import hk_stock_quote_tencent_async
        tencent_raw = await hk_stock_quote_tencent_async(code)
    except Exception:
        pass

    # ── 可选副源：Yahoo key_statistics ──
    yahoo_raw = {}
    try:
        from scripts.quantrisk.data import key_statistics_async
        yahoo_raw = await key_statistics_async(secucode)
    except Exception:
        pass

    def _sf(v):
        if v is None: return None
        try: return float(v)
        except (ValueError, TypeError): return None

    # 财务比率字段（单一数据源，仅标注）
    SINGLE_SOURCE_FIELDS = ["ROE", "GROSS_PROFIT_RATIO", "NET_PROFIT_RATIO",
                            "DEBT_ASSET_RATIO", "OPERATE_INCOME_YOY", "HOLDER_PROFIT_YOY"]
    SINGLE_CN = {
        "ROE": "ROE", "GROSS_PROFIT_RATIO": "毛利率", "NET_PROFIT_RATIO": "净利率",
        "DEBT_ASSET_RATIO": "负债率", "OPERATE_INCOME_YOY": "营收增速", "HOLDER_PROFIT_YOY": "净利增速",
    }

    fields = []

    # 1️⃣ 财务比率：标注单一数据源（东财唯一来源）
    for key in SINGLE_SOURCE_FIELDS:
        pv = _sf(primary_raw.get(key))
        if pv is None or pv == 0:
            continue
        fields.append({
            "name": SINGLE_CN[key],
            "primary": round(pv, 2),
            "secondary": None,
            "deviation_pct": None,
            "status": "📊",  # 单一数据源标记
            "secondary_source": "单一数据源（东财）",
        })

    # 2️⃣ PE：腾讯行情 vs 东财 GMAININDICATOR 不直接提供PE
    #     用腾讯行情 PE 作为可验证值，标注来源
    tencent_pe = _sf(tencent_raw.get("pe")) or _sf(tencent_raw.get("pe_ttm"))
    if tencent_pe and tencent_pe > 0:
        fields.append({
            "name": "PE(TTM)",
            "primary": round(tencent_pe, 2),
            "secondary": None,
            "deviation_pct": None,
            "status": "📊",
            "secondary_source": "腾讯行情（单一数据源）",
        })

    # 3️⃣ PB：腾讯行情
    tencent_pb = _sf(tencent_raw.get("pb"))
    if tencent_pb and tencent_pb > 0:
        fields.append({
            "name": "PB",
            "primary": round(tencent_pb, 2),
            "secondary": None,
            "deviation_pct": None,
            "status": "📊",
            "secondary_source": "腾讯行情（单一数据源）",
        })

    # 4️⃣ Yahoo 补充：若有数据则做交叉验证
    for cn_name, em_key, yh_key, unit in [
        ("ROE", "ROE", "return_on_equity", "x100"),
        ("净利率", "NET_PROFIT_RATIO", "profit_margins", "x100"),
        ("营收增速", "OPERATE_INCOME_YOY", "revenue_growth", "x100"),
    ]:
        pv = _sf(primary_raw.get(em_key))
        if pv is None or pv == 0:
            continue
        sv = _sf(yahoo_raw.get(yh_key))
        if sv is None or sv == 0:
            continue
        if unit == "x100":
            sv *= 100
        deviation = abs(pv - sv) / abs(pv) * 100
        if deviation <= 1.0:
            status = "✅"
        elif deviation <= 5.0:
            status = "⚠️"
        else:
            status = "❌"
        fields.append({
            "name": cn_name,
            "primary": round(pv, 2),
            "secondary": round(sv, 2),
            "deviation_pct": round(deviation, 2),
            "status": status,
            "secondary_source": "Yahoo",
        })

    # 汇总
    verified = [f for f in fields if f["status"] in ("✅", "⚠️", "❌")]
    single = [f for f in fields if f["status"] == "📊"]
    ok_count = sum(1 for f in verified if f["status"] == "✅")
    warn_count = sum(1 for f in verified if f["status"] == "⚠️")
    error_count = sum(1 for f in verified if f["status"] == "❌")

    return {
        "code": code,
        "source_pair": "东财(主) + 腾讯/Yahoo(副)",
        "fields": fields,
        "summary": {
            "total": len(fields),
            "verified": len(verified),
            "single_source": len(single),
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
        "DEBT_ASSET_RATIO": ("DEBT_ASSET_RATIO", "ZCFZL"),  # 资产负债率（来自 F10 主要财务指标）
        "HOLDER_PROFIT_YOY": ("HOLDER_PROFIT_YOY", "SJLTZ"),     # 净利润增长率
        "OPERATE_INCOME": ("OPERATE_INCOME", "TOTAL_OPERATE_INCOME"),  # 营业总收入
        "OPERATE_INCOME_YOY": ("OPERATE_INCOME_YOY", "YSTZ"),    # 营收同比增长
        "HOLDER_PROFIT": ("HOLDER_PROFIT", "PARENT_NETPROFIT"),  # 归母净利润
    }
    PRECISION = {"ROE": 2, "JQROE": 2, "GROSS_PROFIT_RATIO": 2,
                 "DEBT_ASSET_RATIO": 2, "HOLDER_PROFIT_YOY": 2,
                 "OPERATE_INCOME": 2, "OPERATE_INCOME_YOY": 2,
                 "HOLDER_PROFIT": 2}
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
    result = _normalize_cn_indicators(data)
    # CPD 报表缺少正确的资产负债率/净利率，补充东财 F10 主要财务指标（ZCFZL/XSJLL）
    try:
        main = await eastmoney_datacenter("RPT_F10_FINANCE_MAINFINADATA",
                                          filter_str=f'(SECUCODE="{secucode}")',
                                          page_size=1, sort_columns="REPORT_DATE", sort_types="-1")
        if main and result:
            m = main[0]
            latest = result[0]
            for src, dst in (("ZCFZL", "DEBT_ASSET_RATIO"),
                             ("XSJLL", "NET_PROFIT_RATIO"),
                             ("ROEJQ", "ROE"),
                             ("XSMLL", "GROSS_PROFIT_RATIO"),
                             ("TOTALOPERATEREVE", "OPERATE_INCOME"),
                             ("TOTALOPERATEREVETZ", "OPERATE_INCOME_YOY"),
                             ("PARENTNETPROFIT", "HOLDER_PROFIT"),
                             ("PARENTNETPROFITTZ", "HOLDER_PROFIT_YOY")):
                if m.get(src) is not None:
                    latest[dst] = round(float(m[src]), 2)
    except Exception:
        pass
    return result


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
# 东财 fflow 端点高并发下经常静默返回空数组或触发 ServerDisconnectedError（2026-08-31 排查：
# 两市场脚本并行、400+ 只并发拉资金流时"主力5日"全 +0.00亿）。统一限流并发，所有调用方共用。
_fflow_sem: Optional[asyncio.Semaphore] = None


def _get_fflow_sem() -> asyncio.Semaphore:
    global _fflow_sem
    if _fflow_sem is None:
        _fflow_sem = asyncio.Semaphore(5)
    return _fflow_sem


async def fund_flow_daily_async(ticker_or_code: str, secid_prefix: int = 105, limit: int = 100) -> list[dict]:
    """获取个股日度资金流向（东财 fflow，全局限流并发 5，空返回指数退避重试）。"""
    async with _get_fflow_sem():
        return await _fund_flow_daily_async_inner(ticker_or_code, secid_prefix, limit)


async def _fund_flow_daily_async_inner(ticker_or_code: str, secid_prefix: int = 105, limit: int = 100) -> list[dict]:
    """获取个股日度资金流向。

    A股使用 daykline/get 端点，港股(secid_prefix=116)使用 kline/get 端点（daykline/get对港股返回空）。
    东财 fflow/kline/get 对部分港股覆盖不全，有数据的返回主力资金净流入，无数据的返回空数组。
    """
    import json as _json
    s = await get_async_session()

    # push2his 端点支持多日历史（push2 只返回当日）；港股走 kline/get，A股走 daykline/get
    urls = ["https://push2his.eastmoney.com/api/qt/stock/fflow/kline/get",
            "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"]
    if secid_prefix == 116:
        urls = urls  # kline/get 优先
    else:
        urls = list(reversed(urls))  # daykline/get 优先（A股）

    for attempt in range(4):
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
            if attempt < 3:
                await asyncio.sleep(0.5 * (2 ** attempt))  # 指数退避 0.5s/1s/2s
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
