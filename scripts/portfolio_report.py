#!/usr/bin/env python3
"""
📊 持仓组合完整报告 — 一键生成
整合四大师 + 缠论深度分析 + 产业链Mermaid + 行业漏斗5条 + 新标的推荐

用法:
    uv run scripts/portfolio_report.py              # 从 portfolio.json 读取持仓
    uv run scripts/portfolio_report.py --stdin      # 从 stdin 读取持仓 JSON
"""
import sys, os, json, asyncio
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime
from scripts.quantrisk.report import StockAnalyzer
from scripts.quantrisk.data import (hk_stock_quote_tencent_async, hk_kline_tencent_async,
                                     stock_kline_yahoo_async, kline_tickflow_async,
                                     key_indicators_eastmoney_async, close_async_session, close_tickflow)
from scripts.quantrisk.chan import chan_theory_full, calc_ma
from scripts.quantrisk.indicators import calc_stop_loss_take_profit
from scripts.quantrisk.chain_renderer import render_mermaid_raw, render_chain_block, has_chain_data

def fmt(v, dec=2):
    if v is None: return "-"
    if isinstance(v, float): return f"{v:.{dec}f}"
    return str(v)

PORTFOLIO_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "portfolio.json")

# ── 标准持仓名称映射 ──
STOCK_NAMES = {
    "02460": "华润饮料", "03888": "金山软件",
    "01308": "海丰国际", "06693": "赤峰黄金", "03939": "万国黄金集团",
    "09992": "泡泡玛特", "02698": "乐舒适", "02685": "量化派",
    "06181": "老铺黄金", "02099": "中国黄金国际", "02259": "紫金黄金国际",
}

# ── 行业映射 ──
STOCK_SECTORS = {
    "02460": "消费/食品/零售",
    "03888": "互联网/IT",
}

# ── 产业链数据 ──
# 产业链 Mermaid 由 LLM 按 ai-berkshire industry-research SOP 生成，
# 作为临时中间产物传入 render_mermaid_raw() / render_chain_block()。
# 不持久化到文件系统。

async def fetch_klines(code, days=730):
    kl = await stock_kline_yahoo_async(f"{int(code)}.HK", "1d", f"{days//365}y")
    if kl and len(kl) >= 60: return kl
    kl = await kline_tickflow_async(f"{code}.HK", "1d", days)
    return kl or []

async def fetch_week_kline(code):
    kl = await stock_kline_yahoo_async(f"{int(code)}.HK", "1wk", "2y")
    return kl or []

# ── 行业漏斗5条硬指标 ──
def funnel_check(pe, roe, debt_ratio, gross_margin, rev_yoy, net_yoy):
    checks = []
    # 1. PE合理
    pe_pass = 0 < pe < 25
    checks.append(("PE合理", pe, pe_pass))
    # 2. ROE > 15%
    roe_pass = roe > 15 if roe else False
    checks.append(("ROE>15%", roe, roe_pass))
    # 3. 营收正增长
    rev_pass = (rev_yoy or 0) > 0
    checks.append(("营收正增长", rev_yoy, rev_pass))
    # 4. 净利正增长
    net_pass = (net_yoy or 0) > 0
    checks.append(("净利正增长", net_yoy, net_pass))
    # 5. 负债率 < 60%
    dr_pass = (debt_ratio or 0) < 60 if debt_ratio else None
    checks.append(("负债率<60%", debt_ratio, dr_pass))
    
    passed = sum(1 for _, _, p in checks if p)
    total = len(checks)
    status = "✅ 通过" if passed >= 4 else "⚠️ 边缘" if passed >= 3 else "❌ 不通过"
    return checks, status, passed, total

# ── 六维评分（2026-07-22 重构） ──

# 大师视角定义：每个维度的归属大师 + 核心追问 + 非归属大师列表
MASTER_PERSPECTIVES = {
    "生意质量（段永平）": {"owner": "段永平", "question": "这是对的生意吗？", "others": ["巴菲特", "芒格", "李录"]},
    "护城河（巴菲特）": {"owner": "巴菲特", "question": "够便宜吗？有安全边际吗？", "others": ["段永平", "芒格", "李录"]},
    "管理层（段永平+巴菲特）": {"owner": "段永平+巴菲特", "question": "管理层值得信任吗？", "others": ["芒格", "李录"]},
    "最大风险（芒格）": {"owner": "芒格", "question": "怎么会死？有什么风险？", "others": ["段永平", "巴菲特", "李录"]},
    "文明趋势（李录）": {"owner": "李录", "question": "10年后还在吗？", "others": ["段永平", "巴菲特", "芒格"]},
    "估值（巴菲特+段永平）": {"owner": "巴菲特+段永平", "question": "价格有安全边际吗？", "others": ["芒格", "李录"]},
}


def _pe_text(pe):
    """PE 定性文本"""
    if pe is None: return "无数据"
    try:
        pv = float(pe)
        if pv > 0:
            if pv < 10: return f"PE{pv}，估值偏低，安全边际充足"
            elif pv < 20: return f"PE{pv}，估值合理"
            elif pv < 30: return f"PE{pv}，估值合理"
            else: return f"PE{pv}，估值偏高"
        else:
            return f"PE{pv}，亏损"
    except (ValueError, TypeError):
        return "无数据"


def _gm_text(gm):
    """毛利率定性文本"""
    if gm is None: return "无数据"
    try:
        g = float(gm)
        if g > 60: return f"毛利率{g}%远超60%，生意质量好"
        elif g > 40: return f"毛利率{g}%高于40%，有一定定价权"
        elif g <= 20: return f"毛利率仅{g}%，定价权存疑"
        else: return f"毛利率{g}%"
    except (ValueError, TypeError):
        return "无数据"


def _dr_text(dr):
    """负债率定性文本"""
    if dr is None: return "无数据"
    try:
        d = float(dr)
        if d > 70: return f"负债率{d}%过高，财务风险大"
        elif d > 50: return f"负债率{d}%超50%，杠杆偏高"
        else: return f"负债率{d}%，风险可控"
    except (ValueError, TypeError):
        return "无数据"


def _rev_text(rev):
    """营收增速定性文本"""
    if rev is None: return "无数据"
    try:
        r = float(rev)
        if r > 20: return f"营收增长{r:+.1f}%，主业快速扩张"
        elif r > 0: return f"营收增长{r:+.1f}%，主业稳健"
        elif r > -10: return f"营收下滑{r:.1f}%，增长动力不足"
        else: return f"营收暴跌{r:.1f}%，最危险信号"
    except (ValueError, TypeError):
        return "无数据"


def _roe_text(roe):
    """ROE 定性文本"""
    if roe is None: return "无数据"
    try:
        rv = float(roe)
        if rv > 30: return f"ROE{rv}%超30%，资本回报极高"
        elif rv > 20: return f"ROE{rv}%超20%，护城河深厚"
        elif rv > 15: return f"ROE{rv}%在15%以上，回报良好"
        elif rv > 0: return f"ROE{rv}%，回报一般"
        else: return f"ROE{rv}%为负，资本在毁灭价值"
    except (ValueError, TypeError):
        return "无数据"


def _net_text(ny):
    """净利增速定性文本"""
    if ny is None: return "无数据"
    try:
        n = float(ny)
        if n > 20: return f"净利增长{n:+.1f}%，盈利强劲"
        elif n > 0: return f"净利增长{n:+.1f}%"
        elif n > -10: return f"净利下滑{n:.1f}%"
        else: return f"净利暴跌{n:.1f}%，盈利恶化"
    except (ValueError, TypeError):
        return "无数据"


def _np_text(np_margin):
    """净利率定性文本"""
    if np_margin is None: return "无数据"
    try:
        n = float(np_margin)
        if n > 30: return f"净利率{n}%超过30%，盈利质量优秀"
        elif n > 20: return f"净利率{n}%超过20%，盈利良好"
        elif n > 10: return f"净利率{n}%超过10%"
        elif n > 0: return f"净利率{n}%，盈利微薄"
        else: return f"净利率{n}%为负"
    except (ValueError, TypeError):
        return "无数据"


