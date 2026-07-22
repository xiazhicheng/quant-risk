#!/usr/bin/env python3
"""
港股推荐脚本 — 完整执行 SKILL.md 三步强制流程

V2.0 核心改进:
  - 动态候选池: 从东财按成交额排序拉取 300+ 只港股，替代硬编码 114 只
  - HKSectorMapper: 名称关键词自动分类到 8 个板块
  - 核心池 + 动态池双层结构，保证覆盖面 + 新鲜度

  Step 1: 跨板块全市场扫描（8个板块，动态 300+ 只标的）
  Step 2: 中观硬约束过滤（市值≥50亿HKD，股价≥1 HKD，PE≤80，标记净利恶化）
  Step 3: 微观三维评分排序（基本面×5 + 热点×3 + 缠论×2）→ TOP10
"""
from __future__ import annotations

import asyncio, json, sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
# Ensure project root is on sys.path so `scripts.*` imports work
sys.path.insert(0, str(Path(__file__).parent.parent))

CACHE_FILE = Path(__file__).parent.parent / ".hk_dynamic_pool_cache.json"

# 行业 PE 阈值 — 超出标记但不淘汰，基本面评分会扣分
# 依据各行业典型估值区间设定
SECTOR_PE_THRESHOLD = {
    "金融/保险/券商": 15,   # 银行保险 PE 本身就低
    "能源/资源/矿业": 25,   # 周期性
    "公用事业/基建/交运": 25,  # 稳定分红低增长
    "通信/运营商": 25,
    "消费/食品/零售": 50,
    "互联网/IT": 60,        # 研发投入大，净利被摊薄
    "制造/工业/半导体": 60, # 周期性波动
    "医药/生物科技": 150,   # 研发周期长，净利前期很小
    "其他": 60,
}

from scripts.quantrisk.data import (hk_stock_quote_tencent_async, hk_kline_tencent_async,
                                     stock_kline_yahoo_async, kline_tickflow_async,
                                     parallel_map, key_indicators_eastmoney_async,
                                     close_async_session, close_tickflow)

# 共享评分引擎（三市场统一使用百分位排名）
from scripts.quantrisk.recommender import (
    _raw_score_one, percentile_score_all, quality_screen,
    meso_filter as shared_meso_filter,
    fundamental_veto,
)

# ── 格式化引擎（Pydantic 校验 + 渲染） ──────────────────────
from scripts.formatter import format_output, FormatValidationError


# ═══════════════════════════════════════════════════════════════
# 核心池（已分类的 114 只 — 保持向后兼容）
# ═══════════════════════════════════════════════════════════════

CORE_SECTORS = {
    "互联网/IT": ["00700", "09988", "03690", "09999", "01810", "01024", "09618", "09888",
                   "09626", "03888", "06618", "02013", "00268", "00354", "00772", "00777", "01698"],
    "金融/保险/券商": ["00005", "01299", "00388", "01398", "03988", "00939", "03968", "02318",
                       "02628", "02601", "00998", "06881", "02328", "01339", "06060", "03908",
                       "06099", "01776", "01336", "06030"],
    "能源/资源/矿业": ["00883", "00857", "02899", "03993", "01171", "02600", "00753",
                       "01378", "01071", "01818", "01208", "00811", "01258"],
    "通信/运营商": ["00941", "00728", "00762", "00552", "02342"],
    "消费/食品/零售": ["09633", "06862", "02319", "02020", "02313", "02331", "09992",
                       "06690", "01044", "00168", "06186", "00151", "00288", "01876",
                       "02209", "09987", "06969", "03328"],
    "医药/生物科技": ["06160", "02269", "01093", "01177", "01801", "06185", "03692",
                       "09926", "01873", "00013", "00867", "01548", "06618", "02696"],
    "制造/工业/半导体": ["01211", "02382", "00175", "00981", "01347", "02338", "03808",
                         "00669", "00425", "00968", "01357", "02333", "02238", "00763"],
    "公用事业/基建/交运": ["00002", "00006", "01038", "02638", "01308", "02688",
                           "00316", "00836", "00916", "00914", "01199", "01919", "00670"],
}
CORE_CODES = sum(CORE_SECTORS.values(), [])
CORE_MAP = {c: s for s, codes in CORE_SECTORS.items() for c in codes}


# ═══════════════════════════════════════════════════════════════
# HKSectorMapper — 名称关键词分类器
# ═══════════════════════════════════════════════════════════════

