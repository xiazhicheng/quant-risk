"""
quantrisk — 美股推荐适配器

市场专属数据源，与 shared_recommender.py 配合使用。
美股候选池: S&P 500 核心成分 + 热门标的
"""
from __future__ import annotations

import asyncio
from typing import Dict, List, Optional, Tuple

from scripts.quantrisk.data import (
    us_stock_quote_tencent_async,
    us_stock_quote_sina_async,
    us_stock_kline_sina_async,
    key_statistics_async,
    parallel_map,
    close_async_session,
)


# ═══════════════════════════════════════════════════════════════
# 美股行业 PE 阈值
# ═══════════════════════════════════════════════════════════════

US_SECTOR_PE_THRESHOLD = {
    "Technology": 50,
    "Health Care": 40,
    "Consumer Discretionary": 45,
    "Financials": 18,
    "Industrials": 25,
    "Materials": 30,
    "Communication Services": 25,
    "Consumer Staples": 35,
    "Energy": 20,
    "Utilities": 25,
    "Real Estate": 30,
    "Other": 40,
}


# ═══════════════════════════════════════════════════════════════
# 美股核心候选池 (S&P 500 核心 + 热门科技/成长)
# ═══════════════════════════════════════════════════════════════

US_CORE_STOCKS = [
    # Technology
    "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "META", "NVDA", "TSLA", "AVGO", "ORCL",
    "CRM", "ADBE", "CSCO", "INTC", "AMD", "QCOM", "IBM", "NOW", "PANW", "SNOW",
    # Health Care
    "JNJ", "PFE", "ABBV", "MRK", "UNH", "TMO", "ABT", "DHR", "LLY", "BMY",
    # Financials
    "JPM", "BAC", "GS", "MS", "BLK", "SCHW", "V", "MA", "WFC", "C",
    # Consumer
    "WMT", "HD", "DIS", "NKE", "MCD", "SBUX", "SBUX", "TGT", "COST", "KO",
    # Industrials
    "CAT", "DE", "UNP", "UPS", "BA", "GE", "HON", "RTX", "MMM", "LMT",
    # Energy
    "XOM", "CVX", "COP", "SLB", "EOG", "OXY", "HAL", "MPC", "VLO", "PSX",
    # Communication Services
    "NFLX", "CMCSA", "VZ", "T", "TMUS", "CHTR", "EA", "ATVI",
    # Materials
    "LIN", "APD", "DD", "DOW", "ECL", "FMC", "PPG", "NEM",
    # Utilities
    "NEE", "DUK", "SO", "D", "AEP", "EXC", "SRE", "XEL",
    # Real Estate
    "AMT", "PLD", "CCI", "EQIX", "PSA", "SPG", "O", "DLR",
    # Consumer Staples
    "PG", "COST", "KO", "PEP", "MNST", "KHC", "CL", "GIS",
]