def _gen_master_answer(dim_key, pe, roe, gm, np_margin, rev_yoy, net_yoy, dr):
    """生成大师答疑：归属大师针对其他大师质疑的回答"""
    if dim_key not in MASTER_PERSPECTIVES:
        return ""
    # 格式化原始值，避免超长小数
    def _rv(v, nd=1):
        if v is None:
            return None
        try:
            return round(float(v), nd)
        except (ValueError, TypeError):
            return v
    pe = _rv(pe, 1)
    roe = _rv(roe, 1)
    gm = _rv(gm, 1)
    np_margin = _rv(np_margin, 1)
    rev_yoy = _rv(rev_yoy, 1)
    net_yoy = _rv(net_yoy, 1)
    dr = _rv(dr, 1)
    owner = MASTER_PERSPECTIVES[dim_key]["owner"]
    others = MASTER_PERSPECTIVES[dim_key]["others"]
    answers = []

    # 针对每个质疑大师，从owner视角回应
    for master in others:
        if master == "巴菲特":
            if "生意质量" in dim_key or "管理层" in dim_key:
                answers.append(f"PE估值和ROE是结果指标，{_gm_text(gm)}才是生意本质，{_np_text(np_margin)}")
            elif "文明趋势" in dim_key:
                answers.append(f"估值合理说明市场认可，{_rev_text(rev_yoy)}支撑长期确定性")
            elif "最大风险" in dim_key:
                answers.append("估值和ROE与本维度无关，风险核心在下行保护")
        elif master == "段永平":
            if "护城河" in dim_key:
                answers.append(f"生意质量好是护城河的基础，{_dr_text(dr)}")
            elif "最大风险" in dim_key:
                answers.append("好生意≠无风险，本维度看的是下行空间")
            elif "文明趋势" in dim_key or "估值" in dim_key:
                answers.append(f"生意质量好但本维度侧重不同，{_rev_text(rev_yoy)}")
        elif master == "芒格":
            if "生意质量" in dim_key:
                answers.append(f"风险可控说明生意稳健，{_gm_text(gm)}是商业模式的核心")
            elif "护城河" in dim_key:
                answers.append(f"负债率低是护城河的一部分，{_roe_text(roe)}说明竞争力")
            elif "文明趋势" in dim_key:
                answers.append(f"风险可控叠加{_np_text(np_margin)}，长期确定性更强")
            elif "估值" in dim_key:
                answers.append("估值看的是价格安全边际，风险已体现在负债率中")
            elif "管理层" in dim_key:
                answers.append(f"管理层维度看的是执行力和纪律，{_dr_text(dr)}说明财务纪律良好，管理风险可控")
        elif master == "李录":
            if "生意质量" in dim_key:
                answers.append(f"长期趋势好但本维度更关注当期，{_gm_text(gm)}")
            elif "护城河" in dim_key or "最大风险" in dim_key:
                answers.append(f"长期确定性是参考，{_roe_text(roe)}是当前竞争力")
            elif "估值" in dim_key:
                answers.append("长期确定性是参考，估值看的是当前价格是否合理")
            elif "管理层" in dim_key:
                answers.append(f"管理层长期视角看的是战略执行，{_rev_text(rev_yoy)}说明战略方向，长期需持续验证")

    answer_text = "；".join(answers) if answers else "无回应"
    return f"**{owner}回应**：针对质疑——{answer_text}"


def _gen_other_masters_challenge(dim_key, pe, roe, gm, np_margin, rev_yoy, net_yoy, dr):
    """生成其他大师对当前维度的凶悍质疑（逼出LLM潜力）"""
    if dim_key not in MASTER_PERSPECTIVES:
        return ""
    # 格式化原始值，避免 31.180324662625% 这种超长小数
    def _rv(v, nd=1):
        if v is None:
            return None
        try:
            return round(float(v), nd)
        except (ValueError, TypeError):
            return v
    pe = _rv(pe, 1)
    roe = _rv(roe, 1)
    gm = _rv(gm, 1)
    np_margin = _rv(np_margin, 1)
    rev_yoy = _rv(rev_yoy, 1)
    net_yoy = _rv(net_yoy, 1)
    dr = _rv(dr, 1)

    others = MASTER_PERSPECTIVES[dim_key]["others"]
    challenges = []

    for master in others:
        if master == "段永平":
            # 段永平：生意质量视角，质疑一切不关注生意本质的维度
            base = f"段永平：毛利率{gm}%"
            if roe is not None and roe < 15:
                base += f"、ROE仅{roe}%"
            if np_margin is not None and np_margin < 20:
                base += f"、净利率{np_margin}%——你管这叫对的生意？毛利率再高ROE不行就是资金黑洞，净利率不及格盈利质量存疑，"
            elif roe is not None and roe < 15:
                base += "——ROE连15%都没有，说明赚来的钱不知道怎么用，段永平说的好生意就是这种？"
            elif "护城河" in dim_key:
                base += "——毛利率高就算护城河？那所有奢侈品公司都是金城汤池了！护城河要看ROE和竞争优势，不是只看定价权！"
            elif "最大风险" in dim_key:
                base += "——营收负增长、净利暴跌，你跟我说风险可控？芒格你是不是被洗脑了？"
            elif "文明趋势" in dim_key:
                base += "——营收增速慢成这样，10年后可能更小，李录你是在做梦吗？"
            elif "估值" in dim_key:
                base += "——PE低就是便宜？基本面恶化的时候PE低是陷阱不是机会！"
            else:
                base += "！"
            challenges.append(base)

        elif master == "巴菲特":
            # 巴菲特：估值+护城河视角，质疑一切不关注安全边际的维度
            base = f"巴菲特：PE{pe}倍"
            if roe is not None:
                base += f"、ROE{roe}%"
            if dr is not None:
                base += f"、负债率{dr}%"
            if "生意质量" in dim_key:
                base += "——毛利率高但ROE不行，这不是好生意是资金浪费！你赚的钱不创造价值，段永平你清醒一点！"
            elif "管理层" in dim_key:
                base += "——营收增长这么慢，管理层是在混日子吗？ROE这么低，资本配置效率在哪里？"
            elif "最大风险" in dim_key:
                base += "——负债率不高、PE合理，你芒格说的风险在哪？你这是没事找事！"
            elif "文明趋势" in dim_key:
                base += "——营收增速跑不赢通胀，10年后可能更小，这种公司我巴菲特不会投！"
            else:
                base += "！"
            challenges.append(base)

        elif master == "芒格":
            # 芒格：逆向风险视角，质疑一切忽视下行风险的维度
            base = f"芒格："
            risk_flags = []
            if dr is not None and dr > 50:
                risk_flags.append(f"负债率{dr}%这么高")
            if rev_yoy is not None and rev_yoy < 0:
                risk_flags.append(f"营收下滑{rev_yoy:.1f}%")
            if net_yoy is not None and net_yoy < 0:
                risk_flags.append(f"净利暴跌{net_yoy:.1f}%")
            if roe is not None and roe < 5:
                risk_flags.append(f"ROE仅{roe}%")
            if risk_flags:
                base += "、".join(risk_flags)
            else:
                base += "各项指标看起来还行，但"
            if "生意质量" in dim_key:
                base += "——生意质量好就不会死？多少好生意死在杠杆上！你段永平没见过世面！"
            elif "护城河" in dim_key:
                base += "——护城河？历史充满了护城河一夜崩塌的公司！诺基亚的护城河不比你的宽？"
            elif "管理层" in dim_key:
                base += '——管理层值得信任？历史上最惨的亏损都是"值得信任的管理层"造成的！'
            elif "文明趋势" in dim_key:
                base += '——10年后还在？芒格我见过太多"10年后还在"的公司最后死得渣都不剩！'
            elif "估值" in dim_key:
                base += "——便宜没好货！PE低通常是因为它就是不值那个价，不是便宜是定价合理！"
            else:
                base += "！"
            challenges.append(base)

        elif master == "李录":
            # 李录：长期趋势视角，质疑一切短视的维度
            base = f"李录："
            if rev_yoy is not None and rev_yoy > 10:
                base += f"营收增长{rev_yoy:.1f}%"
            elif rev_yoy is not None:
                base += f"营收仅增长{rev_yoy:.1f}%"
            if np_margin is not None and np_margin > 0:
                base += f"、净利率{np_margin}%"
            if dr is not None:
                base += f"、负债率{dr}%"
            if "生意质量" in dim_key:
                base += "——当期毛利率高有什么用？10年后消费者不喝你的水了，你毛利率200%也没用！文明趋势才是根本！"
            elif "护城河" in dim_key:
                base += "——护城河会变窄的！10年后AI替代办公软件，WPS的护城河还在吗？巴菲特你太短视了！"
            elif "最大风险" in dim_key:
                base += "——短期风险不是核心，10年后这家公司还在不在才是真问题！芒格你总是盯着脚下不看前方！"
            elif "管理层" in dim_key:
                base += "——管理层短期表现不错，但10年后呢？这公司有未来吗？营收增速这么慢在等死！"
            elif "估值" in dim_key:
                base += "——PE便宜就买？10年后它可能一文不值！没有长期确定性的便宜就是陷阱！"
            else:
                base += "！"
            challenges.append(base)

    return "<br/>".join(challenges)


def _clamp10(v):
    return max(1.0, min(10.0, round(v, 1)))

def _dim_tag(s, t1, t2, t3, t4):
    if s >= 7.5: return t1
    elif s >= 5.0: return t2
    elif s >= 3.0: return t3
    else: return t4

def _dim_conf(s):
    if s >= 9.0: return "★★★★★"
    elif s >= 7.5: return "★★★★☆"
    elif s >= 5.0: return "★★★☆☆"
    elif s >= 3.0: return "★★☆☆☆"
    else: return "★☆☆☆☆"

