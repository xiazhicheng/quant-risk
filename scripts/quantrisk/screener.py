"""
quantrisk — 标的池三层筛选逻辑 + 批量查询
"""
import asyncio
from .data import (parallel_map, hk_stock_quote_tencent_async,
                   stock_kline_yahoo_async, key_indicators_eastmoney_async,
                   key_statistics_async)


# ── 批量查询（同步入口）──

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
    """并行获取多只港股基本面关键指标"""
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
        quotes, indicators = await asyncio.gather(
            parallel_map(qf), parallel_map(indf)
        )
        result = {}
        for i, code in enumerate(codes):
            q = quotes[i] if isinstance(quotes[i], dict) else {}
            ind = indicators[i][0] if isinstance(indicators[i], list) and indicators[i] else {}
            result[code] = {"quotes": q, "indicators": ind}
        return result
    return asyncio.run(_batch())


# ── 三层筛选 ──

async def build_candidate_pool(market: str = "hk", top_sectors: int = 5, top_per_sector: int = 5) -> list[dict]:
    """① 宏观筛选：构建候选池"""
    from .data import cn_industry_ranking_async, market_stock_list_async
    sectors = await cn_industry_ranking_async(top_n=20)
    hot_sectors = [s for s in sectors if s.get("pct", 0) > 0][:top_sectors]
    candidates = []
    for sec in hot_sectors:
        sector_stocks = await market_stock_list_async(
            market=market, sort_field="f3", sort_desc=True, page=1, page_size=top_per_sector
        )
        for s in (sector_stocks.get("stocks") or [])[:top_per_sector]:
            s["sector"] = sec.get("industry", "")
            s["sector_pct"] = sec.get("pct", 0)
            candidates.append(s)
    return candidates


def filter_candidates(candidates: list[dict]) -> list[dict]:
    """② 中观过滤：硬约束剔除（港股）"""
    filtered = []
    for c in candidates:
        price = c.get("price") or 0
        vol = c.get("volume") or 0
        if price < 1.0:
            continue
        if vol < 1_000_0000:
            continue
        filtered.append(c)
    return filtered


def score_candidate(hot_score: int, fundamental_score: int, chan_score: int) -> dict:
    """③ 微观精选：三维评分"""
    weights = {"hot": 3, "fundamental": 5, "chan": 2}
    total = (
        hot_score * weights["hot"]
        + fundamental_score * weights["fundamental"]
        + chan_score * weights["chan"]
    )
    return {
        "hot_score": hot_score,
        "fundamental_score": fundamental_score,
        "chan_score": chan_score,
        "total_score": total,
    }


def rank_candidates(scored: list[dict]) -> list[dict]:
    """按总分排序输出"""
    return sorted(scored, key=lambda x: x["total_score"], reverse=True)


def run_stock_selection(market: str = "hk") -> list[dict]:
    """标的池筛选全流程"""
    async def _run():
        pool = await build_candidate_pool(market)
        pool = filter_candidates(pool)
        return pool
    return asyncio.run(_run())
