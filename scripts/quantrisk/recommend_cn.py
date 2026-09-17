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

        # 生成所有可能的 A 股代码（2026-09-08 扩池：补齐科创板 688 段，
        # 否则中芯/海光等主线龙头永远进不了池）
        all_codes = []
        for i in range(600000, 606000):      # 沪市主板 600/601/603/605
            all_codes.append(f"sh{i}")
        for i in range(688000, 690000):      # 科创板 688（新增，主线半导体/算力所在）
            all_codes.append(f"sh{i}")
        for i in range(0, 4000):             # 深市主板 000/001/002/003
            all_codes.append(f"sz{i:06d}")
        for i in range(300000, 302000):      # 创业板 300/301
            all_codes.append(f"sz{i}")

        candidates = []
        batch_size = 200  # 腾讯 API 支持 200 个/批，实测可用

        for batch_start in range(0, len(all_codes), batch_size):
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
                # 当日成交额（元）：字段[35] 格式 "最新价/成交量(手)/成交额(元)"
                amount = 0.0
                if len(fields) > 35 and fields[35] and "/" in fields[35]:
                    _parts = fields[35].split("/")
                    if len(_parts) >= 3:
                        try:
                            amount = float(_parts[2])
                        except ValueError:
                            amount = 0.0

                if not code or not name:
                    continue
                # 过滤 ETF/衍生品/ST
                if any(kw in name for kw in ["ETF", "LOF", "REIT", "购", "沽", "牛", "熊"]):
                    continue
                if "ST" in name.upper() or "退" in name:
                    continue
                if price <= 0:
                    continue
                # 停牌/退市残留拦截（2026-09-08 宏源证券000562案例）：成交量(手)为 0 即停牌，
                # 行情冻结在停牌日（价格/市值是历史快照），不进候选池
                vol_hand = float(fields[36]) if len(fields) > 36 and fields[36] else 0
                if vol_hand <= 0:
                    continue
                # 流动性护栏（2026-09-17 池改造）：市值≥30亿 或 当日成交额≥1亿 才入池，
                # 剔除微盘垃圾票；配合下方成交额排序，兼顾主线龙头与活跃小盘弹性
                if mcap < 30 and amount < 1e8:
                    continue

                candidates.append({
                    "code": code,
                    "name": name,
                    "industry": "其他",
                    "market": "",
                    "mcap": mcap,
                    "amount": amount,
                    "price": price,
                    "pe": pe,
                    "sector": "其他",
                })

        # 按当日成交额降序取前 min_stocks（2026-09-17 池改造：由市值改为成交额，
        # 波段要的是活跃+动量，成交额与策略目标同构；原市值排序把 300 亿以下小盘
        # 弹性票全部挡在池外——诺德/华升这类题材股系统性漏选）
        candidates.sort(key=lambda x: x.get("amount", 0), reverse=True)
        return candidates[:min_stocks]

    except Exception as e:
        print(f"[WARN] 候选池获取失败: {e}")
        return []


# ═══════════════════════════════════════════════════════════════
# 热门板块补充池（2026-09-17 新增，用户思路落地）
#   先选热门板块（资金 5 日/当日大量净流入），再取每板块主力净流入 top3 入池，
#   与全市场成交额池补充合并。舆情交叉验证仍留 skill 层（daily 保持无 LLM）。
#   数据源：东财板块 clist 接口，push2delay 主用 + push2 兜底（2026-09-17 实测
#   push2 高频即断连，delay 域名稳定）。
# ═══════════════════════════════════════════════════════════════

# 非题材类板块噪音（风格/交易行为指数，不是可交易主线）：命中即跳过
_BOARD_NOISE_KEYWORDS = (
    "AB股", "融资融券", "深股通", "沪股通", "标普", "MSCI", "富时", "AH股",
    "QFII", "RQFII", "机构重仓", "基金重仓", "社保重仓", "百元股", "微盘股",
    "破净股", "低价股", "高价股", "昨日涨停", "昨日连板", "昨日触板", "次新股",
    "科创次新", "转融券", "转债", "可转债", "ST", "预盈预增", "送转填权",
)

_BOARD_HOSTS = ("push2delay.eastmoney.com", "push2.eastmoney.com")