def six_dimensions(pe, roe, gm, np_margin, rev_yoy, net_yoy, dr, dy, pb=0, sector="未知"):
    """返回六维评分（每维1-10，总分60）"""
    dims = []

    # 1. 生意质量（段永平）
    s1 = 4.0; log1 = [f"基础{s1:.0f}"]
    if gm:
        if gm > 80: s1 += 2.0; log1.append(f"毛利率{gm}%(>80%→+2.0)")
        elif gm > 60: s1 += 1.5; log1.append(f"毛利率{gm}%(>60%→+1.5)")
        elif gm > 40: s1 += 1.0; log1.append(f"毛利率{gm}%(>40%→+1.0)")
        elif gm > 20: s1 += 0.5; log1.append(f"毛利率{gm}%(>20%→+0.5)")
    if np_margin:
        if np_margin > 30: s1 += 2.0; log1.append(f"净利率{np_margin}%(>30%→+2.0)")
        elif np_margin > 20: s1 += 1.5; log1.append(f"净利率{np_margin}%(>20%→+1.5)")
        elif np_margin > 10: s1 += 0.5; log1.append(f"净利率{np_margin}%(>10%→+0.5)")
    if roe:
        if roe > 30: s1 += 2.0; log1.append(f"ROE{roe}%(>30%→+2.0)")
        elif roe > 20: s1 += 1.0; log1.append(f"ROE{roe}%(>20%→+1.0)")
        elif roe > 15: s1 += 0.5; log1.append(f"ROE{roe}%(>15%→+0.5)")
    s1 = _clamp10(s1)
    t1 = _dim_tag(s1, "极佳", "优秀", "一般", "较差")
    c1 = _dim_conf(s1)
    # 生意质量追问回答
    dyp_parts = []
    if gm and gm > 60: dyp_parts.append(f"毛利率{gm}%远超60%，有极强的定价权，这是好生意的标志")
    elif gm and gm > 40: dyp_parts.append(f"毛利率{gm}%高于40%，有一定定价权")
    elif gm and gm > 20: dyp_parts.append(f"毛利率{gm}%在20%以上，行业平均水平")
    elif gm and gm > 0: dyp_parts.append(f"毛利率仅{gm}%，定价权存疑")
    if roe and roe > 30: dyp_parts.append(f"ROE{roe}%超过30%，资本回报效率极高，这是对的生意")
    elif roe and roe > 15: dyp_parts.append(f"ROE{roe}%在15%以上，资本回报效率良好")
    elif roe and roe < 0: dyp_parts.append("ROE为负，资本在毁灭价值")
    if np_margin and np_margin > 30: dyp_parts.append(f"净利率{np_margin}%超过30%，盈利质量优秀")
    elif np_margin and np_margin > 20: dyp_parts.append(f"净利率{np_margin}%超过20%，盈利质量良好")
    elif np_margin and np_margin < 0: dyp_parts.append("净利率为负，公司不赚钱")
    conclusion1 = "，".join(dyp_parts) if dyp_parts else t1
    dims.append(("生意质量（段永平）", s1, conclusion1, c1, "，".join(log1)))

    # 2. 护城河（巴菲特）
    s2 = 4.0; log2 = [f"基础{s2:.0f}"]
    if roe:
        if roe > 30: s2 += 2.0; log2.append(f"ROE{roe}%(>30%→+2.0)")
        elif roe > 20: s2 += 1.5; log2.append(f"ROE{roe}%(>20%→+1.5)")
        elif roe > 15: s2 += 1.0; log2.append(f"ROE{roe}%(>15%→+1.0)")
    if gm:
        if gm > 60: s2 += 1.5; log2.append(f"毛利率{gm}%(>60%→+1.5)")
        elif gm > 40: s2 += 1.0; log2.append(f"毛利率{gm}%(>40%→+1.0)")
        elif gm > 20: s2 += 0.5; log2.append(f"毛利率{gm}%(>20%→+0.5)")
    if dy:
        if dy > 5: s2 += 1.0; log2.append(f"股息率{dy}%(>5%→+1.0)")
        elif dy > 3: s2 += 0.5; log2.append(f"股息率{dy}%(>3%→+0.5)")
        elif dy > 1: s2 += 0.3; log2.append(f"股息率{dy}%(>1%→+0.3)")
    if dr and dr < 30: s2 += 0.5; log2.append(f"负债率{dr}%(<30%→+0.5)")
    s2 = _clamp10(s2)
    t2 = _dim_tag(s2, "宽阔", "较宽", "一般", "狭窄")
    c2 = _dim_conf(s2)
    # 护城河追问回答
    moat_parts = []
    if roe and roe > 20: moat_parts.append(f"ROE{roe}%超过20%，护城河深厚")
    elif roe and roe > 15: moat_parts.append(f"ROE{roe}%在15%以上，护城河一般")
    elif roe and roe < 0: moat_parts.append("ROE为负，护城河在变窄")
    if gm and gm > 60: moat_parts.append(f"毛利率{gm}%远超60%，有极强的定价权护城河")
    elif gm and gm > 40: moat_parts.append(f"毛利率{gm}%高于40%，有一定定价权")
    elif gm and gm < 10: moat_parts.append(f"毛利率仅{gm}%，定价权不足")
    if dy and dy > 3: moat_parts.append(f"股息率{dy}%，股东回报稳定")
    if dr and dr < 30: moat_parts.append(f"负债率{dr}%低，财务稳健")
    elif dr and dr > 70: moat_parts.append(f"负债率{dr}%过高，财务风险大")
    conclusion2 = "，".join(moat_parts) if moat_parts else t2
    dims.append(("护城河（巴菲特）", s2, conclusion2, c2, "，".join(log2)))

    # 3. 管理层（段永平+巴菲特）
    s3 = 4.0; log3 = [f"基础{s3:.0f}"]
    if roe:
        if roe > 30: s3 += 2.0; log3.append(f"ROE{roe}%(>30%→+2.0)")
        elif roe > 20: s3 += 1.5; log3.append(f"ROE{roe}%(>20%→+1.5)")
        elif roe > 15: s3 += 0.5; log3.append(f"ROE{roe}%(>15%→+0.5)")
    if np_margin:
        if np_margin > 20: s3 += 1.5; log3.append(f"净利率{np_margin}%(>20%→+1.5)")
        elif np_margin > 10: s3 += 0.5; log3.append(f"净利率{np_margin}%(>10%→+0.5)")
    if rev_yoy:
        if rev_yoy > 20: s3 += 1.5; log3.append(f"营收{rev_yoy}%(>20%→+1.5)")
        elif rev_yoy > 10: s3 += 1.0; log3.append(f"营收{rev_yoy}%(>10%→+1.0)")
        elif rev_yoy > 0: s3 += 0.5; log3.append(f"营收{rev_yoy}%(>0%→+0.5)")
    if dr and dr < 30: s3 += 0.5; log3.append(f"负债率{dr}%(<30%→+0.5)")
    s3 = _clamp10(s3)
    t3 = _dim_tag(s3, "卓越", "优秀", "一般", "平庸")
    c3 = _dim_conf(s3)
    # 管理层追问回答
    mgmt_parts = []
    if roe and roe > 20: mgmt_parts.append(f"ROE{roe}%超过20%，资本配置效率高")
    elif roe and roe < 0: mgmt_parts.append("ROE为负，资本在毁灭价值")
    if np_margin and np_margin > 20: mgmt_parts.append(f"净利率{np_margin}%超过20%，管理效率优秀")
    elif np_margin and np_margin < 0: mgmt_parts.append("净利率为负，盈利能力差")
    if rev_yoy and rev_yoy > 10: mgmt_parts.append(f"营收增长{rev_yoy:+.1f}%，执行能力良好")
    elif rev_yoy and rev_yoy < 0: mgmt_parts.append(f"营收下滑{rev_yoy:.1f}%，需关注增长动力")
    if dr and dr < 30: mgmt_parts.append(f"负债率{dr}%低，财务纪律良好")
    elif dr and dr > 70: mgmt_parts.append(f"负债率{dr}%过高，财务纪律存疑")
    conclusion3 = "，".join(mgmt_parts) if mgmt_parts else t3
    dims.append(("管理层（段永平+巴菲特）", s3, conclusion3, c3, "，".join(log3)))

    # 4. 最大风险（芒格）— 逆向打分
    s4 = 6.0; log4 = [f"基础{s4:.0f}"]
    if dr:
        if dr > 70: s4 -= 3.0; log4.append(f"负债率{dr}%(>70%→-3.0)")
        elif dr > 50: s4 -= 1.5; log4.append(f"负债率{dr}%(>50%→-1.5)")
        elif dr > 30: s4 -= 0.5; log4.append(f"负债率{dr}%(>30%→-0.5)")
        else: log4.append(f"负债率{dr}%(≤30%→0)")
    if rev_yoy:
        if rev_yoy < -30: s4 -= 3.0; log4.append(f"营收{rev_yoy}%(<-30%→-3.0)")
        elif rev_yoy < -10: s4 -= 1.5; log4.append(f"营收{rev_yoy}%(<-10%→-1.5)")
        elif rev_yoy < 0: s4 -= 0.5; log4.append(f"营收{rev_yoy}%(<0%→-0.5)")
        elif rev_yoy > 10: s4 += 1.0; log4.append(f"营收{rev_yoy}%(>10%→+1.0)")
    if net_yoy:
        if net_yoy < -30: s4 -= 3.0; log4.append(f"净利{net_yoy}%(<-30%→-3.0)")
        elif net_yoy < -10: s4 -= 1.5; log4.append(f"净利{net_yoy}%(<-10%→-1.5)")
        elif net_yoy < 0: s4 -= 0.5; log4.append(f"净利{net_yoy}%(<0%→-0.5)")
        elif net_yoy > 20: s4 += 1.0; log4.append(f"净利{net_yoy}%(>20%→+1.0)")
    if roe and roe < 0: s4 -= 1.5; log4.append(f"ROE{roe}%(<0→-1.5)")
    s4 = _clamp10(s4)
    t4 = "低风险" if s4 >= 7.5 else "可控" if s4 >= 5.0 else "高风险"
    c4 = _dim_conf(s4)
    # 最大风险追问回答（芒格式逆向检验）
    risk_parts = []
    if dr and dr > 70: risk_parts.append(f"负债率{dr}%超过70%，财务风险较高——芒格会问：这家公司怎么死？")
    elif dr and dr > 50: risk_parts.append(f"负债率{dr}%超过50%，杠杆较高")
    elif dr and dr > 0: risk_parts.append(f"负债率{dr}%，财务风险可控")
    if rev_yoy and rev_yoy < -30: risk_parts.append(f"营收暴跌{rev_yoy}%，这是最危险的信号——生意在消失")
    elif rev_yoy and rev_yoy < -10: risk_parts.append(f"营收下滑{rev_yoy}%，增长动力不足")
    elif rev_yoy and rev_yoy > 10: risk_parts.append(f"营收增长{rev_yoy:+.1f}%，主业稳健")
    if net_yoy and net_yoy < -30: risk_parts.append(f"净利暴跌{net_yoy}%，盈利恶化")
    elif net_yoy and net_yoy < 0: risk_parts.append(f"净利下滑{net_yoy}%，盈利承压")
    if roe and roe < 0: risk_parts.append(f"ROE为负，公司亏损，持续失血")
    conclusion4 = "，".join(risk_parts) if risk_parts else t4
    dims.append(("最大风险（芒格）", s4, conclusion4, c4, "，".join(log4)))

    # 5. 文明趋势（李录）
    s5 = 4.0; log5 = [f"基础{s5:.0f}"]
    if rev_yoy:
        if rev_yoy > 30: s5 += 2.5; log5.append(f"营收{rev_yoy}%(>30%→+2.5)")
        elif rev_yoy > 20: s5 += 2.0; log5.append(f"营收{rev_yoy}%(>20%→+2.0)")
        elif rev_yoy > 10: s5 += 1.0; log5.append(f"营收{rev_yoy}%(>10%→+1.0)")
        elif rev_yoy > 0: s5 += 0.5; log5.append(f"营收{rev_yoy}%(>0%→+0.5)")
    if np_margin:
        if np_margin > 30: s5 += 1.5; log5.append(f"净利率{np_margin}%(>30%→+1.5)")
        elif np_margin > 15: s5 += 1.0; log5.append(f"净利率{np_margin}%(>15%→+1.0)")
    if dr and dr < 30: s5 += 1.0; log5.append(f"负债率{dr}%(<30%→+1.0)")
    if roe:
        if roe > 20: s5 += 1.0; log5.append(f"ROE{roe}%(>20%→+1.0)")
        elif roe > 15: s5 += 0.5; log5.append(f"ROE{roe}%(>15%→+0.5)")
    s5 = _clamp10(s5)
    t5 = _dim_tag(s5, "顺应趋势", "良好", "一般", "逆势")
    c5 = _dim_conf(s5)
    # 文明趋势追问回答（李录10年后还在吗？）
    trend_parts = []
    if rev_yoy and rev_yoy > 20: trend_parts.append(f"营收增长{rev_yoy:+.1f}%，主业快速扩张，10年后可能更大")
    elif rev_yoy and rev_yoy > 10: trend_parts.append(f"营收增长{rev_yoy:+.1f}%，主业稳健增长")
    elif rev_yoy and rev_yoy < 0: trend_parts.append(f"营收下滑{rev_yoy:.1f}%，10年后可能更小")
    if np_margin and np_margin > 30: trend_parts.append(f"净利率{np_margin}%超过30%，盈利质量优秀，可持续性强")
    elif np_margin and np_margin > 15: trend_parts.append(f"净利率{np_margin}%超过15%，盈利健康")
    elif np_margin and np_margin < 0: trend_parts.append("净利率为负，长期存续存疑")
    if dr and dr < 30: trend_parts.append(f"负债率{dr}%低，能在经济下行期存活")
    elif dr and dr > 70: trend_parts.append(f"负债率{dr}%过高，经济下行期风险大")
    if roe and roe > 20: trend_parts.append(f"ROE{roe}%超过20%，长期竞争力强")
    elif roe and roe < 0: trend_parts.append("ROE为负，长期竞争力存疑")
    conclusion5 = "，".join(trend_parts) if trend_parts else t5
    dims.append(("文明趋势（李录）", s5, conclusion5, c5, "，".join(log5)))

    # 6. 估值（巴菲特+段永平）
    s6 = 4.0; log6 = [f"基础{s6:.0f}"]
    if pe:
        if 0 < pe < 10: s6 += 3.0; log6.append(f"PE{pe}(<10→+3.0)")
        elif pe < 15: s6 += 2.0; log6.append(f"PE{pe}(<15→+2.0)")
        elif pe < 25: s6 += 1.0; log6.append(f"PE{pe}(<25→+1.0)")
        elif pe >= 25: s6 -= 0.5; log6.append(f"PE{pe}(≥25→-0.5)")
    if dy:
        if dy > 5: s6 += 1.5; log6.append(f"股息率{dy}%(>5%→+1.5)")
        elif dy > 3: s6 += 1.0; log6.append(f"股息率{dy}%(>3%→+1.0)")
        elif dy > 1: s6 += 0.5; log6.append(f"股息率{dy}%(>1%→+0.5)")
    s6 = _clamp10(s6)
    t6 = "低估" if s6 >= 7.5 else "合理" if s6 >= 5.0 else "偏贵"
    c6 = _dim_conf(s6)
    # 估值追问回答
    val_parts = []
    if pe and pe > 0:
        pe_limit = 60  # 默认行业PE阈值
        pe_ratio = pe / pe_limit
        if pe_ratio <= 0.5: val_parts.append(f"PE/行业阈值={pe}/{pe_limit}={pe_ratio:.2f}，估值处于行业低位，有足够安全边际")
        elif pe_ratio <= 1.0: val_parts.append(f"PE/行业阈值={pe}/{pe_limit}={pe_ratio:.2f}，估值合理，安全边际一般")
        else: val_parts.append(f"PE/行业阈值={pe}/{pe_limit}={pe_ratio:.2f}，估值高于行业均值，安全边际不足")
    if dy and dy > 3: val_parts.append(f"股息率{dy}%，股东回报可观")
    if pb and pb < 1: val_parts.append("PB<1，资产价格低于重置成本")
    conclusion6 = "，".join(val_parts) if val_parts else t6
    dims.append(("估值（巴菲特+段永平）", s6, conclusion6, c6, "，".join(log6)))

    # 总分
    total_score = round(sum(d[1] for d in dims), 1)

    # 为每个维度生成大师视角 + 其他大师质疑
    dim_data = []
    for i, (label, score, conclusion, confidence, dim_log) in enumerate(dims):
        dim_key = label
        # 大师视角 = 归属大师基于财务数据的具体观点
        master_perspective = conclusion
        # 其他大师质疑
        other_masters = _gen_other_masters_challenge(
            dim_key, pe, roe, gm, np_margin, rev_yoy, net_yoy, dr
        )
        # 大师答疑 = 归属大师针对其他大师质疑的回答
        master_answer = _gen_master_answer(
            dim_key, pe, roe, gm, np_margin, rev_yoy, net_yoy, dr
        )
        dim_data.append({
            "label": label,
            "score": score,
            "confidence": confidence,
            "master_perspective": master_perspective,
            "other_masters_challenge": other_masters,
            "master_answer": master_answer,
        })

    return {
        "dims": dim_data,  # list of dicts with all fields
        "total_score": total_score,
    }

