#!/usr/bin/env python3
"""统一多市场分析脚本：港股 / A 股 / 美股，输出格式一致。"""

import sys, os, asyncio
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
from typing import Any, Dict, List, Tuple, Optional

from scripts.quantrisk.report import StockAnalyzer
from scripts.quantrisk.data import close_async_session, close_tickflow

# ── 用于 fetch 资金流向（在 main 中按需 import） ──

# ═══════════════════════════════════════════════════════════════
# 市场自动识别
# ═══════════════════════════════════════════════════════════════

def detect_market(code: str) -> Tuple[str, str]:
    """根据代码格式自动识别市场。返回 (market, clean_code)。"""
    code = code.strip()
    upper = code.upper()
    if upper.endswith(".HK"):
        return "hk", upper[:-3]
    if upper.endswith(".US"):
        return "us", upper[:-3]
    if upper.endswith((".SH", ".SZ")):
        return "cn", upper[:-3]
    if code.isdigit():
        if len(code) == 5:
            return "hk", code
        elif len(code) == 6:
            return "cn", code
        else:
            raise ValueError(f"无法识别的市场: {code}")
    elif code.replace(".", "").replace("-", "").isalpha():
        return "us", code.upper()
    else:
        raise ValueError(f"无法识别的代码格式: {code}")


# ═══════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════

def _safe(v, fallback: str = "-") -> str:
    """安全取值，None / 0 等异常值时返回 fallback"""
    if v is None or v == "N/A" or v == "":
        return fallback
    if isinstance(v, (int, float)):
        if abs(v) < 1e-9:
            return fallback
    return v


def _fmt(v, d: int = 2) -> str:
    """数值保留 d 位小数"""
    if isinstance(v, (int, float)):
        return f"{v:.{d}f}"
    return str(v)


def _fmt_pct(v) -> str:
    """百分比格式化，负数带 - 号"""
    if isinstance(v, (int, float)):
        sign = "+" if v >= 0 else "-"
        return f"{sign}{abs(v):.2f}%"
    return str(v)


def _fmt_amount(v) -> str:
    """金额自动转亿/万"""
    if isinstance(v, (int, float)):
        if abs(v) >= 1e8:
            return f"{v / 1e8:.2f}亿"
        elif abs(v) >= 1e4:
            return f"{v / 1e4:.2f}万"
        return f"{v:.2f}"
    return str(v)


def _fmt_volume(v) -> str:
    """成交量自动转万/亿股"""
    if isinstance(v, (int, float)):
        if abs(v) >= 1e8:
            return f"{v / 1e8:.2f}亿股"
        elif abs(v) >= 1e4:
            return f"{v / 1e4:.2f}万股"
        return f"{v:.0f}股"
    return str(v)


def _render_table(rows: List[Tuple[str, str]]) -> str:
    """三列 markdown 表格：指标 | 值 | 解释"""
    lines = ["| 指标 | 值 | 解释 |", "|------|-----|------|"]
    for item in rows:
        if len(item) == 3:
            k, v, note = item
            lines.append(f"| {k} | {v} | {note} |")
        else:
            k, v = item[0], item[1]
            lines.append(f"| {k} | {v} | — |")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# 输出格式化 — 四表 + LLM 分析
# ═══════════════════════════════════════════════════════════════

def _mcap_display(mcap, market: str) -> str:
    """市值显示（带单位）"""
    v = _safe(mcap, None)
    if v is None:
        return "-"
    if market == "us":
        try:
            fv = float(v)
            return f"${_fmt_amount(fv)}"
        except (ValueError, TypeError):
            return str(v)
    return f"{v}亿"


