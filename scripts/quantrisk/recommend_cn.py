"""
quantrisk — A股推荐适配器

市场专属数据源，与 shared_recommender.py 配合使用。
A股候选池: 东财全市场 A 股 → 行业板块 → 三维评分
"""
from __future__ import annotations

import asyncio
import aiohttp
from typing import Dict, List, Optional, Tuple

from scripts.quantrisk.data import (
    cn_stock_quote_tencent_async,
    cn_stock_quote_fallback,
    cn_stock_kline_tencent_async,
    cn_stock_kline_fallback,
    cn_key_indicators_async,
    cn_key_indicators_fallback,
    cn_stock_basic_info_async,
    cn_industry_ranking_async,
    cn_fund_flow_minute_async,
    fund_flow_daily_async,
    eastmoney_datacenter,
    parallel_map,
    close_async_session,
    get_async_session,
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
    """从腾讯行情 API 拉取 A 股候选池（上海+深圳全市场）

    东财 push2 在当前网络环境下不可用，改用腾讯行情 API 批量查询。
    腾讯 API 支持一次查询 200+ 只股票，分批查询即可覆盖全市场。

    返回: [{code, name, industry, mcap, price, pe, sector}, ...]
    """
    try:
        import json, asyncio, math

        # 生成所有可能的 A 股代码
        # 按优先级排序：上海主板(600000-605199) → 深圳主板(000000-003999) → 创业板(300000-301999)
        all_codes = []
        # 上海: 600000-605199
        for i in range(600000, 605200):
            all_codes.append(f"sh{i}")
        # 深圳主板: 000000-003999
        for i in range(0, 4000):
            all_codes.append(f"sz{i:06d}")
        # 深圳创业板: 300000-301999
        for i in range(300000, 302000):
            all_codes.append(f"sz{i}")

        candidates = []
        batch_size = 200  # 腾讯 API 支持 200 个/批，实测可用

        for batch_start in range(0, len(all_codes), batch_size):
            if len(candidates) >= min_stocks:
                break
            batch = all_codes[batch_start:batch_start + batch_size]
            url = "http://qt.gtimg.cn/q=" + ",".join(batch)

            # 重试 2 次
            text = ""
            for retry in range(3):
                try:
                    connector = aiohttp.TCPConnector(force_close=True, limit=1)
                    async with aiohttp.ClientSession(connector=connector) as session:
                        async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                            raw = await resp.read()
                            text = raw.decode("gbk")
                    if text and len(text) >= 10:
                        break
                except Exception:
                    if retry < 2:
                        await asyncio.sleep(0.5)
                    else:
                        raise

            if not text:
                continue

            for line in text.strip().split(";"):
                line = line.strip()
                if not line or "=" not in line:
                    continue
                parts = line.split("=", 1)
                val = parts[1].strip("\"")
                if not val:
                    continue
                fields = val.split("~")
                if len(fields) < 46:
                    continue

                name = fields[1]
                code = fields[2]
                price = float(fields[3]) if fields[3] else 0
                pe = float(fields[39]) if fields[39] and fields[39] != "0.00" else 0
                mcap = float(fields[44]) if fields[44] and fields[44] != "0.00" else 0

                if not code or not name:
                    continue
                # 过滤 ETF/衍生品/ST
                if any(kw in name for kw in ["ETF", "LOF", "REIT", "购", "沽", "牛", "熊"]):
                    continue
                if name.startswith("ST"):
                    continue
                if price <= 0:
                    continue

                candidates.append({
                    "code": code,
                    "name": name,
                    "industry": "其他",
                    "market": "",
                    "mcap": mcap,
                    "price": price,
                    "pe": pe,
                    "sector": "其他",
                })

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
    """批量获取 A 股个股资金流向（并行）"""
    async def _fetch_one(code):
        try:
            flows = await cn_fund_flow_minute_async(code)
            if flows and len(flows) > 0:
                return code, flows[-1].get("main_net", 0)
            return code, 0.0
        except Exception:
            return code, 0.0
    results_list = await asyncio.gather(*[_fetch_one(c) for c in codes], return_exceptions=True)
    return {c: v for c, v in results_list if isinstance(v, (int, float))}


# ═══════════════════════════════════════════════════════════════
# A股批量分析
# ═══════════════════════════════════════════════════════════════

async def cn_batch_analysis(candidates: List[Dict[str, str]]) -> Dict[str, Dict]:
    """A股批量分析（并行获取行情 + 基本面，K线按需获取）"""
    codes = [c["code"] for c in candidates]

    # 并行获取行情
    qf = [lambda c=c: cn_stock_quote_tencent_async(c) for c in codes]
    qr = await parallel_map(qf, max_concurrency=20)

    # 并行获取基本面（东财→Yahoo→mootdx，三级 fallback）
    indf = [lambda c=c: cn_key_indicators_fallback(c) for c in codes]
    ind = await parallel_map(indf, max_concurrency=20)

    # 构建结果字典（K线后面按需获取）
    st = {}
    for i, code in enumerate(codes):
        q = qr[i] if isinstance(qr[i], dict) else {}
        indicators = ind[i] if isinstance(ind[i], list) and ind[i] else {}

        st[code] = {
            "quote": q,
            "klines": [],
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

    # Step 2: 批量分析（行情 + 基本面，K线按需获取）
    st = await cn_batch_analysis(candidates)

    # 板块表现
    ss = {}
    for code, info in st.items():
        q = info.get("quote", {}) or {}
        chg = q.get("change_pct", 0) or 0
        sector = code2sector.get(code, "其他")
        if sector not in ss:
            ss[sector] = {"c": 0, "ap": 0.0, "up": 0, "dn": 0}
        ss[sector]["c"] += 1
        ss[sector]["ap"] += chg
        if chg > 0:
            ss[sector]["up"] += 1
        else:
            ss[sector]["dn"] += 1
    for sec, s_info in ss.items():
        s_info["ap"] = round(s_info["ap"] / max(s_info["c"], 1), 2)

    # Step 3: 中观过滤
    from scripts.quantrisk.recommender import meso_filter, fundamental_veto
    passed, elim = meso_filter(st, CN_SECTOR_PE_THRESHOLD, code2sector, secid_prefix="cn")
    # 基本面一票否决（贯彻"基本面为主"理念）
    passed, vetoed = fundamental_veto(passed)
    passed_cnt = len(passed)

    # Step 4: 并行获取K线 → 共享原始分 → 百分位排名
    from scripts.quantrisk.recommender import _raw_score_one, percentile_score_all

    # 并行获取所有 K 线
    kline_tasks = [asyncio.create_task(cn_stock_kline_fallback(p["c"], days=365)) for p in passed]
    kline_results = await asyncio.gather(*kline_tasks, return_exceptions=True)
    kl_map = {}
    for p, result in zip(passed, kline_results):
        if isinstance(result, list) and result:
            kl_map[p["c"]] = result
        else:
            kl_map[p["c"]] = []

    # 从K线数据计算板块排名（基于近5日平均涨跌幅）
    from collections import defaultdict
    sector_5d_pcts = defaultdict(list)
    for p in passed:
        c, sec = p["c"], p["s"]
        kl = kl_map.get(c, [])
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

    # 计算原始分
    raw_scores = [
        _raw_score_one(p, kl_map.get(p["c"], []), CN_SECTOR_PE_THRESHOLD,
                       sector_ranking=sector_ranking, market="cn")
        for p in passed
    ]

    # 池内百分位排名
    scored = percentile_score_all(raw_scores)

    # 补充 kl/ind 字段
    for s in scored:
        s["kl"] = kl_map.get(s["c"], [])

    # Step 5: 格式化
    from scripts.quantrisk.recommender import build_selection_data
    raw_data = build_selection_data(ds, ss, elim, scored, passed_cnt, sector_ranking=sector_ranking, vetoed=vetoed)
    return raw_data