# 关键词规则（按优先级从高到低排列）
KEYWORD_RULES = [
    ("金融/保险/券商",
     ["银行", "保险", "证券", "券商", "金融", "信托", "资产管理", "投资银行",
      "资本", "信贷", "地产", "置地", "房产", "置业", "物业",
      "房地产", "汇丰", "恒生", "招行", "交行", "工行", "中行", "建行",
      "农行", "平安", "人寿", "太保", "人保", "新华保险", "中国太平"]),
    ("医药/生物科技",
     ["医药", "生物科技", "生物", "制药", "药业", "医疗", "医", "健康产业",
      "药", "医疗器械", "医养", "生命科学", "药明", "康希诺", "百济神州",
      "信达生物", "翰森", "中国生物制药", "石药", "白云山", "同仁堂"]),
    ("通信/运营商",
     ["移动", "联通", "电信", "通信服务", "运营商", "电讯", "中国移动",
      "中国联通", "中国电信", "中移动"]),
    ("互联网/IT",
     ["科技", "互联网", "信息", "软件", "数字", "计算机", "智能",
      "数据", "云计算", "网络", "数码", "电子", "半导体", "芯片",
      "人工智能", "AI", "IT", "媒体", "传媒", "出版", "广告",
      "腾讯", "阿里", "百度", "京东", "网易", "美团", "快手",
      "小米", "商汤", "金山", "联想", "中兴", "中芯", "华虹",
      "阅文", "美图", "微盟", "金蝶", "用友"]),
    ("能源/资源/矿业",
     ["能源", "石油", "煤炭", "矿业", "资源", "原油", "石化",
      "天然气", "煤气", "有色金属", "钢铁", "黄金", "金属",
      "新能源", "光伏", "风电", "锂", "电池", "中海油", "中石油",
      "中石化", "紫金", "洛钼", "宏桥", "江铜", "山金"]),
    ("制造/工业/半导体",
     ["制造", "工业", "重工", "机械", "装备", "电气", "自动化",
      "航空", "航天", "汽车", "中车", "半导体", "芯片", "电子制造",
      "精密", "光电", "新能源车", "动力", "新材料", "比亚迪",
      "创科", "舜宇", "瑞声", "建滔", "美的", "宁德"]),
    ("消费/食品/零售",
     ["食品", "饮料", "乳业", "啤酒", "白酒", "零售", "超市",
      "消费", "家电", "酒店", "餐饮", "服饰", "时装", "体育",
      "用品", "教育", "培训", "旅游", "娱乐", "博彩", "电影", "游戏",
      "携程", "泡泡玛特", "農夫山泉", "蒙牛", "康师傅", "统一",
      "华润啤酒", "百威", "青岛啤酒", "安踏", "李宁", "海底捞",
      "银河娱乐", "金沙"]),
    ("公用事业/基建/交运",
     ["电力", "水务", "燃气", "基建", "铁路", "公路", "高速",
      "港口", "物流", "机场", "交通", "运输", "公用", "航运",
      "航空", "地铁", "巴士", "快递", "速运", "环保", "环境",
      "建筑", "工程", "建设", "华润电力", "中电", "煤气", "港铁"]),
]


def classify_hk_stock(code: str, name: str) -> str:
    """将港股分类到 8 个板块之一

    优先级: 核心池 > 名称关键词匹配 > 兜底
    """
    # 1. 核心池优先
    if code in CORE_MAP:
        return CORE_MAP[code]

    # 2. 名称关键词匹配
    for sector, keywords in KEYWORD_RULES:
        for kw in keywords:
            if kw in name:
                return sector

    # 3. 兜底
    return "其他"


def save_dynamic_pool_cache(pool: list[dict]):
    """缓存动态池到本地文件"""
    try:
        data = [{"code": s["code"], "name": s["name"], "price": s.get("price"),
                 "amount": s.get("amount"), "sector": s.get("sector")} for s in pool]
        CACHE_FILE.write_text(json.dumps(data, ensure_ascii=False))
    except Exception:
        pass


def load_dynamic_pool_cache() -> list[dict] | None:
    """从本地缓存加载动态池"""
    try:
        if not CACHE_FILE.exists():
            return None
        data = json.loads(CACHE_FILE.read_text())
        if not data or len(data) < 50:
            return None
        return data
    except Exception:
        return None


def sf(v, d=0.0):
    try: return float(v) if v not in (None, "-", "", 0, "0") else d
    except: return d


def fmt(v):
    try: return round(float(v), 2) if v not in ("", "-", None, 0, "0") else "-"
    except: return "-"


# ═══════════════════════════════════════════════════════════════
# 动态候选池 — 从东财按成交额排序拉取
# ═══════════════════════════════════════════════════════════════