def format_result(code: str, r: Dict[str, Any], market: str,
                  capital_flow: Optional[Dict[str, Any]] = None,
                  hot_sectors: Optional[Dict[str, List[Dict]]] = None,
                  is_derived: bool = False) -> str:
    """
    将单个分析结果转为四表 + LLM 分析的 markdown 字符串：
      1. 实时行情
      2. 基本面分析
      3. 市场热点分析
      4. 技术分析
      5. LLM 关键分析（模板）
    """
    q = r.get("quote", {})
    t = r.get("technicals", {})
    y = r.get("yahoo_stats", {})
    ind = r.get("indicator", {})
    basic = r.get("basic_info", {})
    blocks = r.get("concept_blocks", {})
    company_profile = r.get("company_profile", {})
    name = r.get("name", "未知")
    hot_sectors = hot_sectors or {}

    # ── 表 1：实时行情 ──
    price = _safe(q.get("price"), "-")
    chg = _safe(q.get("change_pct"), None)
    chg_str = _fmt_pct(chg) if chg is not None else "-"
    open_p = _safe(q.get("open"), "-")
    prev = _safe(q.get("prev_close"), "-")
    day_low = _safe(q.get("low"), "-")
    day_high = _safe(q.get("high"), "-")
    amp = _safe(q.get("amp"), None)
    amp_str = _fmt_pct(amp) if amp is not None else "-"
    mcap = _mcap_display(q.get("market_cap_100m") or q.get("market_cap"), market)
    tr = q.get("turnover_rate")
    # 腾讯API的turnover_rate字段经常返回0.0（截断），从成交量/市值/价格推算
    vol_shares_raw = _safe(q.get("volume_shares"), None)
    vol_str = _fmt_volume(vol_shares_raw) if vol_shares_raw is not None else "-"
    if isinstance(tr, (int, float)) and tr > 0:
        tr_str = f"{tr:.2f}%"
    else:
        # 推算: 换手率 = 成交量 / (市值 / 股价) × 100%
        try:
            mc = float(q.get("market_cap_100m") or 0) * 1e8
            pr = float(q.get("price") or 0)
            vs = float(vol_shares_raw or 0)
            if mc > 0 and pr > 0 and vs > 0:
                total_shares = mc / pr
                tr_calc = vs / total_shares * 100
                tr_str = f"{tr_calc:.4f}%"
            else:
                tr_str = "-"
        except (ValueError, TypeError, ZeroDivisionError):
            tr_str = "-"
    vol_shares = _safe(q.get("volume_shares"), None)
    vol_str = _fmt_volume(vol_shares) if vol_shares is not None else "-"

    rows_quote = [
        ("现价", price, "最新成交价"),
        ("涨跌", chg_str, "较昨收涨跌幅"),
        ("今开", open_p, "今日开盘价"),
        ("昨收", prev, "上一交易日收盘价"),
        ("日内区间", f"{day_low} ~ {day_high}", "今日最低~最高"),
        ("振幅", amp_str, "当日波幅"),
        ("成交额", _fmt_amount(q.get("amount_100m") or q.get("amount", 0)) if market != "us" else _safe(q.get("volume"), "-"), "当日成交金额"),
        ("成交量", vol_str, "当日成交股数"),
        ("换手率", tr_str, "当日换手率"),
        ("市值", mcap, "总股本×现价"),
    ]
    # 美股显示 52 周区间
    if market == "us":
        h52 = _safe(q.get("high_52w"), None)
        l52 = _safe(q.get("low_52w"), None)
        if h52 is not None and l52 is not None:
            rows_quote.append(("52周区间", f"{_fmt(float(h52))} ~ {_fmt(float(l52))}", "52周最低~最高"))

    # ── 表 2：基本面分析 ──
    pe = _safe(q.get("pe") or q.get("pe_ttm"), None)
    pe_str = _fmt(pe, 2) if pe is not None else "-"
    fpe = _safe(y.get("forward_pe"), None)
    fpe_str = _fmt(fpe, 2) if fpe is not None else "-"
    target = _safe(y.get("target_mean"), None)
    target_str = _fmt(target, 2) if target is not None else "-"
    rec = _safe(y.get("recommendation"), "-")

    rows_fund = [
        ("PE (TTM)", pe_str, "市盈率；负值表示亏损"),
        ("远期PE", fpe_str, "分析师预估未来12个月PE"),
        ("目标价", target_str, "券商平均目标价"),
        ("评级", rec, "buy/hold/sell 一致预期"),
    ]
    # 主营业务（港股优先从 company_profile 取，CN/US 暂不展示）
    business = company_profile.get("business", "") if company_profile else ""
    if business:
        # 截断过长描述，显示前100字
        short = (business[:100] + "…") if len(business) > 100 else business
        rows_fund.append(("主营业务", short, "来自新浪个股信息页"))
    if ind:
        rev = _safe(ind.get("OPERATE_INCOME"), None)
        rev_yoy = _safe(ind.get("OPERATE_INCOME_YOY"), None)
        profit = _safe(ind.get("HOLDER_PROFIT"), None)
        profit_yoy = _safe(ind.get("HOLDER_PROFIT_YOY"), None)
        roe = _safe(ind.get("ROE"), None)
        gp = _safe(ind.get("GROSS_MARGIN"), None)
        dr = _safe(ind.get("DEBT_RATIO"), None)
        rows_fund.extend([
            ("最新营收", _fmt_amount(rev) if rev is not None else "-", "最新财报营业收入"),
            ("营收同比", _fmt_pct(rev_yoy) if rev_yoy is not None else "-", "营收同比增长率"),
            ("净利润", _fmt_amount(profit) if profit is not None else "-", "最新财报净利润"),
            ("净利同比", _fmt_pct(profit_yoy) if profit_yoy is not None else "-", "净利润同比增长率"),
            ("ROE", _fmt_pct(roe) if roe is not None else "-", "净资产收益率，盈利能力"),
            ("毛利率", _fmt_pct(gp) if gp is not None else "-", "毛利/营收，产品竞争力"),
            ("负债率", _fmt_pct(dr) if dr is not None else "-", "资产负债率，杠杆风险"),
        ])
    # A股行业
    if market == "cn" and basic:
        industry = _safe(basic.get("industry"), "-")
        rows_fund.append(("行业", industry, "所属行业"))

    # ── 表 3：市场热点分析 ──
    cf = capital_flow or {}
    cf_note = ""
    if is_derived:
        cf_note = "（港股push2无资金流向数据，行情派生估算不可靠，已隐藏）"

    # 个股行业/板块
    if market == "hk":
        stock_industry = _safe(basic.get("industry"), None)
        # 港股：取 indicator 中可能的板块字段，否则从概念标签取
        concept_tags = (blocks or {}).get("concept_tags", [])
        if not stock_industry or stock_industry == "-":
            stock_industry = concept_tags[0] if concept_tags else None

        rows_sentiment = [
            ("所属行业", _safe(stock_industry, "-"), "所属行业板块"),
            ("资金流向(主力净流入)", _fmt_amount(cf.get("main_net", 0)) if cf and not is_derived else "暂无",
             "主力机构当日净买入" + cf_note),
        ]
        # 港股热点板块
        hk_hot = hot_sectors.get("hk", [])
        if hk_hot:
            hot_names = [s.get("industry", "") for s in hk_hot[:3]]
            rows_sentiment.append(("港股热门板块", " > ".join(hot_names),
                                   f"涨幅{hk_hot[0].get('pct','-')}% 起"))
            rows_sentiment.append(("是否热点板块",
                                   "是 ✅" if (stock_industry and stock_industry in hot_names) else "否",
                                   "该股所属板块是否在当日热点中"))
    elif market == "cn":
        industry = _safe(basic.get("industry"), None)
        tags = (blocks or {}).get("concept_tags", [])
        tag_str = ", ".join(tags[:6]) if tags else "-"
        main_net = cf.get("main_net") if cf else None
        rows_sentiment = [
            ("行业", _safe(industry, "-"), "所属行业板块"),
            ("概念", tag_str, "概念股标签"),
            ("资金流向(主力净流入)", _fmt_amount(main_net) if main_net is not None else "暂无",
             "主力机构当日净买入" + cf_note),
            ("主力净流入占比", _fmt_pct(cf.get("main_pct", 0)) if cf else "-",
             "主力净占成交额比"),
        ]
        # A股热点板块
        cn_hot = hot_sectors.get("cn", [])
        if cn_hot:
            hot_names = [s.get("industry", "") for s in cn_hot[:3]]
            rows_sentiment.append(("A股热门板块", " > ".join(hot_names),
                                   f"涨幅{cn_hot[0].get('pct','-')}% 起"))
            rows_sentiment.append(("是否热点板块",
                                   "是 ✅" if (industry and industry in hot_names) else "否",
                                   "该股所属板块是否在当日热点中"))
    else:  # us
        sector = _safe(q.get("sector"), None)
        rows_sentiment = [
            ("所属板块", _safe(sector, "-"), "美股所属板块"),
            ("资金流向", "暂无" + cf_note, "美股无主力资金数据"),
        ]

    # ── 表 4：技术分析 ──
    sup_str = res_str = cur_sup_str = cur_res_str = sl_str = tp_str = "-"
    if t.get("error"):
        rows_tech = [("状态", f"⚠️ {t['error']}")]
        chan_extra = ""
    else:
        ma = t.get("ma", {})
        macd = t["macd"].get("macd_hist", "-") if t.get("macd") else "-"
        rsi14 = t["rsi"].get("rsi14", "-") if t.get("rsi") else "-"
        boll = t.get("boll", {})
        sr = t.get("support_resistance", {})
        sltp = t.get("stop_loss_take_profit", {})
        chan = t.get("chan", {})

        sup = _safe(sr.get("support"), None)
        res = _safe(sr.get("resistance"), None)
        cur_sup = _safe(sr.get("current_support"), None)
        cur_res = _safe(sr.get("current_resistance"), None)
        sup_str = _fmt(sup) if sup is not None else "-"
        res_str = _fmt(res) if res is not None else "-"
        cur_sup_str = _fmt(cur_sup) if cur_sup is not None else "-"
        cur_res_str = _fmt(cur_res) if cur_res is not None else "-"

        sl = _safe(sltp.get("stop_loss"), None)
        tp = _safe(sltp.get("take_profit"), None)
        sl_str = _fmt(sl) if sl is not None else "-"
        tp_str = _fmt(tp) if tp is not None else "-"

        chan_v = chan.get("chan_verdict", "N/A")
        strokes = chan.get("strokes_count", 0) or 0
        segs = chan.get("segments_count", 0) or 0

        trend = chan.get("trend", {})
        trend_dir = trend.get("direction", "unknown")
        trend_desc = trend.get("description", "")

        bsp = chan.get("buy_sell_points", {})
        buy_pts = bsp.get("buy_points", [])
        sell_pts = bsp.get("sell_points", [])
        divergence_list = chan.get("divergences", [])
        risk_sigs = chan.get("risk_signals", [])

        # ── 构造精简缠论详情文本（结论 + 理由，不堆砌原始信号） ──
        chan_extra_lines = []

        # ① 总览结论
        chan_extra_lines.append(
            f"### 缠论分析\n\n"
            f"**结论**: {chan_v}  |  趋势: {trend_desc}  |  笔数: {strokes}  |  段数: {segs}"
        )

        # ② 买卖点汇总（按类型归类，不逐条展开）
        def _count_by_type(pts, key):
            from collections import Counter
            return Counter(p.get(key, "unknown") for p in pts)

        buy_types = _count_by_type(buy_pts, "type")
        sell_types = _count_by_type(sell_pts, "type")

        if buy_types or sell_types:
            lines_bs = []
            if buy_types:
                parts = [f"{t}×{n}" for t, n in buy_types.most_common()]
                lines_bs.append(f"- **买点**: {', '.join(parts)}")
            if sell_types:
                parts = [f"{t}×{n}" for t, n in sell_types.most_common()]
                lines_bs.append(f"- **卖点**: {', '.join(parts)}")
            chan_extra_lines.append("\n".join(lines_bs))

        # ③ 背驰：只保留强背驰，按方向归并
        strong_div = [d for d in divergence_list if d.get("severity", "").lower() == "strong"]
        weak_div = [d for d in divergence_list if d.get("severity", "").lower() == "weak"]
        if strong_div:
            bearish_strong = sum(1 for d in strong_div if "顶背驰" in d.get("detail", ""))
            bullish_strong = sum(1 for d in strong_div if "底背驰" in d.get("detail", ""))
            parts = []
            if bearish_strong:
                parts.append(f"顶背驰(强){bearish_strong}次")
            if bullish_strong:
                parts.append(f"底背驰(强){bullish_strong}次")
            chan_extra_lines.append(f"- **强背驰**: {', '.join(parts)}")
        if weak_div:
            chan_extra_lines.append(f"- **弱背驰**: {len(weak_div)}次")

        # ④ 风险信号：按信号类型归并计数
        sig_counts = _count_by_type(risk_sigs, "signal")
        if sig_counts:
            ignored = {"first_buy", "first_sell", "third_buy"}
            filtered = {k: v for k, v in sig_counts.most_common() if k not in ignored}
            if filtered:
                parts = [f"{k}×{v}" for k, v in filtered.items()]
                chan_extra_lines.append(f"- **关键信号**: {', '.join(parts)}")

        chan_extra = "\n".join(chan_extra_lines) if chan_extra_lines else ""

        rows_tech = [
            ("MA5/10/20/60", f"{_fmt(ma.get('ma5','-'))} / {_fmt(ma.get('ma10','-'))} / {_fmt(ma.get('ma20','-'))} / {_fmt(ma.get('ma60','-'))}", "各周期均线价格"),
            ("RSI14", _fmt(rsi14, 2), "14日相对强弱，<30超卖 >70超买"),
            ("MACD柱", _fmt(macd, 4), "MACD柱状图，正值多头市场"),
            ("布林带(上/中/下)", f"{_fmt(boll.get('upper','-'))} / {_fmt(boll.get('middle','-'))} / {_fmt(boll.get('lower','-'))}", "布林上轨/中轨/下轨"),
            ("支撑/压力", f"支撑{sup_str} / 压力{res_str}", "近期关键支撑与压力位"),
            ("日内支撑/压力", f"支撑{cur_sup_str} / 压力{cur_res_str}", "日内高低点附近"),
            ("止损/止盈", f"止损{sl_str} / 止盈{tp_str}", "止损/止盈参考价位"),
            ("缠论", f"{chan_v}（笔{strokes} 段{segs}，趋势{trend_dir}）", "缠论技术分析结论"),
        ]

    # ── 组合输出 ──
    src = _SOURCES.get(market, {})
    lines = [
        f"\n## 📊 {name} ({code})",
        "",
        _render_table_with_source(rows_quote, "### ① 实时行情", src.get("quote", "")),
        "",
        _render_table_with_source(rows_fund, "### ② 基本面分析", src.get("fund", "")),
        "",
        _render_table_with_source(rows_sentiment, "### ③ 市场热点", src.get("sentiment", "")),
        "",
        _render_table_with_source(rows_tech, "### ④ 技术分析", src.get("tech", "")),
        "",
    ]

    if chan_extra:
        lines.append("### 缠论详情")
        lines.append("")
        lines.append(chan_extra)
        lines.append("")

    lines.append("### ⑤ 综合分析")
    lines.append("")
    lines.append(f"- **支撑位**: {sup_str}（日内{cur_sup_str}）")
    lines.append(f"- **压力位**: {res_str}（日内{cur_res_str}）")
    lines.append(f"- **止损/止盈**: 止损{sl_str} / 止盈{tp_str}")
    lines.append("")

    return "\n".join(lines)