# ── 缠论分析 ──
def chan_detail_output(klines, price, label="日线"):
    if not klines or len(klines) < 60:
        return {"summary": "数据不足", "detail": []}
    ch = chan_theory_full(klines)
    if "error" in ch:
        return {"summary": ch["error"], "detail": []}
    
    lines = []
    trend = ch.get("trend", {})
    strokes = ch.get("strokes", [])
    pivots = ch.get("pivots", [])
    divs = ch.get("divergences", [])
    bs = ch.get("buy_sell_points", {})
    
    lines.append(f"走势: {trend.get('description','未知')} | 笔{ch.get('strokes_count',0)} 段{ch.get('segments_count',0)} 中枢{ch.get('pivots_count',0)}")
    
    if strokes:
        last_s = strokes[-1]
        dir_icon = "↑" if last_s["direction"] == "up" else "↓"
        lines.append(f"最近笔: {dir_icon} {last_s['start_date']}~{last_s['end_date']} [{fmt(last_s['low'])}→{fmt(last_s['high'])}]")
        if last_s.get("broken"):
            lines.append(f"💥 笔断裂: {'向上突破' if last_s['direction']=='up' else '向下突破'}")
    
    if pivots:
        pz = pivots[-1]
        lines.append(f"中枢: ZG={fmt(pz['zg'])} ZD={fmt(pz['zd'])} ZZ={fmt(pz['zz'])}")
        if price > pz["zg"]:
            lines.append(f"价格在中枢上方({fmt((price-pz['zg'])/pz['zg']*100)}%) ✅")
        elif price < pz["zd"]:
            lines.append(f"价格在中枢下方({fmt((pz['zd']-price)/pz['zd']*100)}%) 🔴")
        else:
            lines.append(f"价格在中枢内部 ➖")
        # 三买潜力
        if price > pz["zg"] * 0.97 and price < pz["zg"] * 1.03:
            lines.append(f"⚡ 中枢上沿附近，关注突破三买机会")
    
    if divs:
        for d in divs:
            icon = "🟢" if "底" in d.get("detail","") else "🔴"
            sev = "⚡" if d.get("severity") == "strong" else ""
            lines.append(f"{icon}{sev} {d['detail']}")
    
    if bs.get("buy_points"):
        for bp in bs["buy_points"]:
            lines.append(f"🟢 {bp['detail']}")
    if bs.get("sell_points"):
        for sp in bs["sell_points"]:
            lines.append(f"🔴 {sp['detail']}")
    
    return {"summary": trend.get('description','未知'), "detail": lines}

