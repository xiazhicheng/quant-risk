"""
quantrisk — A股推荐适配器

市场专属数据源，与 shared_recommender.py 配合使用。
A股候选池: 东财全市场 A 股 → 行业板块 → 三维评分
"""
from __future__ import annotations

import asyncio
from typing import Dict, List, Optional, Tuple

from scripts.quantrisk.data import (
    cn_stock_quote_tencent_async,
    cn_stock_kline_tencent_async,
    cn_key_indicators_async,
    cn_stock_basic_info_async,
    cn_industry_ranking_async,
    cn_fund_flow_minute_async,
    fund_flow_daily_async,
    eastmoney_datacenter,
    parallel_map,
    close_async_session,
)


# ═══════════════════════════════════════════════════════════════
# A股行业 PE 阈值
# ═══════════════════════════════════════════════════════════════

CN_SECTOR_PE_THRESHOLD = {
    "信息技术": 60,
    "医药生物": 60,
    "工业": 60,
    "基础材料": 40,
    "能源": 25,
    "消费者用品": 50,
    "金融": 15,
    "公用事业": 30,
    "房地产": 15,
    "其他": 60,
}


# ═══════════════════════════════════════════════════════════════
# A股候选池 — 从东财全市场拉取（按市值排序）
# ═══════════════════════════════════════════════════════════════

def _parse_em_code(em_code: str) -> Optional[str]:
    """东方财富代码 → 腾讯代码 (600519.SH → 600519)"""
    if not em_code:
        return None
    # em_code 格式: 600519.SH 或 600519
    return em_code.split(".")[0] if "." in em_code else em_code


async def fetch_cn_candidate_pool(min_stocks: int = 300) -> List[Dict[str, str]]:
    """从东财全市场拉取 A 股候选池（按市值排序，取前 500 只）

    返回: [{code, name, industry, mcap, price, pe, sector}, ...]
    """
    try:
        # 用东财 datacenter 拉取全市场 A 股列表（按总市值排序）
        stocks = await eastmoney_datacenter(
            "RPTA_WEB_MARKET",
            columns="SECUCODE,SECURITY_CODE,SECURITY_NAME_ABBR,MARKET,INDUSTRY,CHANGE_RATE,TOTAL_MARKET_CAP,LATEST_PRICE",
            sort_columns="TOTAL_MARKET_CAP",
            sort_types="-1",
            page_size=100,
        )
        if not stocks:
            stocks = await eastmoney_datacenter(
                "RPTA_WEB_MARKET",
                columns="SECUCODE,SECURITY_CODE,SECURITY_NAME_ABBR,MARKET,INDUSTRY,CHANGE_RATE,TOTAL_MARKET_CAP,LATEST_PRICE",
                page_size=500,
            )

        candidates = []
        for s in stocks:
            code = _parse_em_code(s.get("SECUCODE", ""))
            if not code:
                continue
            name = s.get("SECURITY_NAME_ABBR", "")
            industry = s.get("INDUSTRY", "其他")
            market = s.get("MARKET", "")
            mcap = s.get("TOTAL_MARKET_CAP", 0)
            price = s.get("LATEST_PRICE", 0)
            pe = s.get("PE", 0)

            # 过滤 ETF/衍生品/ST
            if any(kw in name for kw in ["ETF", "LOF", "REIT", "购", "沽", "牛", "熊"]):
                continue
            if name.startswith("ST"):
                continue

            candidates.append({
                "code": code,
                "name": name,
                "industry": industry,
                "market": market,
                "mcap": mcap,
                "price": price,
                "pe": pe,
                "sector": industry,
            })

            if len(candidates) >= min_stocks:
                break

        return candidates

    except Exception as e:
        print(f"[WARN] 候选池获取失败: {e}")
        return []


async def fetch_cn_industry_ranking(top_n: int = 20) -> List[Dict[str, Any]]:
    """行业板块涨跌排名"""
    try:
        return await cn_industry_ranking_async(top_n=top_n)
    except Exception as e:
        print(f"[WARN] 行业排名获取失败: {e}")
        return []


async def fetch_cn_capital_flow(codes: List[str]) -> Dict[str, float]:
    """批量获取 A 股个股资金流向"""
    import asyncio
    results = {}
    for code in codes:
        try:
            flows = await cn_fund_flow_minute_async(code)
            if flows and len(flows) > 0:
                latest = flows[-1]
                results[code] = latest.get("main_net", 0)
            else:
                results[code] = 0.0
        except Exception as e:
            results[code] = 0.0
    return results


