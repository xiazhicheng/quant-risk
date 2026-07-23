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

# ── 公墓爷树 ──
INDUSTRY_CHAINS = {
    "02460": {
        "name": "饮料行业",
        "mermaid": """graph TB
    subgraph 上游_原材料
        PET[PET 聚酯瓶片<br/>⚠️2026年+40%]
        Water[水源<br/>❌无独占水源]
        Pkg[瓶盖/标签/纸箱]
    end
    subgraph 中游_生产制造
        Own[自有工厂 13家<br/>产量占比46% ↑]
        OEM[合作代工厂 35家<br/>产量占比54%<br/>💸年付20亿代工费]
    end
    subgraph 下游_渠道终端
        Trad[传统经销商<br/>1,198家 + 3,938家次级]
        Cold[冷柜/现代渠道<br/>🔴冷柜战落败]
        EC[电商/特通<br/>🟢CAGR+34%]
    end
    subgraph 终端消费者
        User[消费者<br/>个人 / 家庭 / 企业]
    end
    PET -->|供应原料| Own & OEM
    Water -->|供应水源| Own & OEM
    Pkg -->|供应包材| Own & OEM
    Own -->|自主生产 46%| Trad & Cold & EC
    OEM -->|代工生产 54%| Trad & Cold & EC
    Trad & Cold & EC -->|触达| User""",
        "bottleneck": "🔴 PET原料价格波动（占成本20%+）| 🔴 自产率仅46%代工费吞噬利润",
        "vs_leader": "vs 农夫山泉 — 毛利率-13.6pp | 饮料收入占比-47.7pp | 市值1:23",
    },
    "03888": {
        "name": "软件/办公行业",
        "mermaid": """graph TB
    subgraph 上游_技术算力
        LLM[AI大模型<br/>OpenAI / 国产]
        Cloud[云计算 IaaS<br/>🟢金山云协同]
        HW[硬件终端<br/>🟢WPS for iPad]
    end
    subgraph 中游_软件平台
        WPS[WPS Office<br/>✅月活6.78亿<br/>💰现金牛]
        WPS365[WPS 365 协同<br/>⚠️连续4Q+60%<br/>但市占率<8%]
        WPSAI[WPS AI<br/>🟢月活8013万<br/>🚀+307%]
        Game[游戏业务<br/>🔴Q3同比-47%<br/>拖累]
    end
    subgraph 下游_用户场景
        C[个人用户<br/>6.78亿月活<br/>天花板渐近]
        B[政企客户<br/>✅75%双一流高校<br/>✅信创壁垒]
        O[海外用户<br/>🟢2.45亿月活<br/>🚀+53.67%]
    end
    subgraph 竞争格局
        DD[钉钉 ~2亿月活]
        WX[企业微信 ~1亿月活]
        FS[飞书 ~5000万月活]
    end
    LLM -->|提供AI能力| WPSAI
    Cloud -->|基础设施| WPS365 & WPS
    HW -->|运行平台| WPS
    WPSAI -->|赋能| WPS & WPS365
    WPS -->|办公服务| C & O
    WPS365 -->|协同办公| B
    WPS365 -.->|竞争 92%市占率| DD & WX & FS
    Game -->|娱乐| C""",
        "bottleneck": "🔴 AI大模型依赖外部 | 🔴 协同办公'飞钉微'占92%市占率",
        "vs_leader": "转型关键: WPS从工具→平台转型，研发投入20.95亿(+23.57%)",
    },
}

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
        elif master == "李录":
            if "生意质量" in dim_key:
                answers.append(f"长期趋势好但本维度更关注当期，{_gm_text(gm)}")
            elif "护城河" in dim_key or "最大风险" in dim_key:
                answers.append(f"长期确定性是参考，{_roe_text(roe)}是当前竞争力")
            elif "估值" in dim_key:
                answers.append("长期确定性是参考，估值看的是当前价格是否合理")

    answer_text = "；".join(answers) if answers else "无回应"
    return f"**{owner}回应**：针对质疑——{answer_text}"


def _gen_other_masters_challenge(dim_key, pe, roe, gm, np_margin, rev_yoy, net_yoy, dr):
    """生成其他大师对当前维度的质疑"""
    if dim_key not in MASTER_PERSPECTIVES:
        return ""

    others = MASTER_PERSPECTIVES[dim_key]["others"]
    challenges = []

    for master in others:
        if master == "段永平":
            parts = []
            parts.append(_gm_text(gm))
            parts.append(_roe_text(roe))
            parts.append(_np_text(np_margin))
            challenges.append(f"段永平：{'；'.join(parts)}")
        elif master == "巴菲特":
            parts = []
            parts.append(_pe_text(pe))
            parts.append(_roe_text(roe))
            parts.append(_dr_text(dr))
            challenges.append(f"巴菲特：{'；'.join(parts)}")
        elif master == "芒格":
            parts = []
            parts.append(_dr_text(dr))
            parts.append(_rev_text(rev_yoy))
            parts.append(_net_text(net_yoy))
            challenges.append(f"芒格：{'；'.join(parts)}")
        elif master == "李录":
            parts = []
            parts.append(_rev_text(rev_yoy))
            parts.append(_np_text(np_margin))
            parts.append(_dr_text(dr))
            challenges.append(f"李录：{'；'.join(parts)}")

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