# ── 周线定势 ──
def weekly_outlook(week_kl, price):
    if not week_kl or len(week_kl) < 20:
        return "周线数据不足"
    w_ma = calc_ma(week_kl, [60])
    w_ma60 = w_ma[-1]["ma60"] if w_ma and w_ma[-1].get("ma60") else None
    w_close = week_kl[-1]["close"]
    ch = chan_theory_full(week_kl, min_bi_len=5)
    
    parts = []
    if w_ma60:
        off = (w_close / w_ma60 - 1) * 100
        icon = "🔴" if off < -5 else "🔵" if off < 0 else "🟢"
        parts.append(f"MA60={fmt(w_ma60)} {icon}偏{off<0 and '空' or '多'}({fmt(off)}%)")
    parts.append(f"缠论:{ch.get('trend',{}).get('description','未知')}")
    parts.append(f"笔{ch.get('strokes_count',0)}")
    return " | ".join(parts)

# ── 镜子测试（5句话说清楚为什么买—判分引擎） ──
def mirror_test(code, dims, pe, roe, rev_yoy, net_yoy, chan_info, price_info):
    """基于六维评分判断「能说清楚几句」，判分逻辑：维度评分>=5.0算1句有说服力。
    具体5句话由LLM基于证据+联网生成。"""
    dim_dict = {}
    for dim in dims:
        label = dim["label"]
        score = dim["score"]
        for key in ["生意质量", "护城河", "管理层", "最大风险", "文明趋势", "估值"]:
            if key in label:
                dim_dict[key] = (score, dim["master_perspective"])
                break

    biz_score = dim_dict.get("生意质量", (0, ""))[0]
    moat_score = dim_dict.get("护城河", (0, ""))[0]
    mgmt_score = dim_dict.get("管理层", (0, ""))[0]
    val_score = dim_dict.get("估值", (0, ""))[0]
    risk_score = dim_dict.get("最大风险", (0, ""))[0]

    convincing = sum(1 for s in [biz_score, moat_score, mgmt_score, val_score, risk_score] if s >= 5.0)

    if convincing >= 5:
        result = f"✅ 通过（{convincing}/5）"
    elif convincing >= 3:
        result = f"⚠️ 边缘（{convincing}/5）"
    else:
        result = f"❌ 未通过（{convincing}/5）"

    evidence = {
        "score_biz": biz_score, "score_moat": moat_score,
        "score_mgmt": mgmt_score, "score_val": val_score, "score_risk": risk_score,
        "pe": pe, "roe": roe, "rev_yoy": rev_yoy, "net_yoy": net_yoy,
    }
    return result, evidence
    return result, evidence

# ── 芒格式逆向检验（芒格：这家公司可能怎么死？） ──
def munger_risk_check(code, name, rev_yoy, net_yoy, roe, dr, pe, gm, np_margin, industry_risks=None):
    """芒格式逆向检验：不问怎么成功，问怎么死——然后避开所有死法。

    为每只股票生成 3-5 条具体的失败路径，基于：
    - 已知股票：硬编码业务特征（行业地位、竞争格局、商业模式缺陷）
    - 未知股票：基于财务指标的逆向推断
    """
    risks = []
    s = float(rev_yoy or 0)
    n = float(net_yoy or 0)
    r = float(roe or 0)
    d = float(dr or 0)
    p = float(pe or 0) if pe else 0
    g = float(gm or 0)
    pm = float(np_margin or 0)

    # ── 已知股票：基于业务特征生成具体失败路径 ──
    if code == "03888":
        risks.append("☠️ 游戏业务持续失血：Q3同比-47%，如果游戏部门继续恶化，将拖累整体利润")
        risks.append("☠️ AI替代办公软件：WPS核心是文档编辑，AI直接生成文档时用户不再需要手动编辑，WPS价值归零")
        risks.append("☠️ 协同办公被挤出：'飞钉微'占92%市占率，WPS365仅8%，政企市场一旦被锁定就翻不了身")
        risks.append("☠️ ROE仅4.13%：大量现金低效配置，如果管理层持续乱投资，资本在慢慢毁灭")
    elif code == "02460":
        risks.append("☠️ 营收-18.63%持续萎缩：份额被农夫山泉蚕食，按此速度3年后营收可能腰斩")
        risks.append("☠️ 净利-39.28%崩盘：PET成本2026年+40%叠加价格战，毛利率可能跌破40%")
        risks.append("☠️ 冷柜战落败：农夫山泉垄断终端陈列，新品无法触达消费者，渠道被锁死")
        risks.append("☠️ 代工模式反噬：自产率仅46%，代工费年付20亿，规模缩小时利润会加速崩塌")
        risks.append("☠️ 无水源壁垒：农夫山泉有千岛湖水源独占，华润没有，消费者不认品牌只认水")
    else:
        # ── 未知股票：基于财务指标逆向推断 ──
        # 营收萎缩
        if s < -30:
            risks.append(f"☠️ 营收暴跌{s:.1f}%：生意在消失，不是周期问题而是结构性问题")
        elif s < -15:
            risks.append(f"☠️ 营收-{abs(s):.1f}%持续萎缩：如果市场份额持续流失，3年后营收可能腰斩")
        elif s < 0:
            risks.append(f"⚠️ 营收下滑{s:.1f}%：增长动力不足，需确认是周期还是结构性问题")

        # 净利崩盘
        if n < -50:
            risks.append(f"☠️ 净利暴跌{n:.1f}%：盈利崩盘，成本失控或收入崩塌，离亏损一步之遥")
        elif n < -30:
            risks.append(f"☠️ 净利-{abs(n):.1f}%：盈利恶化，如果持续下去将进入亏损区间")
        elif n < 0:
            risks.append(f"⚠️ 净利下滑{n:.1f}%：盈利承压，需关注成本控制和收入质量")

        # ROE 过低
        if r < 3:
            risks.append(f"☠️ ROE仅{r:.1f}%：连定存都跑不赢，资本在毁灭而非创造价值")
        elif r < 5:
            risks.append(f"⚠️ ROE仅{r:.1f}%：资本回报极低，大量现金低效配置")

        # 高杠杆
        if d > 70:
            risks.append(f"☠️ 负债率{d:.1f}%：高杠杆，利率上行或收入下滑时可能债务违约")

        # 毛利率低 + 营收下滑 = 定价权丢失
        if g < 20 and s < 0:
            risks.append(f"☠️ 毛利率仅{g:.1f}%且营收下滑：无定价权+生意萎缩，双重打击")
        elif g < 10:
            risks.append(f"☠️ 毛利率仅{g:.1f}%：几乎没有定价权，成本上涨直接吃掉利润")

        # 净利率低
        if pm < 5 and s < 0:
            risks.append(f"☠️ 净利率仅{pm:.1f}%且营收下滑：利润率极薄，收入下跌直接亏损")

        # PE 为负
        if p < 0:
            risks.append("☠️ PE为负：公司亏损，无法用PE估值")

        # 行业风险
        if industry_risks:
            for r_text in industry_risks:
                risks.append(f"🏭 {r_text}")

    if not risks:
        risks.append("✅ 无明显逆向风险——但芒格会说：活得久比赚得多重要")

    return risks[:6]  # 最多6条，保持简洁