# ═══════════════════════════════════════════════════════════════
# A股评分函数
# ═══════════════════════════════════════════════════════════════

async def cn_score_one(
    p: Dict[str, Any],
    kl: List[Dict],
    industry_thresholds: Dict[str, int] = None,
    capital_flow: Optional[Dict[str, float]] = None,
    sector_ranking: Optional[List[Tuple[str, Any]]] = None,
) -> Dict[str, Any]:
    """A股单只股票三维评分（调用 shared_recommender）"""
    from scripts.quantrisk.recommender import score_one
    return score_one(p, kl, sector_ranking, capital_flow, industry_thresholds, market="cn")


async def cn_batch_analysis(candidates: List[Dict[str, str]]) -> Dict[str, Dict]:
    """A股批量分析（并行获取行情 + K线 + 基本面）"""
    codes = [c["code"] for c in candidates]

    # 并行获取行情
    qf = [lambda c=c: cn_stock_quote_tencent_async(c) for c in codes]
    qr = await parallel_map(qf, max_concurrency=20)

    # 并行获取 K线（腾讯日K）
    kf = [lambda c=c: cn_stock_kline_tencent_async(c, days=730) for c in codes]
    kl = await parallel_map(kf, max_concurrency=20)

    # 并行获取基本面（东财）
    indf = [lambda c=c: cn_key_indicators_async(c, page_size=4) for c in codes]
    ind = await parallel_map(indf, max_concurrency=20)

    # 构建结果字典
    st = {}
    for i, code in enumerate(codes):
        q = qr[i] if isinstance(qr[i], dict) else {}
        klines = kl[i] if isinstance(kl[i], list) and kl[i] else []
        indicators = ind[i] if isinstance(ind[i], list) and ind[i] else {}

        st[code] = {
            "quote": q,
            "klines": klines,
            "indicator": indicators[0] if isinstance(indicators, list) and indicators else {},
        }

    return st


# ═══════════════════════════════════════════════════════════════
# A股主流程
# ═══════════════════════════════════════════════════════════════

async def cn_recommend_pipeline(candidates: List[Dict[str, str]]) -> dict:
    """A股推荐完整流程（三步强制流程）"""
    ds = __import__("datetime").datetime.now().strftime("%Y-%m-%d")

    # Step 1: 构建板块映射
    code2sector = {c["code"]: c.get("sector", "其他") for c in candidates}
    all_codes = [c["code"] for c in candidates]

    # Step 2: 批量分析（行情 + K线 + 基本面）
    st = await cn_batch_analysis(candidates)

    # 板块表现
    ss = {}
    for code, info in st.items():
        q = info.get("quote", {}) or {}
        chg = q.get("change_pct", 0)
        sector = code2sector.get(code, "其他")
        ss[sector] = {"c": 1, "ap": chg, "up": 1 if chg > 0 else 0, "dn": 0 if chg > 0 else 1}
       

    # Step 3: 中观过滤
    from scripts.quantrisk.recommender import meso_filter
    passed, elim = meso_filter(st, CN_SECTOR_PE_THRESHOLD, code2sector, secid_prefix="cn")
    passed_cnt = len(passed)

    # Step 4: 资金流向
    capital_flow = {}
    try:
        capital_flow = await fetch_cn_capital_flow([p["c"] for p in passed])
    except Exception:
        pass

    # Step 5: 并行评分
    from scripts.quantrisk.recommender import score_one
    scored = []
    for p in passed:
        c = p["c"]
        kl = st.get(c, {}).get("klines", []) or st.get(c, {}).get("quote", {}).get("klines", [])
        if not kl or len(kl) < 20:
            kl = st.get(c, {}).get("klines", []) or []
        s = await cn_score_one(p, kl, CN_SECTOR_PE_THRESHOLD, capital_flow)
        scored.append(s)

    scored.sort(key=lambda x: x["total"], reverse=True)

    # Step 6: 格式化
    from scripts.quantrisk.recommender import build_selection_data
    raw_data = build_selection_data(ds, ss, elim, scored, passed_cnt, capital_flow)
    return raw_data