async def _fetch_page_eastmoney(page: int, page_size: int = 100) -> list[dict]:
    """用 subprocess shell 调 curl 拉取东财港股成交额排名"""
    import json
    url = (f"https://push2.eastmoney.com/api/qt/clist/get?"
           f"fs=m:116&fields=f2,f3,f6,f12,f14"
           f"&pn={page}&pz={page_size}&fid=f6&po=1")
    try:
        proc = await asyncio.create_subprocess_shell(
            f"/usr/bin/curl -s --max-time 15 '{url}'",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=20)
        if not stdout or len(stdout) < 50:
            return []
        d = json.loads(stdout.decode())
    except Exception as e:
        print(f"  [WARN] 东财API请求失败(page={page}): {e}")
        return []
    diff = d.get("data", {}).get("diff", []) or []
    if isinstance(diff, dict):
        diff = list(diff.values())
    stocks = []
    for i in diff:
        name = (i.get("f14") or "").strip()
        code = i.get("f12", "")
        if not name or not code:
            continue
        stocks.append({
            "code": code,
            "name": name,
            "price": i.get("f2"),
            "amount": i.get("f6"),
        })
    return stocks


def _is_derivative_or_etf(name: str, code: str) -> bool:
    """判断是否为衍生品/ETF（应跳过）"""
    if any(kw in name for kw in ["购", "沽", "牛", "熊"]):
        return True
    if name.endswith("ETF") or "ETF" in name or "ETN" in name:
        return True
    # 07xxx / 08xxx / 09xxx 多为 ETF / 债券，跳过除非名称含明显行业词
    if code.startswith(("07", "08", "09")) and len(code) == 5:
        industry_kw = ["银行", "保险", "医药", "科技", "消费", "能源", "电力", "石油"]
        if not any(kw in name for kw in industry_kw):
            return True
    return False


async def fetch_dynamic_pool(min_stocks: int = 300) -> list[dict]:
    """从东财按成交额排序，动态拉取港股候选池

    返回: [{code, name, amount, price, sector}, ...]
    """
    all_stocks = []
    seen_codes = set()
    page = 1
    page_size = 100
    max_pages = 5  # 最多拉 500 只

    while len(all_stocks) < min_stocks and page <= max_pages:
        try:
            stocks = await _fetch_page_eastmoney(page, page_size)
        except Exception:
            break

        if not stocks:
            break

        new_count = 0
        for s in stocks:
            code = s["code"]
            name = s["name"]
            price = s.get("price") or 0

            if price <= 0:
                continue
            if code in seen_codes:
                continue
            if _is_derivative_or_etf(name, code):
                continue

            seen_codes.add(code)
            sector = classify_hk_stock(code, name)
            s["sector"] = sector
            all_stocks.append(s)
            new_count += 1

        page += 1

    if all_stocks:
        save_dynamic_pool_cache(all_stocks)
    return all_stocks


def build_sectors_from_pool(dynamic_pool: list[dict]) -> dict[str, list[str]]:
    """从动态候选池构建板块 → 代码列表映射"""
    sectors = {name: [] for name in CORE_SECTORS}
    sectors["其他"] = []
    seen = set()

    # 1. 先加核心池（确保核心标的永远在）
    for code in CORE_CODES:
        seen.add(code)
        sector = CORE_MAP.get(code, "其他")
        sectors.setdefault(sector, []).append(code)

    # 2. 再加动态池新股
    for item in dynamic_pool:
        code = item["code"]
        if code in seen:
            continue
        seen.add(code)
        sector = item.get("sector", "其他")
        sectors.setdefault(sector, []).append(code)

    # 移除空板块
    sectors = {k: v for k, v in sectors.items() if v}
    return sectors


# ═══════════════════════════════════════════════════════════════
# 扫描、过滤、评分（复用 V1.x 逻辑）
# ═══════════════════════════════════════════════════════════════

async def fetch_all(all_codes: list[str]) -> dict[str, dict]:
    """并行获取行情 + 基本面"""
    # 进度信息不再输出
    pass
    qf = [lambda c=c: hk_stock_quote_tencent_async(c) for c in all_codes]
    secucodes = [f"{c}.HK" for c in all_codes]
    inf = [lambda s=s: key_indicators_eastmoney_async(s) for s in secucodes]
    qr, ir = await parallel_map(qf), await parallel_map(inf)
    st = {}
    for i, c in enumerate(all_codes):
        q = qr[i] if isinstance(qr[i], dict) else {}
        ind = (ir[i][0] if isinstance(ir[i], list) and ir[i] else {})
        st[c] = {"q": q, "ind": ind}
    return st