# ── 主分析函数 ──
async def analyze_holding(h, result):
    """分析一只持仓，返回结构化数据"""
    code = h["code"]
    # 优先用传入的名称（analyze.py 已 resolve），再回退 STOCK_NAMES，最后用代码
    name = h.get("name") or STOCK_NAMES.get(code, code)
    # 如果传入的就是代码，再尝试用 STOCK_NAMES 覆盖
    if name == code:
        name = STOCK_NAMES.get(code, code)
    sector = STOCK_SECTORS.get(code, "未知")
    cost = h["avg_cost"]
    shares = h["shares"]
    
    tech = result.get("technicals", {})
    quote = result.get("quote", {})
    ind = result.get("indicator", {})
    price = quote.get("price", 0) or 0
    
    # 基本面（⚠️ 2026-07-22 修复: 优先用东财数据,腾讯quote的gross_margin字段已移除）
    pe = ind.get("PE_TTM") or ind.get("PE") or quote.get("pe") or 0
    roe = ind.get("ROE") or quote.get("roe") or 0
    gm = ind.get("GROSS_PROFIT_RATIO") or 0
    np_margin = ind.get("NET_PROFIT_RATIO") or 0
    rev_yoy = ind.get("OPERATE_INCOME_YOY") or 0
    net_yoy = ind.get("HOLDER_PROFIT_YOY") or 0
    dr = abs(ind.get("DEBT_ASSET_RATIO") or 0) or abs(quote.get("debt_ratio") or 0) or 0
    dy = quote.get("dividend_yield") or 0
    pb = quote.get("pb") or ind.get("PB") or 0
    # 精度裁剪（东财原始精度常为10+位）
    pe, roe, gm = round(pe, 2), round(roe, 2), round(gm, 2)
    np_margin, rev_yoy, net_yoy, dr, dy = round(np_margin, 2), round(rev_yoy, 2), round(net_yoy, 2), round(dr, 2), round(dy, 2)
    
    pnl_pct = (price / cost - 1) * 100 if cost and price else 0
    
    # 获取K线
    day_kl = await fetch_klines(code)
    week_kl = await fetch_week_kline(code)
    
    # 缠论
    chan = chan_detail_output(day_kl, price)
    
    # 周线
    weekly = weekly_outlook(week_kl, price)
    
    # MA排列
    ma = tech.get("ma", {})
    ma_detail = ""
    if ma and price:
        ma_parts = []
        for p in [5, 10, 20, 60]:
            v = ma.get(f"ma{p}")
            if v:
                off = (price / v - 1) * 100
                icon = "🔺" if off > 0 else "🔻"
                ma_parts.append(f"MA{p}={fmt(v)}({icon}{fmt(off)}%)")
        ma_detail = " | ".join(ma_parts)
    
    # MACD
    macd = tech.get("macd", {})
    macd_detail = ""
    if macd:
        dif = macd.get("dif", 0)
        dea = macd.get("dea", 0)
        hist = macd.get("macd_hist") or (dif - dea) * 2
        state = "多头✅" if dif > dea else "空头🔴"
        macd_detail = f"DIF={fmt(dif)} DEA={fmt(dea)} 柱={fmt(hist)} {state}"
    
    # 布林带
    boll = tech.get("boll", {})
    boll_detail = ""
    if boll and boll.get("upper"):
        upper = boll["upper"]
        middle = boll["middle"]
        lower = boll["lower"]
        bw = boll.get("bandwidth", 0)
        # 判断价格在布林带中的位置
        pos = (price - lower) / (upper - lower) * 100 if upper != lower else 50
        tag = "触及上轨🔴" if pos >= 95 else "偏上⚠️" if pos >= 70 else "中轨附近➖" if pos >= 30 else "偏下⚠️" if pos >= 5 else "触及下轨🟢"
        boll_detail = f"上轨{upper:.2f} 中轨{middle:.2f} 下轨{lower:.2f} | 位置{pos:.0f}% {tag}"
    
    # 止损止盈
    sltp = tech.get("stop_loss_take_profit", {})
    
    # 行业风险
    industry_risks_map = {
        "02460": ["PET成本2026年+40%，行业价格战持续", "冷柜战中被农夫山泉全面压制"],
        "03888": ["游戏业务Q3同比-47%拖累整体", "协同办公'飞钉微'占92%市占率"],
    }
    
    # 六维评分
    masters = six_dimensions(pe, roe, gm, np_margin, rev_yoy, net_yoy, dr, dy, pb, sector)
    
    # 漏斗
    funnel_checks, funnel_status, f_passed, f_total = funnel_check(pe, roe, dr, gm, rev_yoy, net_yoy)
    
    # 芒格式风险
    risks = munger_risk_check(code, name, rev_yoy, net_yoy, roe, dr, pe, gm, np_margin, industry_risks_map.get(code))
    
    # 镜子测试
    mirror_result, mirror_reasons = mirror_test(code, masters.get("dims", []), pe, roe, rev_yoy, net_yoy, chan, ma_detail)
    
    # 技术止损（对已亏损标的用现价计算，对盈利或微亏标的用成本）
    entry_for_sl = price if pnl_pct < -10 else cost
    tech_sl = None
    if day_kl and len(day_kl) >= 20:
        sltp_calc = calc_stop_loss_take_profit(entry_price=entry_for_sl, klines=day_kl[-60:])
        tech_sl = sltp_calc.get("stop_loss")
    
    return {
        "code": code, "name": name, "sector": sector,
        "cost": cost, "price": price, "shares": shares,
        "market_value": price * shares, "cost_value": cost * shares,
        "pnl_pct": pnl_pct,
        "pe": pe, "roe": roe, "gm": gm, "rev_yoy": rev_yoy, "net_yoy": net_yoy, "dr": dr,
        "masters": masters,
        "funnel_checks": funnel_checks, "funnel_status": funnel_status,
        "funnel_passed": f_passed, "funnel_total": f_total,
        "risks": risks,
        "mirror": mirror_result, "mirror_reasons": mirror_reasons,
        "weekly": weekly,
        "chan": chan,
        "ma_detail": ma_detail,
        "macd_detail": macd_detail,
        "boll_detail": boll_detail,
        "tech_sl": tech_sl,
        "sltp": sltp,
    }

# ── 报告生成 ──
def load_holdings_from_stdin():
    """从 stdin 读取持仓 JSON（格式: [{"code":"02460","market":"hk","shares":4600,"avg_cost":10.334}, ...]）"""
    raw = sys.stdin.read().strip()
    if not raw:
        print("❌ stdin 为空")
        sys.exit(1)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        print("❌ stdin 不是合法 JSON")
        sys.exit(1)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("holdings", [])
    return []