async def _em_board_clist(fs: str, pz: int = 20) -> list[dict]:
    """东财板块/成分 clist 请求（按主力净流入 fid=f62 排序），多域名重试。"""
    headers = {"Referer": "https://quote.eastmoney.com/", "User-Agent": "Mozilla/5.0"}
    for host in _BOARD_HOSTS:
        try:
            connector = aiohttp.TCPConnector(force_close=True, limit=1)
            async with aiohttp.ClientSession(connector=connector, headers=headers) as session:
                async with session.get(
                    f"https://{host}/api/qt/clist/get",
                    params={"pn": 1, "pz": pz, "po": 1, "np": 1, "fltt": 2, "invt": 2,
                            "fid": "f62", "fs": fs, "fields": "f12,f14,f2,f3,f62"},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    data = (await resp.json(content_type=None)).get("data") or {}
                    return data.get("diff") or []
        except Exception:
            continue
    return []


async def fetch_hot_boards(max_boards: int = 10, per_board: int = 3) -> List[Dict[str, Any]]:
    """热门板块 top3 补充池：行业+概念板块按主力净流入各取前 max_boards，去重后
    每板块内按主力净流入取 top3 个股。返回 [{code,name,industry,sector,board_hot,...}]，
    失败返回 [] 不阻断主池（板块池是锦上添花）。"""
    boards: list[dict] = []
    for fs in ("m:90+t:2+f:!50", "m:90+t:3+f:!50"):  # 行业板块 + 概念板块
        rows = await _em_board_clist(fs, pz=max_boards + 20)
        kept = []
        for b in rows:
            name = b.get("f14") or ""
            if not name or any(kw in name for kw in _BOARD_NOISE_KEYWORDS):
                continue
            kept.append({"bk": b.get("f12"), "name": name,
                         "inflow": float(b.get("f62") or 0)})
        boards.extend(kept[:max_boards])  # 每类只取资金净流入前 max_boards 个板块（热门板块语义）
        await asyncio.sleep(0.2)
    seen_names, out = set(), []
    for b in boards:
        if b["name"] in seen_names:  # 行业/概念可能重名，去重
            continue
        seen_names.add(b["name"])
        rows = await _em_board_clist(f"b:{b['bk']}+f:!50", pz=per_board)
        for s in rows:
            code = str(s.get("f12") or "")
            sname = s.get("f14") or ""
            if not code or not sname:
                continue
            # 板块成分股 ST/退 过滤（2026-09-17 实测 ST合力泰混入电子纸概念 top3）
            if "ST" in sname.upper() or "退" in sname:
                continue
            out.append({
                "code": code, "name": s.get("f14"), "industry": b["name"],
                "market": "", "mcap": 0.0,
                "amount": float(s.get("f62") or 0),
                "price": float(s.get("f2") or 0), "pe": 0,
                "sector": b["name"], "board_hot": b["name"],
            })
        await asyncio.sleep(0.2)
    return out


def merge_pools(main_pool: List[Dict[str, Any]], board_pool: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """主池（成交额前300）与板块池按 code 去重合并；板块池标的带 board_hot 标记。"""
    seen = {c["code"] for c in main_pool}
    merged = list(main_pool)
    for c in board_pool:
        if c["code"] in seen:
            continue
        seen.add(c["code"])
        merged.append(c)
    return merged


async def fetch_cn_industry_ranking(top_n: int = 20) -> List[Dict[str, Any]]:
    """行业板块涨跌排名"""
    try:
        return await cn_industry_ranking_async(top_n=top_n)
    except Exception as e:
        print(f"[WARN] 行业排名获取失败: {e}")
        return []


async def fetch_cn_capital_flow(codes: List[str]) -> Dict[str, Dict[str, float]]:
    """批量获取 A 股个股近5日主力资金净流入（并行）"""
    async def _fetch_one(code):
        try:
            flows = await cn_fund_flow_minute_async(code)
            if flows and len(flows) > 0:
                mains = [r.get("main_net", 0) or 0 for r in flows[-5:]]
                return code, {
                    "flow_5d": sum(mains),
                    "flow_1d": mains[-1] if mains else 0,
                    "days": min(len(mains), 5),
                }
            return code, {}
        except Exception:
            return code, {}
    results_list = await asyncio.gather(*[_fetch_one(c) for c in codes], return_exceptions=True)
    return {c: v for c, v in results_list if isinstance(v, dict) and v}


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

async def cn_swing_recommend_pipeline(candidates: List[Dict[str, str]], strategy: str = "tactical", run_mode: str = "research", rule_engine: str = "shadow", snapshot: str = "") -> dict:
    """A股纯技术波段流程：日线笔 + 30分钟线段。"""
    from scripts.quantrisk.data import stock_kline_30m_async, cn_index_quotes_async
    from scripts.quantrisk.swing import run_swing_pipeline_with_intraday, build_index_sync

    # 道氏原则3·指数相互验证：上证/深证/创业板需形成合力（2026-09-08 用户框架第二步）
    index_sync = build_index_sync(await cn_index_quotes_async(), "cn")
    quote_results = await asyncio.gather(*[cn_stock_quote_tencent_async(c["code"]) for c in candidates], return_exceptions=True)
    stocks = []
    for c, quote in zip(candidates, quote_results):
        q = quote if isinstance(quote, dict) else {}
        code = c["code"]
        stocks.append({"c": code, "n": c.get("name") or q.get("name", ""),
                       "s": c.get("sector", "其他"), "p": q.get("price") or c.get("price", 0),
                       "q": q, "index_sync": index_sync,
                       "market": "cn", "strategy_id": strategy, "run_mode": run_mode,
                       "rule_engine": rule_engine,
                       "board_hot": c.get("board_hot", "")})

    async def daily_fetch(code: str):
        return await cn_stock_kline_fallback(code, days=365)

    async def flow_fetch(code: str):
        rows = await cn_fund_flow_minute_async(code)
        if not rows:
            return {}
        mains = [r.get("main_net", 0) or 0 for r in rows[-5:]]
        return {"flow_5d": sum(mains), "flow_1d": mains[-1] if mains else 0, "days": len(mains)}

    async def intraday_fetch(code: str):
        return await stock_kline_30m_async(code, "cn", range_="60d")

    return await run_swing_pipeline_with_intraday(stocks, "cn", daily_fetch, flow_fetch, intraday_fetch, snapshot_path=snapshot)


async def cn_recommend_pipeline(candidates: List[Dict[str, str]], mode: str = "value", strategy: str = "tactical", run_mode: str = "research", rule_engine: str = "shadow", snapshot: str = "") -> dict:
    """A股推荐流程；mode=swing时只走纯技术波段链路。"""
    if mode == "swing":
        return await cn_swing_recommend_pipeline(candidates, strategy=strategy, run_mode=run_mode, rule_engine=rule_engine, snapshot=snapshot)
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

    # 周线定大势（缠论结论，用于日线评分的大势权重调整）
    from scripts.quantrisk.data import cn_stock_kline_tencent_async as _cn_week_kl
    from scripts.quantrisk.indicators import chan_risk_assessment as _week_chan
    week_kl_tasks = [asyncio.create_task(_cn_week_kl(p["c"], days=260, period="week")) for p in passed]
    week_kl_results = await asyncio.gather(*week_kl_tasks, return_exceptions=True)
    week_verdict_map = {}
    for p, result in zip(passed, week_kl_results):
        if isinstance(result, list) and len(result) >= 20:
            try:
                wcv = _week_chan(result)
                week_verdict_map[p["c"]] = wcv.get("chan_verdict", "")
            except Exception:
                pass

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

    # 板块资金流汇总 + 资金排名（近5日主力净流入）
    capital_flow = await fetch_cn_capital_flow([p["c"] for p in passed])
    for sec, data in sector_ranking:
        data["flow_5d"] = 0.0
        data["stocks"] = []
    for p in passed:
        cf = capital_flow.get(p["c"], {})
        flow_5d = cf.get("flow_5d", 0) or 0
        for sec, data in sector_ranking:
            if sec == p["s"]:
                data["flow_5d"] += flow_5d
                data["stocks"].append({"code": p["c"], "name": p["n"], "flow_5d": flow_5d})
                break
    if any(d["flow_5d"] != 0 for _, d in sector_ranking):
        sector_ranking.sort(key=lambda x: x[1]["flow_5d"], reverse=True)
        for i, item in enumerate(sector_ranking):
            item[1]["flow_rank"] = i

    # 计算原始分
    raw_scores = [
        _raw_score_one(p, kl_map.get(p["c"], []), CN_SECTOR_PE_THRESHOLD,
                       sector_ranking=sector_ranking, market="cn", capital_flow=capital_flow,
                       week_verdict=week_verdict_map.get(p["c"], ""))
        for p in passed
    ]

    # 池内百分位排名
    scored = percentile_score_all(raw_scores)

    # 补充 kl/ind 字段
    for s in scored:
        s["kl"] = kl_map.get(s["c"], [])
        cf = capital_flow.get(s["c"], {})
        s["flow_5d"] = cf.get("flow_5d", 0) or 0
        s["flow_1d"] = cf.get("flow_1d", 0) or 0
        s["flow_days"] = cf.get("days", 0) or 0
        if s.get("cd"):
            s["cd"]["week_chan_verdict"] = week_verdict_map.get(s["c"], "")

    # Step 5: 格式化
    from scripts.quantrisk.recommender import build_selection_data
    raw_data = build_selection_data(ds, ss, elim, scored, passed_cnt, sector_ranking=sector_ranking, vetoed=vetoed)
    return raw_data