def _render_table_with_source(rows: List[Tuple[str, str]],
                              header: str,
                              source: str) -> str:
    """渲染带数据来源标注的表格：标题 + 来源标注 + 表格"""
    return f"{header}\n\n> 📡 数据来源: {source}\n\n{_render_table(rows)}"


# ═══════════════════════════════════════════════════════════════
# 市场×表的数据来源常量
# ═══════════════════════════════════════════════════════════════

_SOURCES: Dict[str, Dict[str, str]] = {
    "cn": {
        "quote": "腾讯行情",
        "fund": "腾讯行情（PE） + 东财 datacenter（行业/财务指标）",
        "sentiment": "东财 push2（资金流） + 东财板块排名（热点）",
        "tech": "Yahoo K线 / 腾讯 K线（备选 TickFlow）",
    },
    "hk": {
        "quote": "腾讯行情（备选新浪）",
        "fund": "腾讯行情（PE） + 东财 datacenter（财务指标）",
        "sentiment": "东财 push2（资金流） + 东财板块排名（热点）",
        "tech": "Yahoo K线（备选 TickFlow）",
    },
    "us": {
        "quote": "腾讯行情（备选新浪）",
        "fund": "Yahoo Finance（PE/远期PE/目标价/评级）",
        "sentiment": "Yahoo Finance（板块）",
        "tech": "Yahoo K线（备选 TickFlow）",
    },
}