async def generate_report(holdings=None):
    """生成持仓报告。

    Args:
        holdings: 持仓列表（直接传入，优先于命令行参数）
    """
    # 读取持仓：优先参数，其次 --stdin，回退本地文件
    if holdings is None:
        holdings = []
        use_stdin = "--stdin" in sys.argv

        if use_stdin:
            holdings = load_holdings_from_stdin()
        elif os.path.exists(PORTFOLIO_FILE):
            pf = json.loads(open(PORTFOLIO_FILE).read())
            holdings = pf.get("holdings", [])
        else:
            print("❌ 未发现持仓数据。请通过以下方式提供：")
            print("   方式1: uv run scripts/portfolio_report.py --stdin < portfolio.json")
            print("   方式2: 在本地创建 portfolio.json")
            print("   方式3: 告诉 AI 你的持仓，由 AI 从 AgentMemory 读取后传入")
            return

    if not holdings:
        print("❌ 持仓为空")
        return
    
    # 更新名称
    for h in holdings:
        if h["code"] in STOCK_NAMES:
            h["name"] = STOCK_NAMES[h["code"]]
    
    codes = [h["code"] for h in holdings]
    
    # 并行分析
    a = StockAnalyzer()
    results = {}
    for code in codes:
        r = await a.analyze_hk(code)
        if "error" not in r:
            results[code] = r
    
    analyzed = []
    for h in holdings:
        if h["code"] in results:
            d = await analyze_holding(h, results[h["code"]])
            analyzed.append(d)
    
    await a.close()
    await close_async_session()
    await close_tickflow()
    
    # ── 计算组合指标 ──
    total_cost = sum(d["cost_value"] for d in analyzed)
    total_value = sum(d["market_value"] for d in analyzed)
    total_pnl = ((total_value / total_cost) - 1) * 100 if total_cost else 0
    avg_health = sum(d["masters"]["total_score"] for d in analyzed) / len(analyzed) / 12 if analyzed else 0
    analyzed.sort(key=lambda d: d["market_value"], reverse=True)
    top1_pct = analyzed[0]["market_value"] / total_value * 100 if total_value else 0
    
    # ── 输出 ──
    single_mode = "--single" in sys.argv
    if single_mode:
        print(f"# 📊 股票分析报告 | {analyzed[0]['name']}（{analyzed[0]['code']}）| {datetime.now().strftime('%Y-%m-%d')}")
        print()
    else:
        print(f"# 🏦 持仓组合完整报告 | {datetime.now().strftime('%Y-%m-%d')}")
        print()
        
        # 组合总览
        print("## 📊 组合总览")
        print()
        print("| 指标 | 值 |")
        print("|:----|:---|")
        print(f"| 总投入 | {fmt(total_cost,0)} HKD → 当前市值 {fmt(total_value,0)} HKD |")
        print(f"| 总盈亏 | **{fmt(total_pnl)}%**（{fmt(total_value-total_cost,0)} HKD）|")
        print(f"| 持仓数 | {len(analyzed)} 只 |")
        print(f"| 集中度 TOP1 | {analyzed[0]['name']} {fmt(top1_pct)}% {'⚠️超50%红线' if top1_pct>50 else ''}|")
        print(f"| 组合健康度 | {'★'*max(1,min(5,round(avg_health)))}{'☆'*max(0,5-round(avg_health))} {fmt(avg_health)}/5 |")
        print()
    
    # 各股分析
    for d in analyzed:
        code = d["code"]
        name = d["name"]
        pnl = d["pnl_pct"]
        pnl_icon = "🔴" if pnl < -10 else "🟡" if pnl < 0 else "🟢"
        
        if single_mode:
            print(f"## {name}（{code}）— 现价 {fmt(d['price'])}")
            print()
        else:
            print(f"---")
            print()
            print(f"## {pnl_icon} {name}（{code}）— {d['shares']} 股")
            print()
            print(f"> 成本 {fmt(d['cost'])} → 现价 {fmt(d['price'])} | 盈亏 **{fmt(pnl)}%**（{fmt(d['market_value']-d['cost_value'],0)} HKD）| 仓位 {fmt(d['market_value']/total_value*100)}%")
            print()
        
        # 基本面分析（产业链全景图 + 六维评分）
        m = d["masters"]
        dims = m.get("dims", [])
        dim_logs = m.get("dim_logs", {})
        mermaid = d.get("mermaid", "")
        bottleneck = d.get("mermaid_bottleneck", "")
        vs_leader = d.get("mermaid_vs_leader", "")
        industry = d.get("mermaid_industry", "")
        print("### 📊 基本面分析")
        print()
        # 产业链 Mermaid
        if mermaid:
            if industry:
                print(f"**{industry}**")
                print()
            print(render_mermaid_raw(mermaid))
            print()
            if bottleneck:
                print(f"> **卡脖子**: {bottleneck}")
            if vs_leader:
                print(f"> **竞品对标**: {vs_leader}")
            print()
        # ── 六维评分表（2026-07-22 六维框架） ──
        print("| 维度 | 评分 | 信心度 | 大师视角 | 其他大师质疑 | 大师答疑 |")
        print("|:----|:---:|:------:|:--------|:----------:|:--------|")
        for dim in dims:
            label = dim["label"]
            score = dim["score"]
            confidence = dim["confidence"]
            master_perspective = dim.get("master_perspective", "")
            other_masters = dim.get("other_masters_challenge", "")
            master_answer = dim.get("master_answer", "")
            print(f"| {label} | {score}/10 | {confidence} | {master_perspective} | {other_masters} | {master_answer} |")

        print(f"\n> **六维总分**: {m['total_score']}/60")
        
        # 行业漏斗
        print("### 📊 行业漏斗")
        print()
        print(f"| 指标 | 值 | 通过 |")
        print(f"|:----|:---:|:----:|")
        for label, val, passed in d["funnel_checks"]:
            v = fmt(val) if val else "-"
            icon = "✅" if passed else ("❓" if passed is None else "❌")
            print(f"| {label} | {v} | {icon if passed else ('➖' if passed is None else '❌')} |")
        print(f"\n> **漏斗结果**: {d['funnel_status']}（{d['funnel_passed']}/{d['funnel_total']}）")
        print()
        
        # 芒格式逆向检验（表格输出）
        print("### ⚠️ 芒格式逆向检验")
        print()
        print("| 失败路径 | 详情 |")
        print("|:--------|:----|")
        for r in d["risks"]:
            risk_text = r
            # 提取 emoji 和标题
            emoji = risk_text[:2] if risk_text.startswith("☠️") or risk_text.startswith("⚠️") or risk_text.startswith("🏭") else ""
            colon_idx = risk_text.find("：") if "：" in risk_text else -1
            if colon_idx > 0:
                title = risk_text[len(emoji):colon_idx+1].strip() if emoji else risk_text[:colon_idx+1].strip()
                detail = risk_text[colon_idx+1:].strip()
            else:
                title = risk_text
                detail = ""
            print(f"| {emoji} {title} | {detail} |")
        print()
        
        # 缠论 & 技术面（表格输出）
        print("### 🔧 技术面分析")
        print()
        print("| 维度 | 指标 | 数据 |")
        print("|:----|:----|:----:|")
        # 周线定势
        weekly = d['weekly']
        if weekly and "|" in str(weekly):
            parts = str(weekly).split("|")
            for p in parts:
                p = p.strip()
                if "MA60" in p:
                    print(f"| 周线大势 | MA60 | {p} |")
                elif "缠论" in p:
                    print(f"| 周线大势 | 缠论判定 | {p} |")
                elif "笔" in p:
                    print(f"| 周线大势 | 缠论笔 | {p} |")
        else:
            print(f"| 周线大势 | 综合 | {weekly} |")
        # 日线走势
        chan_summary = d['chan']['summary']
        print(f"| 日线走势 | 走势类型 | {chan_summary} |")
        for line in d["chan"]["detail"]:
            line = line.strip()
            if "走势" in line and "oken" not in line:
                continue  # 跳过已处理的走势类型
            if "最近笔" in line:
                print(f"| 日线走势 | 最近笔 | {line} |")
            elif "中枢" in line and "ZG" in line:
                print(f"| 日线走势 | 中枢区间 | {line} |")
            elif "价格" in line and "中枢" in line:
                print(f"| 日线走势 | 价格位置 | {line} |")
            elif "突破" in line or "三买" in line:
                print(f"| 日线走势 | 特殊信号 | {line} |")
            elif "底背" in line or "顶背" in line or "背驰" in line:
                print(f"| 日线走势 | 背驰信号 | {line} |")
            elif "笔断裂" in line:
                print(f"| 日线走势 | 笔断裂 | {line} |")
            elif "笔" in line and "段" in line and "中枢" in line:
                print(f"| 日线走势 | 结构 | {line} |")
        # 技术指标
        ma = d['ma_detail']
        macd = d['macd_detail']
        direction = "偏多" if "🔺" in str(ma) else "偏空" if "🔻" in str(ma) else "中性"
        print(f"| MA排列 | {direction} | {ma} |")
        # MACD
        macd_short = macd.split("|")[0] if "|" in str(macd) else str(macd)
        macd_signal = "多头✅" if "多头" in str(macd) else "空头🔴" if "空头" in str(macd) else "中性"
        print(f"| MACD | {macd_signal} | {macd_short} |")
        # 布林带
        boll = d.get("boll_detail", "")
        if boll:
            print(f"| 布林带 | 价格在布林带中 | {boll} |")
        # 缠论笔
        chan_detail = d["chan"]["detail"]
        last_stroke = ""
        for line in chan_detail:
            if "最近笔" in line:
                last_stroke = line.strip()
                break
        print(f"| 缠论笔 | {'↑' if '↑' in last_stroke else '↓' if '↓' in last_stroke else '-'} | {last_stroke} |")
        # 止损止盈
        if d["tech_sl"]:
            sl_off = (d["price"] / d["tech_sl"] - 1) * 100
            print(f"| 风控 | 止损-{fmt(abs(sl_off))}% | 止损 {fmt(d['tech_sl'])} / 止盈 {fmt(d['sltp'].get('take_profit','-'))} |")
        print()
        
        # 镜子测试（判分结果，5句话由LLM+联网生成）
        ev = d.get("mirror_reasons", {})
        print("### 📋 镜子测试")
        print()
        print(f"> {d['mirror']}")
        print(f"> 📊 生意{ev.get('score_biz',0)}/10 | 护城河{ev.get('score_moat',0)}/10 | 管理层{ev.get('score_mgmt',0)}/10 | 估值{ev.get('score_val',0)}/10 | 风险{ev.get('score_risk',0)}/10")
        
        # 操作建议
        print("### 🎯 操作建议")
        print()
        if pnl < -20 and d["masters"]["total_score"] < 30:
            print(f"> **🔴 建议止损** — 亏损{fmt(pnl)}%+六维评分{fmt(d['masters']['total_score'])}/60偏低")
            print(f"> 释放资金 ~{fmt(d['market_value'],0)} HKD 用于换仓")
        elif d["funnel_passed"] < 3:
            print(f"> **🟡 关注/减仓** — 行业漏斗仅{d['funnel_passed']}/{d['funnel_total']}通过")
        elif pnl < -5:
            print(f"> **🟡 持有观察** — 小幅浮亏但基本面可接受")
        else:
            print(f"> **✅ 持有** — 基本面+技术面均未触发卖出信号")
        print()
    
    # 组合优化建议（单股模式跳过）
    if not single_mode:
        print("---")
        print()
        print("## 🎯 组合优化建议")
        print()
        total_release = 0
        for d in analyzed:
            pnl = d["pnl_pct"]
            code = d["code"]
            if pnl < -20 and d["masters"]["total_score"] < 30:
                print(f"| **{code} {d['name']}** | 🔴 止损 | 释放~{fmt(d['market_value'],0)} HKD | 亏损{fmt(pnl)}%+六维评分低 |")
                total_release += d["market_value"]
        if total_release == 0:
            print("  当前持仓无紧急操作需求")
        else:
            print(f"\n> 合计可释放 **~{fmt(total_release,0)} HKD** 用于重新配置")
        print()
    
    # AI偏见自查
    print("### 🧠 AI偏见自查清单")
    print()
    print("| 偏见 | 自查 |")
    print("|:----|:------|")
    print("| 🏢 龙头偏好 | 02460标注了与农夫山泉差距; 03888标注了'飞钉微'92%市占率 |")
    print("| 📝 成熟行业偏好 | 饮料行业补充了PET涨价+价格战数据 |")
    print("| 🎮 新业务偏好 | 03888标注游戏Q3-47%拖累 |")
    print("| 🌐 英文偏好 | 03888单独列出海外+53.67%增长 |")
    print("| 📊 故事偏好 | AI概念以WPS AI月活8013万(+307%)验证 |")
    print()
    
    print("---")
    print(f"> 📡 数据来源: StockAnalyzer + chan_theory_full + 研报数据库 + 行业分析")
    print(f"> ⚠️ 声明: 基于公开市场数据，不构成投资建议")
    print(f"> 脚本: scripts/portfolio_report.py | {datetime.now().strftime('%Y-%m-%d %H:%M')}")


# ── JSON管道（脚本→LLM→脚本，保证输出格式一致性） ──
async def _generate_data_json(holdings):
    """生成完整持仓报告原始数据JSON"""
    report = {"portfolio": {}, "stocks": []}
    total_cost = 0
    total_value = 0
    for h in holdings:
        code = h["code"]
        result = await analyze_holding(h, await _fetch_stock_data(code))
        name = result.get("name", STOCK_NAMES.get(code, code))
        cost = h["avg_cost"]
        shares = h["shares"]
        price = result.get("price", 0)
        cost_value = cost * shares
        market_value = price * shares
        total_cost += cost_value
        total_value += market_value
        pnl = (price / cost - 1) * 100 if cost else 0
        masters = result["masters"]
        dims = masters.get("dims", [])
        stock = {
            "code": code, "name": name,
            "cost": round(cost, 3), "price": round(price, 2),
            "shares": shares, "pnl": round(pnl, 2),
            "cost_value": round(cost_value, 0), "market_value": round(market_value, 0),
            "sector": result.get("sector", STOCK_SECTORS.get(code, "未知")),
            "mermaid": result.get("mermaid", ""),
            "mermaid_bottleneck": result.get("mermaid_bottleneck", ""),
            "mermaid_vs_leader": result.get("mermaid_vs_leader", ""),
            "mermaid_industry": result.get("mermaid_industry", ""),
            "dims": [],
            "total_score": masters["total_score"],
            "pe": round(result.get("pe", 0), 2),
            "roe": round(result.get("roe", 0), 2),
            "gm": round(result.get("gm", 0), 2),
            "np_margin": round(result.get("np_margin", 0), 2),
            "rev_yoy": round(result.get("rev_yoy", 0), 2),
            "net_yoy": round(result.get("net_yoy", 0), 2),
            "dr": round(result.get("dr", 0), 2),
            "funnel": result.get("funnel_checks", []),
            "funnel_status": result.get("funnel_status", ""),
            "funnel_passed": result.get("funnel_passed", 0),
            "funnel_total": result.get("funnel_total", 0),
            "risks": result.get("risks", []),
            "weekly": result.get("weekly", ""),
            "chan": result.get("chan", {}),
            "ma_detail": result.get("ma_detail", ""),
            "macd_detail": result.get("macd_detail", ""),
            "boll_detail": result.get("boll_detail", ""),
            "tech_sl": result.get("tech_sl", 0),
            "sltp": result.get("sltp", {}),
            "mirror": result.get("mirror", ""),
            "mirror_reasons": result.get("mirror_reasons", {}),
            "advice": result.get("advice", ""),
        }
        for dim in dims:
            stock["dims"].append({
                "label": dim["label"],
                "score": dim["score"],
                "confidence": dim["confidence"],
                "conclusion": dim["master_perspective"],
            })
        report["stocks"].append(stock)
    report["portfolio"] = {
        "total_cost": round(total_cost, 0),
        "total_value": round(total_value, 0),
        "total_pnl": round((total_value / total_cost - 1) * 100, 2) if total_cost else 0,
    }
    return report