# ── 镜子测试（5句话说清楚为什么买—判分引擎+问答生成） ──
def mirror_test(code, dims, pe, roe, rev_yoy, net_yoy, chan_info, price_info, gm=0, np_margin=0, net_yoy_val=0, dr=0, dy=0, sl=0, tp=0):
    """基于六维评分判断「能说清楚几句」，并生成5个问答条目。
    判分逻辑：维度评分>=5.0算1句有说服力。"""
    dim_dict = {}
    for dim in dims:
        label = dim["label"]
        score = dim["score"]
        conclusion = dim["master_perspective"]
        for key in ["生意质量", "护城河", "管理层", "最大风险", "文明趋势", "估值"]:
            if key in label:
                dim_dict[key] = (score, conclusion)
                break

    biz_score = dim_dict.get("生意质量", (0, ""))[0]
    biz_conclusion = dim_dict.get("生意质量", (0, ""))[1]
    moat_score = dim_dict.get("护城河", (0, ""))[0]
    moat_conclusion = dim_dict.get("护城河", (0, ""))[1]
    mgmt_score = dim_dict.get("管理层", (0, ""))[0]
    val_score = dim_dict.get("估值", (0, ""))[0]
    val_conclusion = dim_dict.get("估值", (0, ""))[1]
    risk_score = dim_dict.get("最大风险", (0, ""))[0]

    convincing = sum(1 for s in [biz_score, moat_score, mgmt_score, val_score, risk_score] if s >= 5.0)

    if convincing >= 5:
        result = f"✅ 通过（{convincing}/5）"
    elif convincing >= 3:
        result = f"⚠️ 边缘（{convincing}/5）"
    else:
        result = f"❌ 未通过（{convincing}/5）"

    # 生成5个问答
    def _biz_q():
        if biz_score >= 7.5: return f"是的，{biz_conclusion}"
        elif biz_score >= 5.0: return f"有一定理解，{biz_conclusion}"
        else: return "较难理解，商业模式不清晰"

    def _moat_q():
        if moat_score >= 7.5: return f"护城河宽阔，{moat_conclusion}"
        elif moat_score >= 5.0: return f"护城河一般，{moat_conclusion}"
        else: return "护城河不明显"

    def _mgmt_q():
        if mgmt_score >= 7.5: return f"管理卓越，ROE{roe}%，{dim_dict.get('管理层',('',''))[1] if '管理层' in dim_dict else ''}"
        elif mgmt_score >= 5.0: return f"管理合格，但ROE仅{roe}%"
        else: return f"管理存疑，ROE{roe}%偏低"

    def _val_q():
        if val_score >= 7.5: return f"有安全边际，{val_conclusion}"
        elif val_score >= 5.0: return f"估值合理，{val_conclusion}"
        else: return f"估值偏高，{val_conclusion}"

    def _risk_q():
        if risk_score < 3.0:
            parts = []
            if rev_yoy and rev_yoy < -10: parts.append(f"营收下滑{rev_yoy:.1f}%")
            if net_yoy_val and net_yoy_val < -10: parts.append(f"净利暴跌{net_yoy_val:.1f}%")
            if dr and dr > 50: parts.append(f"负债率{dr}%偏高")
            risk_detail = "，".join(parts) if parts else "风险较高"
            return f"风险极高，{risk_detail}，需设止损{sl}"
        elif risk_score >= 5.0:
            return f"风险可控，止损{sl}设好即可"
        else:
            return f"需关注，败率较高，止损{sl}"

    answers = [
        ("① 这门生意我能理解吗？", _biz_q()),
        ("② 护城河深不深？", _moat_q()),
        ("③ 管理层值得信任吗？", _mgmt_q()),
        ("④ 价格有安全边际吗？", _val_q()),
        ("⑤ 错了会怎样？", _risk_q()),
    ]

    evidence = {
        "score_biz": biz_score, "score_moat": moat_score,
        "score_mgmt": mgmt_score, "score_val": val_score, "score_risk": risk_score,
        "pe": pe, "roe": roe, "rev_yoy": rev_yoy, "net_yoy": net_yoy_val,
        "answers": answers,
    }
    return result, evidence

