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
# Ensure project root is on sys.path so `scripts.*` imports work
sys.path.insert(0, str(Path(__file__).parent.parent))

CACHE_FILE = Path(__file__).parent / ".hk_dynamic_pool_cache.json"

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
                                     batch_hk_capital_flow_async,
                                     close_async_session, close_tickflow)
from scripts.quantrisk.indicators import calc_ma, calc_macd, chan_risk_assessment

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


def build_selection_data(ds, ss, elim, scored, passed_cnt, capital_flow, sector_ranking):
    """将内部数据结构转为 format_output() 所需的 JSON Schema。

    返回的 dict 结构:
        {date, sectors[], eliminated[], passed_count, top10[], details[], summary[]}
    """
    from scripts.quantrisk.indicators import calc_stop_loss_take_profit

    top10 = scored[:10]
    flow_all_zero = all(abs(v) < 1e4 for v in (capital_flow or {}).values()) if capital_flow else True

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
        advice = "强烈关注" if t >= 35 else ("可关注" if t >= 28 else ("观察" if t >= 22 else "回避"))
        top10_data.append({
            "rank": i + 1,
            "code": s["c"],
            "name": s["n"],
            "sector": s["s"],
            "fb": s["fb"],
            "hot": s["hot"],
            "ch": s["ch"],
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
        advice = ("强烈关注，适合布局" if t >= 35 else
                  "可适当关注，等待入场时机" if t >= 28 else
                  "纳入观察清单，等待催化剂" if t >= 22 else "暂时回避，等待改善")

        # 热点描述
        if flow_all_zero:
            kl_s = s.get("kl", [])
            vr = 1.0
            if kl_s and len(kl_s) >= 21:
                vols = [k.get("volume", 0) for k in kl_s[-21:]]
                if vols and vols[-1] > 0:
                    avg_vol = sum(vols[:-1]) / max(len(vols) - 1, 1)
                    vr = vols[-1] / max(avg_vol, 1)
            if vr > 2.0:
                vol_desc = f"放巨量({vr:.1f}x)"
            elif vr > 1.5:
                vol_desc = f"放量({vr:.1f}x)"
            elif vr < 0.5:
                vol_desc = f"缩量({vr:.1f}x)"
            else:
                vol_desc = f"量平({vr:.1f}x)"
            hot_desc = f"{s['s']}板块 {vol_desc} {'+' if chg >= 0 else ''}{chg:.2f}%"
        else:
            flow = capital_flow.get(s["c"], 0)
            flow_str = f"主力净{flow/1e8:+.2f}亿" if abs(flow) > 1e4 else "无明显资金流入"
            hot_desc = f"{s['s']}板块 {flow_str}"

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
            "fb": {
                "score": s["fb"],
                "pe": _fmt_num(s.get("pe")),
                "revenue_yoy": _fmt_num(s.get("rev")),
                "net_profit_yoy": _fmt_num(s.get("ny")),
                "roe": _fmt_num(ind.get("ROE") or ind.get("JQROE")),
                "gross_margin": _fmt_num(ind.get("GROSS_PROFIT_RATIO")),
                "debt_ratio": _fmt_num(ind.get("DEBT_ASSET_RATIO")),
            },
            "hot": {
                "score": s["hot"],
                "desc": hot_desc,
            },
            "ch": {
                "score": s["ch"],
                "ma60": ma60,
                "price": _fmt_num(s.get("p")),
                "macd_hist": _fmt_num(macd_hist) if macd_hist != "?" else "?",
                "signal": sig,
            },
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
        advice = "强烈关注" if t >= 35 else ("可关注" if t >= 28 else ("观察" if t >= 22 else "回避"))
        summary_data.append({
            "code": f"{s['c']} {s['n']}",
            "advice": advice,
            "buy": _fmt_num(s.get("p")),
            "stop_loss": sl_point,
            "take_profit": tp_point,
        })

    return {
        "date": ds,
        "sectors": sectors_data,
        "eliminated": eliminated_data,
        "passed_count": passed_cnt,
        "top10": top10_data,
        "details": details_data,
        "summary": summary_data,
    }


async def score_one(p, sector_ranking=None, capital_flow=None):
    c = p["c"]
    # 备选链: 腾讯 > Yahoo > TickFlow
    try:
        kl = await hk_kline_tencent_async(c, "day", 365)
    except Exception:
        kl = []
    if not kl or len(kl) < 20:
        try:
            kl = await stock_kline_yahoo_async(f"{int(c)}.HK", "1d", "1y")
        except Exception:
            kl = []
    if not kl or len(kl) < 20:
        try:
            kl = await kline_tickflow_async(f"{c}.HK", "1d", 365)
        except Exception:
            kl = []
    fb = await fb_score(p, p.get("s", "其他"))
    hot = await hot_score(p, kl, sector_ranking, capital_flow)
    ch, cd = await chan_score(p, kl)
    total = fb * 5 + hot * 3 + ch * 2
    return {"c": c, "n": p["n"], "s": p["s"], "p": p["p"], "mc": p["mc"], "pe": p["pe"],
            "fb": fb, "hot": hot, "ch": ch, "total": total, "pw": p.get("pw", ""),
            "ny": p.get("ny"), "rev": p.get("rev"), "kl": kl, "cd": cd, "q": p["q"], "ind": p["ind"]}


async def fb_score(p, sector=None):
    ind = p["ind"]
    rev = sf(p.get("rev"))
    ny = sf(p.get("ny"))
    roe = (sf(ind.get("ROE")) or sf(ind.get("JQROE")) or 0)
    gr = (sf(ind.get("GROSS_PROFIT_RATIO")) or 0)
    dr = (sf(ind.get("DEBT_ASSET_RATIO")) or 0)
    pe = p.get("pe", 0)
    s = 3.0
    if rev > 30: s += 1
    elif rev > 15: s += 0.5
    elif rev < -10: s -= 1
    elif rev < 0: s -= 0.5
    if roe > 20: s += 1
    elif roe > 10: s += 0.5
    elif 0 < roe < 3: s -= 0.5
    elif roe < 0: s -= 1.0
    if gr > 60: s += 1
    elif gr > 30: s += 0.5
    elif 0 < gr < 10: s -= 0.5
    if dr > 0:
        if dr < 30: s += 0.5
        elif dr > 70: s -= 0.5

    # PE 按行业阈值评分：用相对估值倍数（实际PE / 行业阈值）判断
    pe_limit = SECTOR_PE_THRESHOLD.get(sector or "其他", SECTOR_PE_THRESHOLD["其他"])
    if pe > 0:
        pe_ratio = pe / pe_limit
        if pe_ratio <= 0.5:   # PE 远低于行业均值，估值便宜
            s += 0.5
        elif pe_ratio <= 1.0: # PE 在行业合理区间内
            pass
        elif pe_ratio <= 2.0: # PE 偏高但可接受
            s -= 0.3
        else:                 # PE 远超行业阈值，估值泡沫
            s -= 0.8
    elif pe < 0:              # PE 为负（亏损），扣更多分
        s -= 1.5
    if ny < -50: s -= 1.0
    elif ny < 0: s -= 0.5
    return max(1, min(5, round(s)))


async def hot_score(p, kl, sector_ranking=None, capital_flow=None):
    """基于实际资金流向的热点评分"""
    s, sec, c = 3.0, p["s"], p["c"]
    flow = capital_flow.get(c, 0) if capital_flow else 0

    # ① 板块资金排名
    if sector_ranking:
        for rank, (name, data) in enumerate(sector_ranking):
            if name == sec:
                total = data["total_flow"]
                if rank == 0 and total > 0:
                    s += 1.2
                elif rank < 3 and total > 0:
                    s += 0.8
                elif rank < 5:
                    s += 0.3 if total > 0 else -0.3
                else:
                    s -= 0.6
                break

    # ② 个股资金流向
    if flow > 5e8:
        s += 0.8
    elif flow > 2e8:
        s += 0.6
    elif flow > 1e8:
        s += 0.4
    elif flow > 5e7:
        s += 0.2
    elif flow > 1e7:
        s += 0.1
    elif flow < -5e7:
        s -= 0.5
    elif flow < -1e7:
        s -= 0.25

    # ③ 板块内资金龙头判定
    if sector_ranking:
        for name, data in sector_ranking:
            if name == sec:
                ranked = sorted(data["stocks"], key=lambda x: x["flow"], reverse=True)
                for rank, st in enumerate(ranked):
                    if st["code"] == c:
                        if rank == 0 and flow > 0:
                            s += 0.5
                        elif rank < 3 and flow > 0:
                            s += 0.25
                        break
                break

    # ④ 资金流向兜底：用成交量替代
    if abs(flow) < 1e4 and kl and len(kl) >= 21:
        vols = [k.get("volume", 0) for k in kl[-21:]]
        if vols and vols[-1] > 0:
            avg_vol = sum(vols[:-1]) / max(len(vols) - 1, 1)
            vol_ratio = vols[-1] / max(avg_vol, 1)
            if vol_ratio > 2.0:
                s += 0.6
            elif vol_ratio > 1.5:
                s += 0.4
            elif vol_ratio < 0.5:
                s -= 0.3
            pc = (kl[-1]["close"] - kl[-21]["close"]) / kl[-21]["close"] * 100
            if pc > 10 and vol_ratio > 1.2:
                s += 0.3
            elif pc < -5 and vol_ratio > 1.2:
                s -= 0.3

    # ⑤ 20日动量
    if kl and len(kl) >= 20:
        pc = (kl[-1]["close"] - kl[-20]["close"]) / kl[-20]["close"] * 100
        if pc > 15: s += 0.5
        elif pc > 8: s += 0.25
        elif pc < -10: s -= 0.5
        elif pc < -5: s -= 0.25

    return max(1, min(5, round(s)))


async def chan_score(p, kl):
    if not kl or len(kl) < 60:
        return 3, {}
    s, d = 3.0, {}
    try:
        ma = calc_ma(kl, [5, 20, 60])
        md = calc_macd(kl)
        cv = chan_risk_assessment(kl)
        close = kl[-1]["close"]

        if ma and len(ma) > 0:
            last_ma = ma[-1]
            m5 = last_ma.get("ma5")
            m20 = last_ma.get("ma20")
            m60 = last_ma.get("ma60")
            if m5 and m20 and m60:
                d["ma5"] = round(m5, 2)
                d["ma20"] = round(m20, 2)
                d["ma60"] = round(m60, 2)
                d["pv5"] = round((close - m5) / m5 * 100, 1)
                d["pv20"] = round((close - m20) / m20 * 100, 1)
                d["pv60"] = round((close - m60) / m60 * 100, 1)
                if m5 > m20 > m60:
                    d["ma_alignment"] = "多头排列↑"
                    d["ma_trend"] = "强势"
                    s += 1.2
                    d["ma5_pos"] = "上方" if close > m5 else "下方"
                elif m5 < m20 < m60:
                    d["ma_alignment"] = "空头排列↓"
                    d["ma_trend"] = "弱势"
                    s -= 1.2
                else:
                    if close > m60:
                        s += 0.3
                        d["ma_trend"] = "偏多"
                    else:
                        s -= 0.3
                        d["ma_trend"] = "偏空"
                    if m5 > m20:
                        d["ma_alignment"] = "短期金叉"
                        s += 0.3
                    else:
                        d["ma_alignment"] = "短期死叉"
                        s -= 0.3
                above_count = sum([close > m5, close > m20, close > m60])
                d["ma_above_count"] = above_count
                d["ma_pos_summary"] = {3: "三线之上", 2: "两线之上", 1: "一线之上"}.get(above_count, "三线之下")

            if m5 and m20 and len(ma) >= 2:
                prev_m5 = ma[-2].get("ma5")
                prev_m20 = ma[-2].get("ma20")
                if prev_m5 and prev_m20:
                    if prev_m5 <= prev_m20 and m5 > m20:
                        d["ma_cross_short"] = "MA5金叉MA20↑"
                        s += 0.5
                    elif prev_m5 >= prev_m20 and m5 < m20:
                        d["ma_cross_short"] = "MA5死叉MA20↓"
                        s -= 0.5

            if m20 and m60 and len(ma) >= 2:
                prev_m20 = ma[-2].get("ma20")
                prev_m60 = ma[-2].get("ma60")
                if prev_m20 and prev_m60:
                    if prev_m20 <= prev_m60 and m20 > m60:
                        d["ma_cross_medium"] = "MA20金叉MA60↑"
                        s += 0.8
                    elif prev_m20 >= prev_m60 and m20 < m60:
                        d["ma_cross_medium"] = "MA20死叉MA60↓"
                        s -= 0.8

        if md and len(md) > 0:
            m = md[-1]
            hi = m.get("macd_hist", (m["dif"] - m["dea"]) * 2)
            d["mh"] = round(hi, 4)
            if len(md) >= 2:
                pm = md[-2]
                ph = pm.get("macd_hist", (pm["dif"] - pm["dea"]) * 2)
                if ph < 0 < hi: d["mc"] = "金叉↑"; s += 1
                elif ph > 0 > hi: d["mc"] = "死叉↓"; s -= 1
            elif hi > 0: s += 0.5
            else: s -= 0.5
            d["mc"] = d.get("mc", "无交叉")
        d["v"] = str(cv.get("verdict", "")) if isinstance(cv, dict) else ""
        sig = cv.get("signal", "") if isinstance(cv, dict) else ""
        if "买" in sig or "buy" in sig.lower(): s += 1
        elif "卖" in sig or "sell" in sig.lower(): s -= 1
    except Exception as e:
        d["e"] = str(e)
    return max(1, min(5, round(s))), d


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

async def main():
    ds = datetime.now().strftime("%Y-%m-%d")
    # ── stdout 只输出正式报告（格式唯一且确定），进度信息不输出 ──
    _log = lambda *a, **kw: None

    # ── 动态候选池 ──
    _log("[Phase 0] 构建动态候选池...")
    dynamic_pool = await fetch_dynamic_pool(min_stocks=300)
    if not dynamic_pool:
        dynamic_pool = load_dynamic_pool_cache() or []
    _log(f"  动态池: {len(dynamic_pool)} 只\n")

    # ── 构建板块映射 ──
    sectors = build_sectors_from_pool(dynamic_pool)
    all_codes = sum(sectors.values(), [])
    code2sector = {c: s for s, codes in sectors.items() for c in codes}
    _log(f"  合并后候选池: {len(all_codes)} 只（{len(sectors)} 个板块）")
    for sec, codes in sorted(sectors.items()):
        _log(f"    {sec}: {len(codes)} 只")
    _log()

    # ── Step 1: 全市场扫描 ──
    st = await fetch_all(all_codes)

    # ── 板块表现 ──
    _log("  板块表现:")
    ss = {}
    for sec, codes in sectors.items():
        chs = [sf(st[c]["q"].get("change_pct")) for c in codes if st.get(c, {}).get("q", {}).get("name")]
        ap = sum(chs) / len(chs) if chs else 0
        up = sum(1 for ch in chs if ch > 0)
        ss[sec] = {"c": len(chs), "ap": round(ap, 2), "up": up, "dn": len(chs) - up}
        _log(f"    {sec}: {len(chs)}只 {ap:+.2f}% 涨{up}跌{len(chs)-up}")

    # ── Step 2: 中观过滤 ──
    _log(f"\n[Step 2] 中观过滤...")
    passed, elim = meso_filter(st, sectors, code2sector)
    _log(f"  剔除: {len(elim)} 只")
    for c, n, r in elim: _log(f"    - {c} {n}: {r}")
    _log(f"  通过: {len(passed)} 只\n")

    # ── Step 3: 并行评分 ──
    _log(f"[Step 3] 资金流向分析+并行评分 {len(passed)} 只候选标的...")
    capital_flow = await batch_hk_capital_flow_async([p["c"] for p in passed])
    sector_flow = {}
    for p in passed:
        sec, flow = p["s"], capital_flow.get(p["c"], 0)
        if sec not in sector_flow:
            sector_flow[sec] = {"total_flow": 0.0, "stocks": []}
        sector_flow[sec]["total_flow"] += flow
        sector_flow[sec]["stocks"].append({"code": p["c"], "name": p["n"], "flow": flow})
    sector_ranking = sorted(sector_flow.items(), key=lambda x: x[1]["total_flow"], reverse=True)
    _log("  资金流向板块排名（前4）：")
    for i, (name, data) in enumerate(sector_ranking[:4]):
        top = sorted(data["stocks"], key=lambda x: x["flow"], reverse=True)[0]
        _log(f"    {i+1}. {name}: 主力净{data['total_flow']/1e8:+.2f}亿  龙头:{top['name']}(+{top['flow']/1e8:.2f}亿)")

    scored = await asyncio.gather(*[score_one(p, sector_ranking=sector_ranking, capital_flow=capital_flow) for p in passed])
    scored = [s for s in scored if s]
    scored.sort(key=lambda x: x["total"], reverse=True)
    _log(f"  评分完成\n")

    # ── 构建裸数据 → 格式引擎输出（Pydantic 校验 + 渲染）─
    # stdout 只走这里，格式唯一且确定
    raw_data = build_selection_data(ds, ss, elim, scored, len(passed), capital_flow, sector_ranking)
    try:
        report = format_output(raw_data)
        print(report)
    except FormatValidationError as e:
        _log(f"\n{'=' * 60}")
        _log("❌ 数据格式校验失败，需修正 JSON 结构后重试")
        _log(f"{'=' * 60}")
        _log(e.message)
        _log(f"{'=' * 60}\n")
        raise
    await close_async_session()
    await close_tickflow()


if __name__ == "__main__":
    import gc
    asyncio.run(main())
    asyncio.run(close_async_session())
    asyncio.run(close_tickflow())
    gc.collect()