# 美股 → 行业映射
US_STOCK_SECTOR_MAP = {
    # Technology
    "AAPL": "Technology", "MSFT": "Technology", "GOOGL": "Technology", "GOOG": "Technology",
    "AMZN": "Technology", "META": "Technology", "NVDA": "Technology", "TSLA": "Technology",
    "AVGO": "Technology", "ORCL": "Technology", "CRM": "Technology", "ADBE": "Technology",
    "CSCO": "Technology", "INTC": "Technology", "AMD": "Technology", "QCOM": "Technology",
    "IBM": "Technology", "NOW": "Technology", "PANW": "Technology", "SNOW": "Technology",
    # Health Care
    "JNJ": "Health Care", "PFE": "Health Care", "ABBV": "Health Care", "MRK": "Health Care",
    "UNH": "Health Care", "TMO": "Health Care", "ABT": "Health Care", "DHR": "Health Care",
    "LLY": "Health Care", "BMY": "Health Care",
    # Financials
    "JPM": "Financials", "BAC": "Financials", "GS": "Financials", "MS": "Financials",
    "BLK": "Financials", "SCHW": "Financials", "V": "Financials", "MA": "Financials",
    "WFC": "Financials", "C": "Financials",
    # Consumer Discretionary
    "WMT": "Consumer", "HD": "Consumer", "DIS": "Consumer", "NKE": "Consumer",
    "MCD": "Consumer", "SBUX": "Consumer", "TGT": "Consumer", "COST": "Consumer",
    # Industrials
    "CAT": "Industrials", "DE": "Industrials", "UNP": "Industrials", "UPS": "Industrials",
    "BA": "Industrials", "GE": "Industrials", "HON": "Industrials", "RTX": "Industrials",
    "MMM": "Industrials", "LMT": "Industrials",
    # Energy
    "XOM": "Energy", "CVX": "Energy", "COP": "Energy", "SLB": "Energy",
    "EOG": "Energy", "OXY": "Energy", "HAL": "Energy", "MPC": "Energy",
    "VLO": "Energy", "PSX": "Energy",
    # Communication Services
    "NFLX": "Communication Services", "CMCSA": "Communication Services", "VZ": "Communication Services",
    "T": "Communication Services", "TMUS": "Communication Services", "CHTR": "Communication Services",
    "EA": "Communication Services", "ATVI": "Communication Services",
    # Materials
    "LIN": "Materials", "APD": "Materials", "DD": "Materials", "DOW": "Materials",
    "ECL": "Materials", "FMC": "Materials", "PPG": "Materials", "NEM": "Materials",
    # Utilities
    "NEE": "Utilities", "DUK": "Utilities", "SO": "Utilities", "D": "Utilities",
    "AEP": "Utilities", "EXC": "Utilities", "SRE": "Utilities", "XEL": "Utilities",
    # Real Estate
    "AMT": "Real Estate", "PLD": "Real Estate", "CCI": "Real Estate", "EQIX": "Real Estate",
    "PSA": "Real Estate", "SPG": "Real Estate", "O": "Real Estate", "DLR": "Real Estate",
    # Consumer Staples
    "PG": "Consumer Staples", "KO": "Consumer Staples", "PEP": "Consumer Staples",
    "MNST": "Consumer Staples", "KHC": "Consumer Staples", "CL": "Consumer Staples",
    "GIS": "Consumer Staples",
}


def get_us_candidate_pool() -> List[Dict[str, str]]:
    """获取美股候选池（S&P 500 核心 + 热门标的）"""
    candidates = []
    seen = set()
    for ticker in US_CORE_STOCKS:
        if ticker in seen:
            continue
        seen.add(ticker)
        sector = US_STOCK_SECTOR_MAP.get(ticker, "Other")
        candidates.append({
            "ticker": ticker,
            "name": "",  # 将在获取行情时填充
            "sector": sector,
            "code": ticker,
        })
    return candidates


# ═══════════════════════════════════════════════════════════════
# 美股批量分析
# ═══════════════════════════════════════════════════════════════

async def us_batch_analysis(candidates: List[Dict[str, str]]) -> Dict[str, Dict]:
    """美股批量分析（并行获取行情 + K线 + Yahoo stats）"""
    tickers = [c["ticker"] for c in candidates]

    # 并行获取行情
    qf = [lambda t=t: us_stock_quote_tencent_async(t) for t in tickers]
    qr = await parallel_map(qf, max_concurrency=20)

    qf2 = [lambda t=t: us_stock_quote_sina_async(t) for t in tickers]
    qr2 = await parallel_map(qf2, max_concurrency=20)

    # 并行获取 K线
    kf = [lambda t=t: us_stock_kline_sina_async(t, num=730) for t in tickers]
    kl = await parallel_map(kf, max_concurrency=20)

    # 并行获取 Yahoo stats
    yf = [lambda t=t: key_statistics_async(t.upper()) for t in tickers]
    ys = await parallel_map(yf, max_concurrency=20)

    st = {}
    for i, ticker in enumerate(tickers):
        q_tx = qr[i] if isinstance(qr[i], dict) else {}
        q_sina = qr2[i] if isinstance(qr2[i], dict) else {}
        klines = kl[i] if isinstance(kl[i], list) and kl[i] else []
        yahoo = ys[i] if isinstance(ys[i], dict) else {}

        # 合并腾讯 + 新浪行情
        quote = dict(q_tx)
        if q_sina:
            if not quote.get("name"):
                quote["name"] = q_sina.get("name", "")
            if not quote.get("price"):
                quote["price"] = q_sina.get("price", 0)
            if not quote.get("open"):
                quote["open"] = q_sina.get("open", 0)
            if not quote.get("pe") or quote["pe"] <= 0 or quote["pe"] > 5000:
                quote["pe"] = q_sina.get("pe", quote["pe"])
            if not quote.get("high_52w") or quote["high_52w"] <= 0:
                quote["high_52w"] = q_sina.get("high_52w", 0)
            if not quote.get("low_52w") or quote["low_52w"] <= 0:
                quote["low_52w"] = q_sina.get("low_52w", 0)
            if not quote.get("market_cap") or quote["market_cap"] <= 0:
                quote["market_cap"] = q_sina.get("market_cap", 0)

        st[ticker] = {
            "quote": quote,
            "klines": klines,
            "indicator": {},  # 美股无东财基本面
            "yahoo_stats": yahoo,
        }

    return st