def format_json_result(code: str, r: Dict[str, Any], market: str) -> Dict[str, Any]:
    """JSON 输出模式，保留原始结构并加 market 标记。"""
    return {"market": market, **r}


# ═══════════════════════════════════════════════════════════════
# 资金流向获取
# ═══════════════════════════════════════════════════════════════

def _fetch_capital_flow_sync(codes: List[str], secid_prefix: int) -> Dict[str, Dict[str, Any]]:
    """
    同步获取资金流向（curl 方式，aiohttp 连 push2.eastmoney.com 会断开）。
    港股(secid_prefix=116) 使用 kline/get 端点，A股使用 daykline/get 端点。
    返回 {clean_code: {main_net, main_pct}}
    """
    import subprocess, time
    out = {}
    endpoint = "kline" if secid_prefix == 116 else "daykline"
    for code in codes:
        url = (f"https://push2.eastmoney.com/api/qt/stock/fflow/{endpoint}/get"
               f"?secid={secid_prefix}.{code}&klt=101"
               "&fields1=f1,f2,f3,f7&fields2=f51,f52,f53,f54,f55,f56,f57&lmt=1")
        try:
            res = subprocess.run(
                ["curl", "-s", "--max-time", "8", "-H", "Referer: https://quote.eastmoney.com/", url],
                capture_output=True, text=True, timeout=12
            )
            data = json.loads(res.stdout).get("data", {})
            klines = data.get("klines", [])
            if klines:
                p = klines[-1].split(",")
                # 字段顺序: date,main_net,small_net,mid_net,big_net,super_big_net,main_pct
                out[code] = {
                    "main_net": float(p[1]) if len(p) > 1 and p[1] else 0,
                    "main_pct": float(p[6]) if len(p) > 6 and p[6] else 0,
                }
        except Exception:
            pass
        time.sleep(0.3)  # 间隔限流
    return out