# ── 芒格式逆向检验 ──
def munger_risk_check(rev_yoy, net_yoy, roe, dr, pe, industry_risks=None):
    risks = []
    if rev_yoy and rev_yoy < -15: risks.append(f"☠️ 营收同比{fmt(rev_yoy)}%，主业严重萎缩")
    elif rev_yoy and rev_yoy < 0: risks.append(f"⚠️ 营收同比{fmt(rev_yoy)}%，下滑趋势")
    if net_yoy and net_yoy < -30: risks.append(f"☠️ 净利同比{fmt(net_yoy)}%，盈利崩盘")
    elif net_yoy and net_yoy < 0: risks.append(f"⚠️ 净利同比{fmt(net_yoy)}%，盈利下滑")
    if roe and roe < 5: risks.append(f"⚠️ ROE仅{fmt(roe)}%，资本回报极低")
    if dr and dr > 70: risks.append(f"☠️ 负债率{fmt(dr)}%，高杠杆风险")
    if pe and pe < 0: risks.append(f"☠️ PE为负，公司亏损")
    if industry_risks:
        for r in industry_risks:
            risks.append(f"🏭 {r}")
    if not risks:
        risks.append("✅ 无明显逆向风险")
    return risks

# ── 主分析函数 ──
async def analyze_holding(h, result):
    """分析一只持仓，返回结构化数据"""
    code = h["code"]
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
    risks = munger_risk_check(rev_yoy, net_yoy, roe, dr, pe, industry_risks_map.get(code))
    
    # 镜子测试
    mirror_result, mirror_reasons = mirror_test(
        code, masters.get("dims", []),
        pe, roe, rev_yoy, net_yoy, chan, ma_detail,
        gm=gm, np_margin=np_margin, net_yoy_val=net_yoy, dr=dr, dy=dy,
        sl=sltp.get("stop_loss", 0), tp=sltp.get("take_profit", 0)
    )
    
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

async def generate_report():
    # 读取持仓：优先 --stdin，回退本地文件
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
        chain = INDUSTRY_CHAINS.get(code)
        print("### 📊 基本面分析")
        print()
        # 产业链 Mermaid
        if chain:
            print(f"**{chain['name']}**")
            print()
            print("```mermaid")
            print(chain["mermaid"])
            print("```")
            print()
            print(f"> **卡脖子**: {chain['bottleneck']}")
            print(f"> **竞品对标**: {chain['vs_leader']}")
            print()
        # ── 六维评分表（2026-07-22 六维框架） ──
        print("| 维度 | 评分 | 信心度 | 大师视角 | 其他大师质疑 | 大师答疑 |")
        print("|:----|:---:|:------:|:--------|:----------:|:--------|")
        for dim in dims:
            label = dim["label"]
            score = dim["score"]
            confidence = dim["confidence"]
            master_pv = dim["master_perspective"]
            other_ch = dim["other_masters_challenge"]
            master_answer = dim.get("master_answer", "")
            print(f"| {label} | {score}/10 | {confidence} | {master_pv} | {other_ch} | {master_answer} |")

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
        
        # 芒格式逆向检验
        print("### ⚠️ 芒格式逆向检验")
        print()
        for r in d["risks"]:
            print(f"  {r}")
        print()
        
        # 缠论 & 技术面
        print("### 🔧 技术面分析")
        print()
        print(f"**周线定势**: {d['weekly']}")
        print()
        print(f"**日线走势**: {d['chan']['summary']}")
        for line in d["chan"]["detail"]:
            print(f"  {line}")
        print()
        
        # 技术面汇总表（类似 recommend.py 格式）
        ma = d['ma_detail']
        macd = d['macd_detail']
        print("**技术指标**:")
        print()
        print("| 维度 | 信号 | 数值 |")
        print("|:----|:----|:----:|")
        # 从 ma_detail 解析 MA 排列
        ma_line = ma.split("|") if "|" in str(ma) else [str(ma)]
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
        
        # 镜子测试（判分结果 + 5个问答）
        ev = d.get("mirror_reasons", {})
        print("### 📋 镜子测试")
        print()
        print(f"> {d['mirror']}")
        print(f"| # | 问题 | 回答 |")
        print(f"|:-:|:----|:----|")
        for q, a in ev.get("answers", []):
            num = q.split(" ")[0] if " " in q else "?"
            question_text = q[len(num)+1:] if " " in q else q
            print(f"| {num} | {question_text} | {a} |")
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
    
    # 组合优化建议
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

if __name__ == "__main__":
    asyncio.run(generate_report())