# ═══════════════════════════════════════════════════════════════
# 美股主流程
# ═══════════════════════════════════════════════════════════════

async def us_recommend_pipeline(candidates: List[Dict[str, str]]) -> dict:
    """美股推荐完整流程（三步强制流程）"""
    ds = __import__("datetime").datetime.now().strftime("%Y-%m-%d")

    # Step 1: 板块映射
    code2sector = {c["ticker"]: c.get("sector", "Other") for c in candidates}

    # Step 2: 批量分析
    st = await us_batch_analysis(candidates)

    # 板块表现
    ss = {}
    for ticker, info in st.items():
        q = info.get("quote", {}) or {}
        chg = q.get("change_pct", 0)
        sector = code2sector.get(ticker, "Other")
        if sector not in ss:
            ss[sector] = {"c": 0, "chg_sum": 0.0, "up": 0, "dn": 0}
        ss[sector]["c"] += 1
        ss[sector]["chg_sum"] += chg
        if chg > 0:
            ss[sector]["up"] += 1
        else:
            ss[sector]["dn"] += 1

    for sec in ss:
        s = ss[sec]
        s["ap"] = round(s["chg_sum"] / s["c"], 2) if s["c"] > 0 else 0

    # Step 3: 中观过滤
    from scripts.quantrisk.recommender import meso_filter, fundamental_veto
    passed, elim = meso_filter(st, US_SECTOR_PE_THRESHOLD, code2sector, secid_prefix="us")
    # 基本面一票否决（贯彻"基本面为主"理念）
    passed, vetoed = fundamental_veto(passed)
    passed_cnt = len(passed)

    # Step 4: K线已在 batch_analysis 中获取 → 共享原始分 → 百分位排名
    from scripts.quantrisk.recommender import _raw_score_one, percentile_score_all

    # 从K线数据计算板块排名（基于近5日平均涨跌幅）
    from collections import defaultdict
    sector_5d_pcts = defaultdict(list)
    for p in passed:
        c, sec = p["c"], p["s"]
        kl = st.get(p["c"], {}).get("klines", []) or []
        if kl and len(kl) >= 6:
            c5 = kl[-6].get("close", 0) or 0
            c0 = kl[-1].get("close", 0) or 0
            if c5 > 0:
                pct_5d = (c0 - c5) / c5 * 100
                sector_5d_pcts[sec].append(pct_5d)
    sector_ranking = []
    for sec, pcts in sector_5d_pcts.items():
        avg_5d = sum(pcts) / len(pcts) if pcts else 0
        sector_ranking.append((sec, {"avg_5d_pct": avg_5d, "stock_count": len(pcts)}))
    sector_ranking = sorted(sector_ranking, key=lambda x: x[1]["avg_5d_pct"], reverse=True)
    for i, item in enumerate(sector_ranking):
        item[1]["rank"] = i

    raw_scores = [
        _raw_score_one(p, st.get(p["c"], {}).get("klines", []) or [], US_SECTOR_PE_THRESHOLD,
                       sector_ranking=sector_ranking, market="us")
        for p in passed
    ]

    scored = percentile_score_all(raw_scores)

    # Step 5: 格式化
    from scripts.quantrisk.recommender import build_selection_data
    raw_data = build_selection_data(ds, ss, elim, scored, passed_cnt, sector_ranking=sector_ranking, vetoed=vetoed)
    return raw_data