def meso_filter(st: dict, sectors: dict, code2sector: dict) -> tuple[list, list]:
    """中观硬约束过滤 — 市值、股价硬门槛；PE 按行业阈值标记但不淘汰。"""
    passed, elim = [], []
    for c, s in st.items():
        q, ind = s["q"], s["ind"]
        nm = q.get("name", "?")
        pr = sf(q.get("price"))
        mc = sf(q.get("market_cap_100m"))
        pe = sf(q.get("pe"))
        ny = sf(ind.get("HOLDER_PROFIT_YOY"))
        sec = code2sector.get(c, "其他")

        rs = []
        if mc > 0 and mc < 50: rs.append(f"市值{mc:.0f}亿<50亿")
        if pr > 0 and pr < 1: rs.append(f"股价{pr:.2f}<1HKD")

        pw = []
        if ny < -0.5:
            pw.append(f"⚠️净利同比{ny:.2f}%（恶化）")
        # PE 按行业阈值判断：超过则标记但不淘汰
        pe_limit = SECTOR_PE_THRESHOLD.get(sec, SECTOR_PE_THRESHOLD["其他"])
        if pe > pe_limit:
            pw.append(f"⚠️PE{pe:.0f}>行业阈值{pe_limit}（{sec}）")

        pw_str = "; ".join(pw) if pw else ""
        if rs:
            elim.append((c, nm, "; ".join(rs)))
        else:
            passed.append({"c": c, "n": nm, "s": sec,
                           "p": pr, "mc": mc, "pe": pe, "ny": ny,
                           "rev": sf(ind.get("OPERATE_INCOME_YOY")),
                           "pw": pw_str, "q": q, "ind": ind})
    return passed, elim


def _fmt_num(v):
    """安全数值格式化"""
    try:
        if v in (None, "-", "", 0, "0"):
            return "?"
        return round(float(v), 2)
    except (ValueError, TypeError):
        return "?"