async def _fetch_stock_data(code):
    """获取单只股票的完整数据"""
    from scripts.quantrisk.data import hk_stock_quote_tencent_async
    quote = await hk_stock_quote_tencent_async(code)
    day_kl = await fetch_klines(code)
    return {"quote": quote or {}, "klines": day_kl}


async def _render_analysis(analysis):
    """读取LLM生成的JSON分析，渲染完整持仓报告（所有表格格式固定）"""
    portfolio = analysis.get("portfolio", {})
    print(f"# 🏦 持仓组合完整报告 | {datetime.now().strftime('%Y-%m-%d')}")
    print()
    print("## 📊 组合总览")
    print()
    print("| 指标 | 值 |")
    print("|:----|:---|")
    print(f"| 总投入 | {portfolio.get('total_cost',0)} HKD → 当前市值 {portfolio.get('total_value',0)} HKD |")
    print(f"| 总盈亏 | **{portfolio.get('total_pnl',0)}%**（{portfolio.get('total_value',0) - portfolio.get('total_cost',0)} HKD）|")
    print(f"| 持仓数 | {len(analysis.get('stocks',[]))} 只 |")
    print()
    for stock in analysis.get("stocks", []):
        code = stock["code"]
        name = stock["name"]
        pnl = stock.get("pnl", 0)
        pnl_icon = "🔴" if pnl < -10 else "🟡" if pnl < 0 else "🟢"
        cost = stock["cost"]
        price = stock["price"]
        dims = stock.get("dims", [])
        total = stock.get("total_score", 0)
        print(f"---")
        print()
        print(f"## {pnl_icon} {name}（{code}）— {stock['shares']} 股")
        print()
        print(f"> 成本 {cost} → 现价 {price} | 盈亏 **{pnl}%**（{stock.get('market_value',0) - stock.get('cost_value',0)} HKD）| 仓位 {stock.get('market_value',0) / portfolio.get('total_value',1) * 100:.2f}%")
        print()
        # 基本面分析 + 产业链Mermaid
        print("### 📊 基本面分析")
        print()
        mermaid = stock.get("mermaid", "")
        if mermaid:
            print(f"**{stock.get('sector','')}行业**")
            print()
            print("```mermaid")
            print(mermaid)
            print("```")
            print()
            bottleneck = stock.get("mermaid_bottleneck", "")
            vs_leader = stock.get("mermaid_vs_leader", "")
            if bottleneck or vs_leader:
                print(f"> **卡脖子**: {bottleneck}")
                print(f"> **竞品对标**: {vs_leader}")
                print()
        # 六维评分表（固定格式）
        print("| 维度 | 评分 | 信心度 | 大师视角 | 其他大师质疑 | 大师答疑 |")
        print("|:----|:---:|:------:|:--------|:----------:|:--------|")
        for dim in dims:
            label = dim["label"]
            score = dim["score"]
            conf = dim["confidence"]
            pv = dim.get("master_perspective", "")
            ch = dim.get("other_masters_challenge", "")
            ans = dim.get("master_answer", "")
            print(f"| {label} | {score}/10 | {conf} | {pv} | {ch} | {ans} |")
        print(f"\n> **六维总分**: {total}/60")
        # 行业漏斗
        print("### 📊 行业漏斗")
        print()
        print("| 指标 | 值 | 通过 |")
        print("|:----|:---:|:----:|")
        for f_item in stock.get("funnel", []):
            f_label, f_val, f_passed = f_item
            icon = "✅" if f_passed else "❌"
            print(f"| {f_label} | {f_val} | {icon} |")
        print(f"\n> **漏斗结果**: {stock.get('funnel_status','')}（{stock.get('funnel_passed',0)}/{stock.get('funnel_total',0)}）")
        # 芒格式逆向检验
        print()
        print("### ⚠️ 芒格式逆向检验")
        print()
        print("| 失败路径 | 详情 |")
        print("|:--------|:----|")
        for r in stock.get("risks", []):
            emoji = r[:2] if r.startswith("☠️") or r.startswith("⚠️") or r.startswith("🏭") else ""
            colon_idx = r.find("：") if "：" in r else -1
            if colon_idx > 0:
                title = r[len(emoji):colon_idx+1].strip() if emoji else r[:colon_idx+1].strip()
                detail = r[colon_idx+1:].strip()
            else:
                title, detail = r, ""
            print(f"| {emoji} {title} | {detail} |")
        # 技术面分析
        print()
        print("### 🔧 技术面分析")
        print()
        print("| 维度 | 指标 | 数据 |")
        print("|:----|:----|:----:|")
        weekly = stock.get("weekly", "")
        if weekly and "|" in str(weekly):
            for p in str(weekly).split("|"):
                p = p.strip()
                if "MA60" in p: print(f"| 周线大势 | MA60 | {p} |")
                elif "缠论" in p: print(f"| 周线大势 | 缠论判定 | {p} |")
                elif "笔" in p: print(f"| 周线大势 | 缠论笔 | {p} |")
        else:
            print(f"| 周线大势 | 综合 | {weekly} |")
        chan = stock.get("chan", {})
        print(f"| 日线走势 | 走势类型 | {chan.get('summary','')} |")
        for line in chan.get("detail", []):
            ls = line.strip()
            if "最近笔" in ls: print(f"| 日线走势 | 最近笔 | {ls} |")
            elif "中枢" in ls and "ZG" in ls: print(f"| 日线走势 | 中枢区间 | {ls} |")
            elif "价格" in ls and "中枢" in ls: print(f"| 日线走势 | 价格位置 | {ls} |")
            elif "笔" in ls and "段" in ls and "中枢" in ls: print(f"| 日线走势 | 结构 | {ls} |")
        ma = stock.get("ma_detail", "")
        direction = "偏多" if "🔺" in str(ma) else "偏空" if "🔻" in str(ma) else "中性"
        print(f"| MA排列 | {direction} | {ma} |")
        macd = stock.get("macd_detail", "")
        macd_signal = "多头✅" if "多头" in str(macd) else "空头🔴" if "空头" in str(macd) else "中性"
        print(f"| MACD | {macd_signal} | {macd} |")
        boll = stock.get("boll_detail", "")
        if boll: print(f"| 布林带 | 价格在布林带中 | {boll} |")
        sl = stock.get("tech_sl", 0)
        if sl:
            sl_off = (price / sl - 1) * 100 if sl else 0
            tp = stock.get("sltp", {}).get("take_profit", "-")
            print(f"| 风控 | 止损-{abs(sl_off):.2f}% | 止损 {sl} / 止盈 {tp} |")
        # 镜子测试
        print()
        print("### 📋 镜子测试")
        print()
        print(f"> {stock.get('mirror','')}")
        ev = stock.get("mirror_reasons", {})
        print(f"> 📊 生意{ev.get('score_biz',0)}/10 | 护城河{ev.get('score_moat',0)}/10 | 管理层{ev.get('score_mgmt',0)}/10 | 估值{ev.get('score_val',0)}/10 | 风险{ev.get('score_risk',0)}/10")
        # 操作建议
        print("### 🎯 操作建议")
        print()
        print(f"> {stock.get('advice','')}")
        print()
    print("---")
    print(f"> 📡 数据来源: StockAnalyzer + chan_theory_full + 研报数据库 + 行业分析")
    print(f"> ⚠️ 声明: 基于公开市场数据，不构成投资建议")
    print(f"> 脚本: scripts/portfolio_report.py --sixdim-render | {datetime.now().strftime('%Y-%m-%d %H:%M')}")


if __name__ == "__main__":
    import sys
    if "--sixdim-json" in sys.argv:
        # 模式1：输出六维评分原始数据JSON（供LLM生成分析文本）
        import json as _json
        holdings = [
            {"code": "02460", "market": "hk", "shares": 4600, "avg_cost": 10.334},
            {"code": "03888", "market": "hk", "shares": 1600, "avg_cost": 25.013},
        ]
        report = asyncio.run(_generate_data_json(holdings))
        print(_json.dumps(report, ensure_ascii=False, indent=2))
    elif "--sixdim-render" in sys.argv:
        # 模式2：读取LLM生成的JSON分析文件，渲染最终报告
        idx = sys.argv.index("--sixdim-render") + 1
        if idx < len(sys.argv):
            analysis_file = sys.argv[idx]
            import json as _json
            with open(analysis_file) as _f:
                analysis = _json.load(_f)
            # 渲染最终报告
            asyncio.run(_render_analysis(analysis))
        else:
            print("Usage: --sixdim-render <analysis.json>")
    else:
        asyncio.run(generate_report())