def _derive_hk_capital_flow_from_quote(code: str, r: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """从 Tencent 行情数据派生港股资金流向（push2 API 对港股返回空时兜底）。
    估算逻辑: 主力净流入 ≈ 价格变动 × 成交量(股) × 0.3（经验系数）"""
    q = r.get("quote", {})
    price = q.get("price")
    prev = q.get("prev_close")
    vol = q.get("volume_shares") or q.get("volume")
    if price is None or prev is None or not vol:
        return None
    try:
        price, prev, vol = float(price), float(prev), float(vol)
    except (ValueError, TypeError):
        return None
    price_change = price - prev
    # 主力净流入估算 = 价格变动 × 成交量(股) × 0.3
    est_main_net = price_change * vol * 0.3  # 元
    est_main_pct = (price_change / prev * 100 * 0.3) if prev else 0
    return {"main_net": round(est_main_net, 0), "main_pct": round(est_main_pct, 2),
            "_derived": True}


async def _fetch_capital_flow(codes: List[str], market: str,
                               results: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Dict[str, Any]]:
    """按需获取资金流向（异步入口，内部用 subprocess 调用 curl；港股 push2 返回空时从 Tencent 数据派生）"""
    if not codes:
        return {}
    results = results or {}
    if market == "hk":
        prefix = 116
        out = {}
        for code in codes:
            sub = _fetch_capital_flow_sync([code], prefix)
            if code in sub:
                out[code] = sub[code]
            else:
                # push2 API 对港股返回空，从 Tencent 行情数据派生
                r = results.get(code, {})
                derived = _derive_hk_capital_flow_from_quote(code, r)
                if derived:
                    out[code] = derived
        return out
    elif market == "cn":
        from scripts.quantrisk.data import cn_secid
        out = {}
        for code in codes:
            try:
                secid = cn_secid(code)
                prefix = int(secid.split(".")[0])
            except Exception:
                continue
            sub = _fetch_capital_flow_sync([code], prefix)
            out.update(sub)
        return out
    else:
        return {}
    return _fetch_capital_flow_sync(codes, prefix)


async def _fetch_hot_sectors() -> Dict[str, List[Dict[str, Any]]]:
    """获取各市场热点板块排名（curl 方式，aiohttp 连 push2 易断开）。
    返回 {market: [sector, ...]}
    """
    import subprocess, time
    def _curl(params: str, label: str) -> List[Dict[str, Any]]:
        url = ("https://push2.eastmoney.com/api/qt/clist/get?" + params +
               "&fields=f2,f3,f4,f5,f6,f12,f14&pn=1&pz=5&fid=f3&po=1")
        for attempt in range(3):
            try:
                res = subprocess.run(
                    ["curl", "-s", "--max-time", "10",
                     "-H", "Referer: https://quote.eastmoney.com/",
                     "-H", "User-Agent: Mozilla/5.0", url],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    text=True, timeout=15
                )
                if not res.stdout.strip():
                    time.sleep(2); continue
                d = json.loads(res.stdout)
                diff = (d.get("data") or {}).get("diff") or []
                if isinstance(diff, dict): diff = list(diff.values())
                return [{"industry": i.get("f14"), "pct": round((i.get("f3") or 0) / 100, 2),
                         "up": i.get("f4"), "down": i.get("f5")} for i in diff if i.get("f14")]
            except Exception as e:
                print(f"[WARN] {label}板块排名失败(attempt {attempt}): {e}")
                time.sleep(2)
        return []

    cn_sectors = _curl("fs=m:90+t:2", "A股")  # A股行业
    hk_sectors = _curl("fs=m:0+t:5", "港股")   # 港股板块
    return {"cn": cn_sectors, "hk": hk_sectors}


# ═══════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════

async def main():
    args = sys.argv[1:]
    codes = [a for a in args if not a.startswith("--")]
    json_mode = "--json" in args

    if not codes:
        print("用法: uv run scripts/analyze.py 03690 [600309 ...] [--json]")
        print("  03690     → 港股  |  600309 → A股  |  AAPL → 美股")
        sys.exit(1)

    # 识别每个代码的市场
    try:
        tasks = [(code, detect_market(code)) for code in codes]
    except ValueError as e:
        print(f"错误: {e}")
        sys.exit(1)

    # ── 非 JSON 模式：委托给 portfolio_report 统一渲染 ──
    # 所有分析（单只/批量）复用同一套模板（六维评分+产业链+漏斗+镜子测试+技术面）
    if not json_mode:
        import subprocess
        import json
        import os

        # 先用 StockAnalyzer 获取真实名称（避免报告里出现 "00268" 而不是 "金蝶国际"）
        analyzer = StockAnalyzer()
        name_map = {}
        async def _fetch_name(c, m):
            try:
                if m == "hk":
                    r = await analyzer.analyze_hk(c)
                elif m == "cn":
                    r = await analyzer.analyze_cn(c)
                else:
                    r = await analyzer.analyze_us(c)
                return r.get("name") or c if "error" not in r else c
            except Exception:
                return c

        for code, (market, clean_code) in tasks:
            nm = await _fetch_name(clean_code, market)
            name_map[clean_code] = nm

        # 构造持仓 JSON（成本设为 0，让报告模板正常渲染）
        holdings = []
        for code, (market, clean_code) in tasks:
            holdings.append({
                "code": clean_code,
                "market": market,
                "name": name_map.get(clean_code, code),
                "shares": 1,
                "avg_cost": 0,
            })
        await analyzer.close()
        await close_async_session()
        await close_tickflow()
        stdin_data = json.dumps({"holdings": holdings})
        script_dir = os.path.dirname(os.path.abspath(__file__))
        report_script = os.path.join(script_dir, "portfolio_report.py")

        # 直接调用 venv python（analyze.py 自身已由 uv run 执行，使用相同环境）
        result = subprocess.run(
            [sys.executable, report_script, "--stdin", "--single"],
            input=stdin_data,
            capture_output=True,
            text=True,
            timeout=180,
            env={**os.environ, "PYTHONPATH": os.path.join(script_dir, os.pardir)},
        )
        print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        return

    # ── JSON 模式：保持原有行为 ──

    analyzer = StockAnalyzer()
    results: Dict[str, Dict[str, Any]] = {}

    # 按市场分组
    grouped: Dict[str, List[str]] = {"hk": [], "cn": [], "us": []}
    for _, (market, clean_code) in tasks:
        grouped[market].append(clean_code)

    # 并行分析
    async def _run_hk(codes):
        if not codes:
            return {}
        return await analyzer.analyze_hk_batch(codes)

    async def _run_cn(codes):
        if not codes:
            return {}
        return {c: await analyzer.analyze_cn(c) for c in codes}

    async def _run_us(codes):
        if not codes:
            return {}
        return {c: await analyzer.analyze_us(c) for c in codes}

    hk_res, cn_res, us_res = await asyncio.gather(
        _run_hk(grouped["hk"]),
        _run_cn(grouped["cn"]),
        _run_us(grouped["us"]),
    )

    # 获取资金流向（HK + A股）
    cf_hk = await _fetch_capital_flow(grouped["hk"], "hk")
    # 构建分析结果（先存到 results 再传给资金流向函数做派生）
    _raw: Dict[str, Dict[str, Any]] = {}
    for code, (market, clean_code) in tasks:
        if market == "hk":
            _raw[code] = hk_res.get(clean_code, {})
        elif market == "cn":
            _raw[code] = cn_res.get(clean_code, {})
        elif market == "us":
            _raw[code] = us_res.get(clean_code, {})

    # 获取资金流向（HK + A股），港股 push2 返回空时从 Tencent 数据派生
    cf_hk = await _fetch_capital_flow(grouped["hk"], "hk", results=_raw)
    cf_cn = await _fetch_capital_flow(grouped["cn"], "cn")

    # 获取热点板块
    hot_sectors = await _fetch_hot_sectors()

    # 合并结果
    for code, (market, clean_code) in tasks:
        r = _raw.get(code, {})
        if market == "hk":
            results[code] = (r, market, cf_hk.get(clean_code),
                             hot_sectors.get("hk", []),
                             cf_hk.get(clean_code, {}).get("_derived", False))
        elif market == "cn":
            results[code] = (r, market, cf_cn.get(clean_code),
                             hot_sectors.get("cn", []),
                             False)
        elif market == "us":
            results[code] = (r, market, None, [], False)

    # 输出
    if json_mode:
        output = {}
        for code, (r, market, _, _, _) in results.items():
            output[code] = format_json_result(code, r, market)
        print(json.dumps(output, ensure_ascii=False, default=str, indent=2))
    else:
        for code, (r, market, cf, hs, derived) in results.items():
            if not r:
                print(f"\n## ❌ {code} — 数据获取失败")
                continue
            print(format_result(code, r, market, capital_flow=cf,
                                hot_sectors={"hk": hs} if market == "hk" else
                                            {"cn": hs} if market == "cn" else {},
                                is_derived=derived))

    await analyzer.close()


if __name__ == "__main__":
    asyncio.run(main())
    asyncio.run(close_async_session())
    asyncio.run(close_tickflow())