def build_selection_data(ds, ss, elim, scored, passed_cnt, sector_ranking=None, vetoed=None):
    """将内部数据结构转为 format_output() 所需的 JSON Schema。

    返回的 dict 结构:
        {date, sectors[], eliminated[], vetoed[], passed_count, top10[], details[], summary[]}

    Args:
        vetoed: 基本面一票否决的标的 [(code, name, reason)]
    """
    from scripts.quantrisk.indicators import calc_stop_loss_take_profit

    top10 = scored[:10]

    # ── sectors ──
    sectors_data = []
    for sec_name, s_info in ss.items():
        sectors_data.append({
            "sector": sec_name,
            "count": s_info.get("c", 0),
            "pct": round(s_info.get("ap", 0), 2),
            "up": s_info.get("up", 0),
            "dn": s_info.get("dn", 0),
        })

    # ── eliminated ──
    eliminated_data = [{"code": c, "name": n, "reason": r} for c, n, r in elim]

    # ── top10 ──
    top10_data = []
    for i, s in enumerate(top10):
        t = s["total"]
        advice = "强烈关注" if t >= 70 else ("可关注" if t >= 56 else ("观察" if t >= 44 else "回避"))
        top10_data.append({
            "rank": i + 1,
            "code": s["c"],
            "name": s["n"],
            "sector": s["s"],
            "fb": s["fb"],
            "hot": s["hot"],
            "ch": s["ch"],
            "fb_w": s.get("fb_w", round(s["fb"] * 12, 1)),
            "hot_w": s.get("hot_w", round(s["hot"] * 4, 1)),
            "ch_w": s.get("ch_w", round(s["ch"] * 4, 1)),
            "total": t,
            "advice": advice,
        })

    # ── details (top 5) ──
    details_data = []
    for s in top10[:5]:
        idx = scored.index(s) + 1
        chg = sf(s.get("q", {}).get("change_pct", 0))
        ind = s.get("ind", {})
        d = s.get("cd", {})

        kl = s.get("kl", [])
        sltp = {}
        if kl and len(kl) >= 20:
            sltp = calc_stop_loss_take_profit(entry_price=s["p"], klines=kl[-60:])
        sl_point = sltp.get("stop_loss") or round(s["p"] * 0.92, 2)
        tp_point = sltp.get("take_profit") or round(s["p"] * 1.15, 2)
        t = s["total"]
        advice = ("强烈关注，适合布局" if t >= 70 else
                  "可适当关注，等待入场时机" if t >= 56 else
                  "纳入观察清单，等待催化剂" if t >= 44 else "暂时回避，等待改善")

        # 热点描述 — 基于近5日成交额变化+收盘价变化（替代资金流向）
        kl_s = s.get("kl", [])
        vol_5d_ratio = 1.0
        pct_5d = 0.0
        if kl_s and len(kl_s) >= 10:
            recent_5_vol = sum(k.get("volume", 0) or 0 for k in kl_s[-5:])
            prev_5_vol = sum(k.get("volume", 0) or 0 for k in kl_s[-10:-5])
            if prev_5_vol > 0 and recent_5_vol > 0:
                vol_5d_ratio = recent_5_vol / prev_5_vol
        if kl_s and len(kl_s) >= 6:
            c5 = kl_s[-6].get("close", 0) or 0
            c0 = kl_s[-1].get("close", 0) or 0
            if c5 > 0:
                pct_5d = (c0 - c5) / c5 * 100

        if vol_5d_ratio > 2.0:
            vol_desc = f"放巨量({vol_5d_ratio:.1f}x)"
        elif vol_5d_ratio > 1.5:
            vol_desc = f"放量({vol_5d_ratio:.1f}x)"
        elif vol_5d_ratio < 0.5:
            vol_desc = f"缩量({vol_5d_ratio:.1f}x)"
        else:
            vol_desc = f"量平({vol_5d_ratio:.1f}x)"

        pct_desc = f"{'+' if pct_5d >= 0 else ''}{pct_5d:.2f}%"
        hot_desc = f"{s['s']}板块 5日量{vol_desc} | 5日涨幅{pct_desc}"

        # 缠论信号
        v_str = str(d.get("v", ""))
        sig = v_str if v_str and v_str != "等待信号" else "macd待确认"
        macd_hist = d.get("mh", "?")
        ma60 = d.get("ma60", "?")
        ma60 = _fmt_num(ma60) if ma60 != "?" else "?"

        details_data.append({
            "rank": idx,
            "code": s["c"],
            "name": s["n"],
            "price": _fmt_num(s.get("p")),
            "pct": chg,
            "advice": advice,
            "stop_loss": sl_point,
            "take_profit": tp_point,
            "total": s["total"],
            "fb": {
                "score": s["fb"],
                "score_w": s.get("fb_w", round(s["fb"] * 12, 1)),
                "debug": s.get("fb_debug", ""),
                "pe": _fmt_num(s.get("pe")),
                "revenue_yoy": _fmt_num(s.get("rev")),
                "net_profit_yoy": _fmt_num(s.get("ny")),
                "roe": _fmt_num(ind.get("ROE") or ind.get("JQROE")),
                "gross_margin": _fmt_num(ind.get("GROSS_PROFIT_RATIO")),
                "debt_ratio": _fmt_num(ind.get("DEBT_ASSET_RATIO")),
                # 六维评分（2026-07-22 重构）
                "dim1_score": _fmt_num(s.get("dim1")),
                "dim2_score": _fmt_num(s.get("dim2")),
                "dim3_score": _fmt_num(s.get("dim3")),
                "dim4_score": _fmt_num(s.get("dim4")),
                "dim5_score": _fmt_num(s.get("dim5")),
                "dim6_score": _fmt_num(s.get("dim6")),
                "dim1_debug": s.get("dim1_debug", ""),
                "dim2_debug": s.get("dim2_debug", ""),
                "dim3_debug": s.get("dim3_debug", ""),
                "dim4_debug": s.get("dim4_debug", ""),
                "dim5_debug": s.get("dim5_debug", ""),
                "dim6_debug": s.get("dim6_debug", ""),
                "dim1_conclusion": s.get("dim1_conclusion", ""),
                "dim2_conclusion": s.get("dim2_conclusion", ""),
                "dim3_conclusion": s.get("dim3_conclusion", ""),
                "dim4_conclusion": s.get("dim4_conclusion", ""),
                "dim5_conclusion": s.get("dim5_conclusion", ""),
                "dim6_conclusion": s.get("dim6_conclusion", ""),
                "dim1_confidence": s.get("dim1_confidence", ""),
                "dim2_confidence": s.get("dim2_confidence", ""),
                "dim3_confidence": s.get("dim3_confidence", ""),
                "dim4_confidence": s.get("dim4_confidence", ""),
                "dim5_confidence": s.get("dim5_confidence", ""),
                "dim6_confidence": s.get("dim6_confidence", ""),
                # 大师视角 + 其他大师质疑（2026-07-22 新增）
                "dim1_master_view": s.get("dim1_master_view", ""),
                "dim2_master_view": s.get("dim2_master_view", ""),
                "dim3_master_view": s.get("dim3_master_view", ""),
                "dim4_master_view": s.get("dim4_master_view", ""),
                "dim5_master_view": s.get("dim5_master_view", ""),
                "dim6_master_view": s.get("dim6_master_view", ""),
                "dim1_other_masters": s.get("dim1_other_masters", ""),
                "dim2_other_masters": s.get("dim2_other_masters", ""),
                "dim3_other_masters": s.get("dim3_other_masters", ""),
                "dim4_other_masters": s.get("dim4_other_masters", ""),
                "dim5_other_masters": s.get("dim5_other_masters", ""),
                "dim6_other_masters": s.get("dim6_other_masters", ""),
                # 芒格式逆向检验
                "reverse_test": s.get("reverse_test", ""),
                # 质量筛选问题
                "quality_issues": s.get("quality_issues", []),
                # 信息丰富度评级
                "info_richness": s.get("info_richness", "?"),
                "info_richness_detail": s.get("info_richness_detail", ""),
            },
            "hot": {
                "score": s["hot"],
                "score_w": s.get("hot_w", round(s["hot"] * 4, 1)),
                "desc": hot_desc,
            },
            "ch": {
                "score": s["ch"],
                "score_w": s.get("ch_w", round(s["ch"] * 4, 1)),
                "ma60": ma60,
                "price": _fmt_num(s.get("p")),
                "macd_hist": _fmt_num(macd_hist) if macd_hist != "?" else "?",
                "signal": sig,
                "ma_alignment": d.get("ma_alignment", ""),
                "ma_trend": d.get("ma_trend", ""),
                "mc": d.get("mc", ""),
                "ma_pos_summary": d.get("ma_pos_summary", ""),
                "ma_cross_short": d.get("ma_cross_short", ""),
                "ma_cross_medium": d.get("ma_cross_medium", ""),
                # 深度缠论（2026-07-21 新增）
                "week_ma60": d.get("week_ma60", "?"),
                "week_chan_verdict": d.get("week_chan_verdict", ""),
                "day_ma5": _fmt_num(d.get("ma5")),
                "day_bottom_fx": _fmt_num(d.get("day_bottom_fx")),
                "day_top_fx": _fmt_num(d.get("day_top_fx")),
                "day_bottom_fx_date": d.get("day_bottom_fx_date", ""),
                "day_last_bi_dir": d.get("day_last_bi_dir", ""),
                "day_above_ma5": bool(d.get("day_above_ma5", False)),
                "buy_sell_detail": d.get("buy_sell_detail", ""),
                "divergence_detail": d.get("divergence_detail", ""),
                "chan_verdict": d.get("chan_verdict", ""),
            },
            "vol_5d_ratio": round(vol_5d_ratio, 2),
            "pct_5d": round(pct_5d, 2),
        })

    # ── summary ──
    summary_data = []
    for s in top10:
        kl = s.get("kl", [])
        sltp = {}
        if kl and len(kl) >= 20:
            sltp = calc_stop_loss_take_profit(entry_price=s["p"], klines=kl[-60:])
        sl_point = sltp.get("stop_loss") or round(s["p"] * 0.92, 2)
        tp_point = sltp.get("take_profit") or round(s["p"] * 1.15, 2)
        t = s["total"]
        advice = "强烈关注" if t >= 70 else ("可关注" if t >= 56 else ("观察" if t >= 44 else "回避"))
        summary_data.append({
            "code": f"{s['c']} {s['n']}",
            "advice": advice,
            "buy": _fmt_num(s.get("p")),
            "stop_loss": sl_point,
            "take_profit": tp_point,
        })

    # 基本面一票否决记录
    vetoed_data = [{"code": c, "name": n, "reason": r} for c, n, r in (vetoed or [])]

    return {
        "date": ds,
        "sectors": sectors_data,
        "eliminated": eliminated_data,
        "vetoed": vetoed_data,
        "passed_count": passed_cnt,
        "top10": top10_data,
        "details": details_data,
        "summary": summary_data,
    }


async def _fetch_klines(c: str) -> Tuple[str, List[Dict], List[Dict]]:
    """异步获取单只股票K线（备选链: 腾讯 > Yahoo > TickFlow）。

    Returns: (code, kl_daily, kl_weekly)
    """
    kl = None
    # 日K
    try:
        kl = await hk_kline_tencent_async(c, "day", 365)
        if kl and len(kl) < 20:
            kl = None
    except Exception:
        kl = None
    if not kl:
        try:
            kl = await stock_kline_yahoo_async(f"{int(c)}.HK", "1d", "1y")
            if kl and len(kl) < 20:
                kl = None
        except Exception:
            kl = None
    if not kl:
        try:
            kl = await kline_tickflow_async(f"{c}.HK", "1d", 365)
            if kl and len(kl) < 20:
                kl = None
        except Exception:
            kl = None

    # 周K（仅腾讯，用于缠论大势判断）
    kl_week = None
    try:
        kl_week = await hk_kline_tencent_async(c, "week", 120)
        if kl_week and len(kl_week) < 10:
            kl_week = None
    except Exception:
        kl_week = None

    return c, kl or [], kl_week or []


async def score_all_passed(
    passed: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """对全部候选股先并行获取K线，再用共享评分引擎（百分位排名）。"""
    # Step 1: 并行获取 K 线（日K + 周K）
    kline_tasks = [asyncio.create_task(_fetch_klines(p["c"])) for p in passed]
    kline_results = await asyncio.gather(*kline_tasks)
    kl_map = {c: kl for c, kl, _ in kline_results}
    kl_week_map = {c: klw for c, _, klw in kline_results}

    # 从K线数据计算板块排名（基于近5日平均涨跌幅，替代资金流向排名）
    sector_5d_pcts = {}
    for p in passed:
        c, sec = p["c"], p["s"]
        kl = kl_map.get(c, [])
        if kl and len(kl) >= 6:
            c5 = kl[-6].get("close", 0) or 0
            c0 = kl[-1].get("close", 0) or 0
            if c5 > 0:
                pct_5d = (c0 - c5) / c5 * 100
                if sec not in sector_5d_pcts:
                    sector_5d_pcts[sec] = []
                sector_5d_pcts[sec].append(pct_5d)
    sector_ranking = []
    for sec, pcts in sector_5d_pcts.items():
        avg_5d = sum(pcts) / len(pcts) if pcts else 0
        sector_ranking.append((sec, {"avg_5d_pct": avg_5d, "stock_count": len(pcts)}))
    sector_ranking = sorted(sector_ranking, key=lambda x: x[1]["avg_5d_pct"], reverse=True)
    for i, item in enumerate(sector_ranking):
        item[1]["rank"] = i

    # Step 2: 计算原始分（调用 recommender 共享函数）
    raw_scores = [
        _raw_score_one(p, kl_map.get(p["c"], []), SECTOR_PE_THRESHOLD,
                       sector_ranking=sector_ranking, market="hk")
        for p in passed
    ]

    # Step 3: 池内百分位排名
    scored = percentile_score_all(raw_scores)

    # Step 3b: 质量筛选（基于5条硬指标降档标记）
    scored = quality_screen(scored)

    # 补充 cd/kl/q/ind 字段（build_selection_data 需要）
    kl_map = {r["c"]: r["kl"] for r in raw_scores}
    cd_map = {r["c"]: r["cd"] for r in raw_scores}
    passed_map = {p["c"]: p for p in passed}

    # 计算周线缠论数据（大势判断）
    from scripts.quantrisk.indicators import calc_ma as _calc_ma, chan_risk_assessment as _chan_risk

    def _fmt_chan_week(cd: dict, kl_week: list) -> dict:
        """计算周线缠论并合并到 cd 字典。"""
        if not kl_week or len(kl_week) < 10:
            return cd
        try:
            wk_ma = _calc_ma(kl_week, [60])
            if wk_ma:
                cd["week_ma60"] = round(wk_ma[-1].get("ma60", 0), 2)
            wk_cv = _chan_risk(kl_week)
            cd["week_chan_verdict"] = wk_cv.get("chan_verdict", "")
        except Exception:
            pass
        return cd

    for s in scored:
        s["cd"] = cd_map.get(s["c"], {})
        s["kl"] = kl_map.get(s["c"], [])
        p = passed_map.get(s["c"], {})
        s["q"] = p.get("q", {})
        s["ind"] = p.get("ind", {})
        # 合并周线数据
        kl_week = kl_week_map.get(s["c"], [])
        s["cd"] = _fmt_chan_week(s["cd"], kl_week)

        # ── 返回评分结果 ──
        return scored


# ═══════════════════════════════════════════════════════════════
# 港股推荐 Pipeline（可被 recommend.py 统一调用）
# ═══════════════════════════════════════════════════════════════

async def hk_recommend_pipeline(min_stocks: int = 300, industry: str = "") -> dict:
    """港股推荐完整流程，返回 raw_data dict（与 cn_recommend_pipeline 格式一致）。

    三步强制流程:
      ① 跨板块全市场扫描（8个板块，动态 300+ 只标的）
      ② 中观硬约束过滤（市值≥50亿HKD，股价≥1 HKD）+ 基本面一票否决（营收/净利崩盘者直接淘汰）
      ③ 微观三维评分排序（基本面×5 + 热点×3 + 缠论×2）→ TOP10

    Args:
        min_stocks: 最小候选池规模
        industry: 行业名称，指定时只对该行业做漏斗筛选（如"能源/资源/矿业"）

    Returns:
        {date, sectors[], eliminated[], vetoed[], passed_count, top10[], details[], summary[], funnel?}
    """
    ds = datetime.now().strftime("%Y-%m-%d")
    funnel = {"industry": industry, "scan_count": 0, "after_filter": 0, "after_veto": 0}

    # ── 动态候选池 ──
    dynamic_pool = await fetch_dynamic_pool(min_stocks=min_stocks)
    if not dynamic_pool:
        dynamic_pool = load_dynamic_pool_cache() or []

    # ── 构建板块映射 ──
    sectors = build_sectors_from_pool(dynamic_pool)
    all_codes = sum(sectors.values(), [])
    code2sector = {c: s for s, codes in sectors.items() for c in codes}

    # ── 行业漏斗过滤 ──
    if industry:
        target_codes = [c for c in all_codes if code2sector.get(c) == industry]
        if not target_codes:
            print(f"⚠️ 行业 '{industry}' 未找到对应标的，使用全市场")
        else:
            all_codes = target_codes
            funnel["scan_count"] = len(all_codes)
            # 只保留该板块的sectors
            sectors = {industry: [c for c in sectors.get(industry, []) if c in all_codes]} if industry in sectors else {}
            print(f"📋 行业漏斗筛选: {industry}（{len(all_codes)} 只）")
    else:
        funnel["scan_count"] = len(all_codes)

    # ── Step 1: 全市场扫描 ──
    st = await fetch_all(all_codes)

    # ── 板块表现 ──
    ss = {}
    for sec, codes in sectors.items():
        chs = [sf(st[c]["q"].get("change_pct")) for c in codes if st.get(c, {}).get("q", {}).get("name")]
        ap = sum(chs) / len(chs) if chs else 0
        up = sum(1 for ch in chs if ch > 0)
        ss[sec] = {"c": len(chs), "ap": round(ap, 2), "up": up, "dn": len(chs) - up}

    # ── Step 2a: 中观硬约束过滤（市值≥50亿，股价≥1HKD） ──
    passed, elim = shared_meso_filter(st, SECTOR_PE_THRESHOLD, code2sector,
                                      field_map={"q": "q", "ind": "ind"})
    funnel["after_filter"] = len(passed)

    # ── Step 2b: 基本面一票否决（营收/净利崩盘者直接淘汰） ──
    # 贯彻"基本面为主"理念：技术面和热点再强，基本面崩塌的股票也不进评分池
    passed, vetoed = fundamental_veto(passed)
    funnel["after_veto"] = len(passed)

    # ── Step 3: 并行评分（K线→板块排名→评分→百分位排名→策略检查）
    scored = await score_all_passed(passed)

    # ── Step 3b: 关键数据多源交叉验证（TOP5 标的，腾讯 vs Yahoo）
    cross_validate_results = []
    try:
        from scripts.quantrisk.data import batch_cross_validate_hk
        top5_codes = [s["c"] for s in scored[:5]]
        cross_validate_results = await batch_cross_validate_hk(top5_codes)
    except Exception:
        cross_validate_results = []

    # ── 构建裸数据 ──
    raw_data = build_selection_data(ds, ss, elim, scored, len(passed),
                                    vetoed=vetoed)
    # 追加行业漏斗数据
    if industry:
        raw_data["funnel"] = funnel
    # 追加交叉验证结果
    if cross_validate_results:
        raw_data["cross_validation"] = cross_validate_results
    return raw_data


async def main():
    raw_data = await hk_recommend_pipeline(min_stocks=300)
    try:
        report = format_output(raw_data)
        print(report)
    except FormatValidationError as e:
        print(f"\n{'=' * 60}")
        print("❌ 数据格式校验失败，需修正 JSON 结构后重试")
        print(f"{'=' * 60}")
        print(e.message)
        print(f"{'=' * 60}\n")
        raise
    await close_async_session()
    await close_tickflow()


if __name__ == "__main__":
    import gc
    asyncio.run(main())
    asyncio.run(close_async_session())
    asyncio.run(close_tickflow())
    gc.collect()