"""
quantrisk — 共享推荐引擎（Recommender）

跨市场共享的过滤/评分/格式化逻辑，A股/港股/美股共用。
各市场的差异化数据源（板块扫描、候选池、资金流向）由市场适配器提供。

设计原则:
  - 过滤/评分规则统一
  - 格式输出由 formatter.py 控制
  - 市场差异通过 adapters 隔离
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple


# ═══════════════════════════════════════════════════════════════
# 四大师独立裁决 + 追问引擎（2026-07-22 新增）
# ═══════════════════════════════════════════════════════════════

def _verdict_from_score(score: float) -> str:
    """将百分位评分(1-5)映射为独立裁决"""
    if score >= 4.0: return "✅ 通过"
    elif score >= 3.0: return "⚠️ 有条件通过"
    elif score >= 2.0: return "❓ 灰色地带"
    else: return "❌ 不通过"


def _dyp_question(p: Dict[str, Any]) -> str:
    """🏢 段永平追问：这是对的生意吗？"""
    ind = p.get("ind", {}) or {}
    q = p.get("q", {}) or {}
    def _v(k): return ind.get(k) or ind.get(k.replace("_yoy", ""), 0)
    roe = _v("ROE") or _v("JQROE") or 0
    gr = _v("GROSS_PROFIT_RATIO") or 0
    pm = q.get("profit_margin", 0) or 0
    parts = []
    if gr > 60:
        parts.append(f"毛利率{gr:.1f}%远超60%，有极强的定价权，这是好生意的标志")
    elif gr > 40:
        parts.append(f"毛利率{gr:.1f}%高于40%，有一定定价权")
    elif gr > 20:
        parts.append(f"毛利率{gr:.1f}%在20%以上，行业平均水平")
    elif gr > 0:
        parts.append(f"毛利率仅{gr:.1f}%，定价权存疑，必须确认这是否是模式性问题")
    if roe > 30:
        parts.append(f"ROE{roe:.1f}%超过30%，资本回报效率极高，这是对的生意")
    elif roe > 15:
        parts.append(f"ROE{roe:.1f}%在15%以上，资本回报效率良好")
    elif roe < 0:
        parts.append(f"ROE为负，资本在毁灭价值")
    if pm > 30:
        parts.append(f"净利率{pm:.1f}%超过30%，盈利质量优秀")
    elif pm > 20:
        parts.append(f"净利率{pm:.1f}%超过20%，盈利质量良好")
    elif pm < 0:
        parts.append(f"净利率为负，公司不赚钱")
    return "，".join(parts) if parts else "数据不足，难以判断生意质量"


def _buffett_question(p: Dict[str, Any], sector: str, pe_limit: int) -> str:
    """🛡️ 巴菲特追问：够便宜吗？有安全边际吗？"""
    q = p.get("q", {}) or {}
    ind = p.get("ind", {}) or {}
    pe = p.get("pe", 0)
    pb = q.get("pb", 0)
    dy = q.get("dividend_yield", 0) or 0
    def _v(k): return ind.get(k) or ind.get(k.replace("_yoy", ""), 0)
    roe = _v("ROE") or _v("JQROE") or 0
    parts = []
    if pe > 0:
        pe_ratio = pe / max(pe_limit, 1)
        if pe_ratio <= 0.5:
            parts.append(f"PE/行业阈值={pe:.0f}/{pe_limit}={pe_ratio:.2f}，估值处于行业低位，有足够安全边际")
        elif pe_ratio <= 1.0:
            parts.append(f"PE/行业阈值={pe:.0f}/{pe_limit}={pe_ratio:.2f}，估值合理，安全边际一般")
        else:
            parts.append(f"PE/行业阈值={pe:.0f}/{pe_limit}={pe_ratio:.2f}，估值高于行业均值，安全边际不足")
    if pb > 0 and pb < 1:
        parts.append(f"PB<1，资产价格低于重置成本，安全边际充足")
    if dy > 3:
        parts.append(f"股息率{dy:.1f}%，股东回报可观，符合巴菲特对稳定现金流的偏好")
    if roe > 20:
        parts.append(f"ROE{roe:.1f}%超过20%，护城河深厚")
    return "，".join(parts) if parts else "数据不足，难以判断估值安全边际"


def _munger_question(p: Dict[str, Any]) -> str:
    """⚠️ 芒格追问：怎么会死？有什么风险？"""
    ind = p.get("ind", {}) or {}
    rev = p.get("rev", 0)
    ny = p.get("ny", 0)
    def _v(k): return ind.get(k) or ind.get(k.replace("_yoy", ""), 0)
    dr = _v("DEBT_ASSET_RATIO") or 0
    parts = []
    if dr > 70:
        parts.append(f"负债率{dr:.1f}%超过70%，财务风险较高——芒格会问：这家公司怎么死？")
    elif dr > 50:
        parts.append(f"负债率{dr:.1f}%超过50%，杠杆偏高，需关注偿债能力")
    elif dr < 30:
        parts.append(f"负债率{dr:.1f}%低于30%，财务结构稳健")
    if rev < -30:
        parts.append(f"营收下滑{rev:.1f}%，这是最危险的信号之一——芒格会问：公司在被谁替代？")
    elif rev < -10:
        parts.append(f"营收下滑{rev:.1f}%，需警惕趋势是否持续")
    elif rev > 30 and dr < 30:
        parts.append(f"高增长({rev:.1f}%)+低负债({dr:.1f}%)，风险可控，但芒格会问：增长可持续吗？")
    if ny < -50:
        parts.append(f"净利暴跌{ny:.1f}%，盈利能力严重恶化")
    if dr <= 30 and rev > 0 and ny > 0:
        parts.append("营收/净利正增长+低负债，逆向风险较低")
    return "，".join(parts) if parts else "数据不足，难以评估风险"


def _lilu_question(p: Dict[str, Any]) -> str:
    """🔭 李录追问：10年后还在吗？"""
    ind = p.get("ind", {}) or {}
    q = p.get("q", {}) or {}
    rev = p.get("rev", 0)
    def _v(k): return ind.get(k) or ind.get(k.replace("_yoy", ""), 0)
    roe = _v("ROE") or _v("JQROE") or 0
    dr = _v("DEBT_ASSET_RATIO") or 0
    pm = q.get("profit_margin", 0) or 0
    dy = q.get("dividend_yield", 0) or 0
    parts = []
    if rev > 20 and dr < 30:
        parts.append(f"高增长(营收{rev:.1f}%)+低负债(负债率{dr:.1f}%)，10年后大概率还在——符合李录长期确定性标准")
    elif rev > 0 and dr < 30:
        parts.append(f"营收稳健+低负债，长期确定性较好")
    if roe > 15:
        parts.append(f"ROE{roe:.1f}%持续高水平，说明有持续竞争力")
    elif roe < 0:
        parts.append("ROE为负，长期能否存活存疑")
    if pm > 15:
        parts.append(f"净利率{pm:.1f}%，赚钱能力强，可持续")
    if dy > 3:
        parts.append(f"持续分红(股息率{dy:.1f}%)，说明公司有持续赚钱能力")
    if rev < 0:
        parts.append("营收下滑，10年后的确定性存疑")
    return "，".join(parts) if parts else "数据不足，难以判断长期确定性"


def _munger_reverse_test(p: Dict[str, Any]) -> str:
    """⚠️ 芒格式逆向检验：这家公司可能怎么死？

    基于指标列出失败路径，不是预测，而是反向思考。
    """
    ind = p.get("ind", {}) or {}
    rev = p.get("rev", 0)
    ny = p.get("ny", 0)
    def _v(k): return ind.get(k) or ind.get(k.replace("_yoy", ""), 0)
    dr = _v("DEBT_ASSET_RATIO") or 0
    roe = _v("ROE") or _v("JQROE") or 0
    gr = _v("GROSS_PROFIT_RATIO") or 0
    q = p.get("q", {}) or {}
    pe = p.get("pe", 0)

    risks = []
    if dr > 70:
        risks.append(f"🔥 高负债(负债率{dr:.1f}%)：如果利率上升或收入下滑，可能触发债务违约")
    elif dr > 50:
        risks.append(f"⚠️ 负债率{dr:.1f}%偏高，杠杆成本上升时会侵蚀利润")

    if rev < -30:
        risks.append(f"🔥 营收严重萎缩(营收{rev:.1f}%)：市场份额被蚕食，可能是被替代的早期信号")
    elif rev < -10:
        risks.append(f"⚠️ 营收下滑(营收{rev:.1f}%)：需警惕趋势是否持续，公司在被谁替代？")
    elif rev < 0:
        risks.append(f"⚠️ 营收微降(营收{rev:.1f}%)：虽然幅度不大，但负增长本身就是警讯")

    if ny < -100:
        risks.append(f"🔥 盈利能力崩塌(净利{ny:.1f}%)：净利暴跌，可能是非经常性损失或结构性恶化")
    elif ny < -50:
        risks.append(f"⚠️ 净利大幅下滑(净利{ny:.1f}%)：需确认是周期性还是结构性问题")

    if roe < 0:
        risks.append(f"🔥 持续亏损(ROE{roe:.1f}%)：公司正在毁灭股东价值")
    elif roe < 5:
        risks.append(f"⚠️ ROE仅{roe:.1f}%，资本回报率低，竞争优势存疑")

    if 0 < gr < 10 and rev < 0:
        risks.append(f"⚠️ 毛利率低(毛利率{gr:.1f}%)且营收下滑：无定价权+市场萎缩，双重打击")

    if pe < 0:
        risks.append(f"🔥 PE为负，公司处于亏损状态，无法用市盈率估值")

    if not risks:
        return "✅ 财务结构健康，暂时无明显死亡路径。芒格会问：如果行业周期向下，这家公司能撑住吗？——从现有数据看，可以。"

    risks.append("芒格会问：以上风险中，哪个最可能成真？如果成真，损失有多大？")
    return "\n".join(risks)


# ═══════════════════════════════════════════════════════════════
# 共享过滤/评分逻辑
# ═══════════════════════════════════════════════════════════════

def meso_filter(
    st: Dict[str, Any],
    industry_thresholds: Dict[str, int],
    code2sector: Dict[str, str],
    field_map: Optional[Dict[str, str]] = None,
    **kwargs: Any,
) -> Tuple[List[Dict], List[Tuple[str, str, str]]]:
    """中观硬约束过滤 — 市值/股价硬门槛；PE按行业阈值标记但不淘汰。

    Args:
        st: {code: {field_map["quote"]: {...}, field_map["indicator"]: {...}}}
        industry_thresholds: {sector_name: pe_threshold}
        code2sector: {code: sector_name}
        field_map: 数据字段名映射（HK用{"q":"quote","ind":"indicator"}，CN/US默认{"quote":"quote","indicator":"indicator"}）

    Returns:
        passed: [{code, name, sector, price, mcap, pe, ny, rev, pw, q, ind}]
        eliminated: [(code, name, reason)]
    """
    passed, elim = [], []
    default_pe_limit = industry_thresholds.get("其他", 60)
    q_key = (field_map or {}).get("q", "quote")
    ind_key = (field_map or {}).get("ind", "indicator")

    for code, info in st.items():
        q = info.get(q_key, {}) or {}
        ind = info.get(ind_key, {}) or {}
        sector = code2sector.get(code, "其他")
        pe_limit = industry_thresholds.get(sector, default_pe_limit)

        price = q.get("price", 0)
        mcap = q.get("market_cap_100m") or q.get("market_cap", 0)
        pe = q.get("pe") or q.get("pe_ttm", 0)
        ny = (ind.get("HOLDER_PROFIT_YOY") or 0) if ind else 0
        rev = (ind.get("OPERATE_INCOME_YOY") or 0) if ind else 0

        rs, pw = [], []

        # 硬约束：市值和股价
        if mcap > 0 and mcap < 50:
            rs.append(f"市值{mcap:.0f}亿<50亿")
        if price > 0 and price < 1:
            rs.append(f"股价{price:.2f}<1元")

        # PE 标记但不淘汰
        if pe and pe > pe_limit:
            pw.append(f"⚠️PE{pe:.0f}>行业阈值{pe_limit}（{sector}）")
        if ny < -50:
            pw.append(f"⚠️净利同比{ny:.2f}%（恶化）")

        pw_str = "; ".join(pw) if pw else ""

        if rs:
            elim.append((code, q.get("name", "?"), "; ".join(rs)))
        else:
            passed.append({
                "c": code, "n": q.get("name", "?"), "s": sector,
                "p": price, "mc": mcap, "pe": pe, "ny": ny, "rev": rev,
                "pw": pw_str, "q": q, "ind": ind,
            })

    return passed, elim


# ═══════════════════════════════════════════════════════════════
# 基本面一票否决（投资理念铁律：基本面为主，不合格者直接淘汰）
# ═══════════════════════════════════════════════════════════════

def fundamental_veto(
    passed: List[Dict[str, Any]],
    min_rev_yoy: float = -30.0,
    min_ny_yoy: float = -30.0,
    max_pe_neg: float = -10.0,
) -> Tuple[List[Dict[str, Any]], List[Tuple[str, str, str]]]:
    """基本面一票否决（扩展版）— 严重基本面恶化的标的直接淘汰。

    贯彻"基本面为主"理念：技术面和热点再强，基本面崩塌的股票也不进评分池。

    否决条件（8条，整合自 ai-berkshire 快速否决清单）：
      1. 营收同比下滑 > 30% → 业务萎缩
      2. 净利同比下滑 > 30% → 盈利能力崩塌
      3. PE 严重负值（< -10）→ 巨亏无法估值
      4. 负债率 > 90% → 资不抵债风险
      5. ROE < 0（亏损）→ 持续无法创造股东回报
      6. 毛利率 < 10% 且营收增速 < 0 → 无定价权+萎缩
      7. PB < 0（净资产为负）→ 资不抵债
      8. 营收 < 净利（靠非经常性损益）→ 主业不赚钱

    Args:
        passed: meso_filter 通过后的标的列表
        min_rev_yoy: 营收同比下滑阈值（%），低于此值淘汰（默认 -30%）
        min_ny_yoy: 净利同比下滑阈值（%），低于此值淘汰（默认 -30%）
        max_pe_neg: PE 负值阈值，低于此值淘汰（默认 -10，即严重亏损）

    Returns:
        passed: 通过否决后的标的列表
        vetoed: [(code, name, reason)] 被否决的标的
    """
    passed_out, vetoed = [], []

    for p in passed:
        c = p["c"]
        n = p.get("n", "?")
        ny = p.get("ny", 0)
        rev = p.get("rev", 0)
        pe = p.get("pe", 0)
        q = p.get("q", {}) or {}
        ind = p.get("ind", {}) or {}

        def _v(k):
            return ind.get(k) or ind.get(k.replace("_yoy", ""), 0)

        roe = _v("ROE") or _v("JQROE") or 0
        gr = _v("GROSS_PROFIT_RATIO") or 0
        dr = _v("DEBT_ASSET_RATIO") or 0
        pb = q.get("pb", 0) or 0
        pm = q.get("profit_margin", 0) or 0

        reasons = []

        # ① 营收同比严重下滑
        if rev < min_rev_yoy:
            reasons.append(f"营收同比{rev:.1f}%（<-{abs(min_rev_yoy)}%）")

        # ② 净利同比严重下滑
        if ny < min_ny_yoy:
            reasons.append(f"净利同比{ny:.1f}%（<-{abs(min_ny_yoy)}%）")

        # ③ PE 严重负值
        if pe < max_pe_neg:
            reasons.append(f"PE{pe:.1f}（严重亏损）")

        # ④ 负债率 > 90%
        if dr > 90:
            reasons.append(f"负债率{dr:.1f}%（>90%资不抵债风险）")

        # ⑤ ROE < 0（亏损）
        if roe < 0:
            reasons.append(f"ROE{roe:.1f}%（亏损，无法创造股东回报）")

        # ⑥ 毛利率 < 10% 且 营收增速 < 0
        if rev < 0 and 0 < gr < 10:
            reasons.append(f"毛利率{gr:.1f}%（<10%）且营收下滑{rev:.1f}%（无定价权+萎缩）")

        # ⑦ PB < 0（净资产为负）
        if pb < 0:
            reasons.append(f"PB{pb:.2f}（净资产为负）")

        # ⑧ 营收 < 净利（靠非经常性损益）
        if rev < 0 and ny > 0 and abs(ny) > abs(rev):
            reasons.append(f"营收{rev:.1f}% < 净利{ny:.1f}%（可能靠非经常性损益）")

        if reasons:
            vetoed.append((c, n, "; ".join(reasons)))
        else:
            passed_out.append(p)

    return passed_out, vetoed


def quality_screen(scored: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """质量筛选：基于5条硬指标对已评分标的做质量标记。

    借鉴 ai-berkshire quality-screen.md 的7条去劣逻辑，
    适配 quant-risk 的可用数据（只有最新一期财务指标，无多年历史）。

    不直接淘汰（让评分说话），但在标的的 advice 降档标记。

    5条指标（可用数据范围内）：
      1. ROE < 8% → 资本效率低下
      2. 毛利率 < 15% → 无定价权
      3. 净利率 < 5% → 抗风险能力弱
      4. 负债率 > 70% → 过高负债风险
      5. 营收增速 < -10% 且 净利增速 < -10% → 双降风险
    """
    for r in scored:
        ind = r.get("ind", {}) or {}
        q = r.get("q", {}) or {}

        def _v(k):
            return ind.get(k) or ind.get(k.replace("_yoy", ""), 0)

        roe = _v("ROE") or _v("JQROE") or 0
        gr = _v("GROSS_PROFIT_RATIO") or 0
        pm = q.get("profit_margin", 0) or 0
        dr = _v("DEBT_ASSET_RATIO") or 0
        rev = r.get("rev", 0)
        ny = r.get("ny", 0)

        issues = []
        if 0 < roe < 8:
            issues.append(f"ROE{roe:.1f}%<8%（资本效率低下）")
        if 0 < gr < 15:
            issues.append(f"毛利率{gr:.1f}%<15%（无定价权）")
        if 0 < pm < 5:
            issues.append(f"净利率{pm:.1f}%<5%（抗风险能力弱）")
        if dr > 70:
            issues.append(f"负债率{dr:.1f}%>70%（过高负债风险）")
        if rev < -10 and ny < -10:
            issues.append(f"营收{rev:.1f}%+净利{ny:.1f}%双降（趋势恶化）")

        r["quality_issues"] = issues

        # 有质量问题的，建议降一档
        if issues:
            t = r.get("total", 0)
            current_advice = r.get("advice", "")
            if current_advice == "强烈关注":
                r["advice"] = "可关注"
            elif current_advice == "可关注":
                r["advice"] = "观察"

    return scored


# ── 辅助 ──────────────────────────────────────────────────────

def _clamp(v: float, lo: float = 1.0, hi: float = 5.0) -> float:
    """限制到 [lo, hi] 范围并保留 1 位小数。"""
    return round(max(lo, min(hi, v)), 1)


def _percentile(values: List[float], v: float) -> float:
    """返回 v 在 values 中的百分位排名（0~1）。"""
    if not values:
        return 0.5
    ranked = sorted(values)
    n = len(ranked)
    # 比 v 小的比例
    smaller = sum(1 for x in ranked if x < v)
    return smaller / n


# ═══════════════════════════════════════════════════════════════
# 四大师视角评分（2026-07-22 新增，借鉴 ai-berkshire 框架）
# 段永平(商业模式)30% + 巴菲特(护城河/估值)30% + 芒格(逆向风险)20% + 李录(长期确定性)20%
# ═══════════════════════════════════════════════════════════════

def info_richness_rating(p: Dict[str, Any]) -> Tuple[str, str]:
    """信息丰富度评级（A/B/C 三级）。

    基于 9 个基本面字段的完整性：
      - A级：7-9个字段有值
      - B级：4-6个字段有值
      - C级：<4个字段有值

    Returns:
        (rating, detail)
    """
    ind = p.get("ind", {}) or {}
    q = p.get("q", {}) or {}
    rev = p.get("rev", 0)
    ny = p.get("ny", 0)

    def _v(k):
        return ind.get(k) or ind.get(k.replace("_yoy", ""), 0)

    fields = {
        "营收增速": rev,
        "净利同比": ny,
        "ROE": _v("ROE") or _v("JQROE"),
        "毛利率": _v("GROSS_PROFIT_RATIO"),
        "负债率": _v("DEBT_ASSET_RATIO"),
        "PE": p.get("pe", 0),
        "PB": q.get("pb", 0),
        "股息率": q.get("dividend_yield", 0),
        "净利率": q.get("profit_margin", 0),
    }
    has_value = sum(1 for v in fields.values() if v and v != "?" and v != 0)
    missing = [k for k, v in fields.items() if not v or v == "?" or v == 0]

    if has_value >= 7:
        rating = "A级"
        detail = "数据充足"
    elif has_value >= 4:
        rating = "B级"
        detail = f"部分数据缺失（缺失{len(missing)}个字段：{'/'.join(missing[:3])}）"
    else:
        rating = "C级"
        detail = f"数据严重不足（仅{has_value}个字段有值）"

    return rating, detail


# ═══════════════════════════════════════════════════════════════
# 六维评分（2026-07-22 重构：替代原有的四大师评分）
# ═══════════════════════════════════════════════════════════════
# 基本面总分 60 分 = 6 个维度 × 10 分满分
# 每个维度返回 (score, debug, conclusion, confidence)
#    score: 1-10
#    debug: 计算明细文本
#    conclusion: 自动生成的定性结论描述
#    confidence: ★★★★★ 风格

def _dim_conclusion(score: float, high_label: str, mid_label: str, low_label: str) -> str:
    """根据分数生成定性标签"""
    if score >= 9.0: return "极佳"
    elif score >= 7.5: return "优秀"
    elif score >= 6.0: return "良好"
    elif score >= 4.5: return "一般"
    elif score >= 3.0: return "较差"
    else: return "极差"

def _dim_confidence(score: float) -> str:
    """根据分数生成信心度（★）"""
    if score >= 9.0: return "★★★★★"
    elif score >= 7.5: return "★★★★☆"
    elif score >= 6.0: return "★★★☆☆"
    elif score >= 4.5: return "★★☆☆☆"
    else: return "★☆☆☆☆"

def _clamp10(v: float) -> float:
    """限幅到 1.0-10.0"""
    return max(1.0, min(10.0, round(v, 1)))


def dim_business_quality(p: Dict[str, Any]) -> Tuple[float, str, str, str]:
    """维度1：生意质量（段永平）— 满分10分

    核心指标：毛利率、净利率、ROE
    判断"这是对的生意吗？"
    """
    ind = p.get("ind", {}) or {}
    q = p.get("q", {}) or {}

    def _v(k): return ind.get(k) or ind.get(k.replace("_yoy", ""), 0)
    roe = _v("ROE") or _v("JQROE") or 0
    gr = _v("GROSS_PROFIT_RATIO") or 0
    pm = q.get("profit_margin", 0) or 0

    s = 4.0
    parts = [f"基础{s:.1f}"]

    # ── 毛利率（定价权） ──
    if gr > 80: s += 2.0; parts.append(f"毛利率{gr:.1f}%(>80%→+2.0)")
    elif gr > 60: s += 1.5; parts.append(f"毛利率{gr:.1f}%(>60%→+1.5)")
    elif gr > 40: s += 1.0; parts.append(f"毛利率{gr:.1f}%(>40%→+1.0)")
    elif gr > 20: s += 0.5; parts.append(f"毛利率{gr:.1f}%(>20%→+0.5)")
    elif 0 < gr < 10: s -= 1.0; parts.append(f"毛利率{gr:.1f}%(<10%→-1.0)")
    else: parts.append("毛利率?(无数据→0)")

    # ── 净利率（盈利质量） ──
    if pm > 30: s += 2.0; parts.append(f"净利率{pm:.1f}%(>30%→+2.0)")
    elif pm > 20: s += 1.5; parts.append(f"净利率{pm:.1f}%(>20%→+1.5)")
    elif pm > 10: s += 0.5; parts.append(f"净利率{pm:.1f}%(>10%→+0.5)")
    elif pm < 0: s -= 1.0; parts.append(f"净利率{pm:.1f}%(<0→-1.0)")
    else: parts.append(f"净利率?(无数据→0)")

    # ── ROE（资本回报效率） ──
    if roe > 30: s += 2.0; parts.append(f"ROE{roe:.1f}%(>30%→+2.0)")
    elif roe > 20: s += 1.0; parts.append(f"ROE{roe:.1f}%(>20%→+1.0)")
    elif roe > 15: s += 0.5; parts.append(f"ROE{roe:.1f}%(>15%→+0.5)")
    elif roe < 0: s -= 1.5; parts.append(f"ROE{roe:.1f}%(<0→-1.5)")
    else: parts.append(f"ROE?(无数据→0)")

    score = _clamp10(s)
    debug = "+".join(parts)
    tag = _dim_conclusion(score, "极佳", "优秀", "较差")
    conf = _dim_confidence(score)
    # 拼接结论文本 — 使用 _dyp_question 的详细追问回答
    conclusion = _dyp_question(p)
    return score, debug, conclusion, conf


def dim_moat(p: Dict[str, Any]) -> Tuple[float, str, str, str]:
    """维度2：护城河（巴菲特）— 满分10分

    核心指标：ROE、毛利率、股息率、负债率
    判断"护城河够宽吗？"
    """
    ind = p.get("ind", {}) or {}
    q = p.get("q", {}) or {}

    def _v(k): return ind.get(k) or ind.get(k.replace("_yoy", ""), 0)
    dr = _v("DEBT_ASSET_RATIO") or 0
    roe = _v("ROE") or _v("JQROE") or 0
    gr = _v("GROSS_PROFIT_RATIO") or 0
    dy = q.get("dividend_yield", 0) or 0

    s = 4.0
    parts = [f"基础{s:.1f}"]

    # ── ROE（护城河核心标志） ──
    if roe > 30: s += 2.0; parts.append(f"ROE{roe:.1f}%(>30%→+2.0)")
    elif roe > 20: s += 1.5; parts.append(f"ROE{roe:.1f}%(>20%→+1.5)")
    elif roe > 15: s += 1.0; parts.append(f"ROE{roe:.1f}%(>15%→+1.0)")
    elif roe < 0: s -= 1.5; parts.append(f"ROE{roe:.1f}%(<0→-1.5)")
    else: parts.append(f"ROE?(无数据→0)")

    # ── 毛利率（定价权护城河） ──
    if gr > 60: s += 1.5; parts.append(f"毛利率{gr:.1f}%(>60%→+1.5)")
    elif gr > 40: s += 1.0; parts.append(f"毛利率{gr:.1f}%(>40%→+1.0)")
    elif gr > 20: s += 0.5; parts.append(f"毛利率{gr:.1f}%(>20%→+0.5)")
    else: parts.append(f"毛利率{gr:.1f}%(≤20%→0)")

    # ── 股息率（稳定现金流） ──
    if dy > 5: s += 1.0; parts.append(f"股息率{dy:.1f}%(>5%→+1.0)")
    elif dy > 3: s += 0.5; parts.append(f"股息率{dy:.1f}%(>3%→+0.5)")
    elif dy > 1: s += 0.3; parts.append(f"股息率{dy:.1f}%(>1%→+0.3)")

    # ── 负债率（财务稳健） ──
    if dr > 0:
        if dr < 30: s += 0.5; parts.append(f"负债率{dr:.1f}%(<30%→+0.5)")
        elif dr > 70: s -= 1.0; parts.append(f"负债率{dr:.1f}%(>70%→-1.0)")
        else: parts.append(f"负债率{dr:.1f}%(30-70%→0)")

    score = _clamp10(s)
    debug = "+".join(parts)
    tag = _dim_conclusion(score, "宽阔", "较宽", "狭窄")
    conf = _dim_confidence(score)
    # 护城河追问回答
    moat_parts = []
    if roe > 20:
        moat_parts.append(f"ROE{roe:.1f}%超过20%，护城河深厚")
    elif roe > 15:
        moat_parts.append(f"ROE{roe:.1f}%在15%以上，护城河一般")
    elif roe < 0:
        moat_parts.append(f"ROE为负，护城河在变窄")
    if gr > 60:
        moat_parts.append(f"毛利率{gr:.1f}%远超60%，有极强的定价权护城河")
    elif gr > 40:
        moat_parts.append(f"毛利率{gr:.1f}%高于40%，有一定定价权")
    elif gr < 10:
        moat_parts.append(f"毛利率仅{gr:.1f}%，定价权不足")
    if dy > 3:
        moat_parts.append(f"股息率{dy:.1f}%，股东回报稳定")
    if dr > 0 and dr < 30:
        moat_parts.append(f"负债率{dr:.1f}%低，财务稳健")
    elif dr > 70:
        moat_parts.append(f"负债率{dr:.1f}%过高，财务风险大")
    conclusion = "，".join(moat_parts) if moat_parts else tag
    return score, debug, conclusion, conf


def dim_management(p: Dict[str, Any]) -> Tuple[float, str, str, str]:
    """维度3：管理层（段永平+巴菲特）— 满分10分

    核心指标：ROE(资本配置)、净利率、营收增速、负债率(财务纪律)
    判断"管理层是否优秀？资本配置是否有效？"
    """
    ind = p.get("ind", {}) or {}
    q = p.get("q", {}) or {}
    rev = p.get("rev", 0)
    def _v(k): return ind.get(k) or ind.get(k.replace("_yoy", ""), 0)
    roe = _v("ROE") or _v("JQROE") or 0
    pm = q.get("profit_margin", 0) or 0
    dr = _v("DEBT_ASSET_RATIO") or 0

    s = 4.0
    parts = [f"基础{s:.1f}"]

    # ── ROE（资本配置效率） ──
    if roe > 30: s += 2.0; parts.append(f"ROE{roe:.1f}%(>30%→+2.0)")
    elif roe > 20: s += 1.5; parts.append(f"ROE{roe:.1f}%(>20%→+1.5)")
    elif roe > 15: s += 0.5; parts.append(f"ROE{roe:.1f}%(>15%→+0.5)")
    elif roe < 0: s -= 1.5; parts.append(f"ROE{roe:.1f}%(<0→-1.5)")

    # ── 净利率（管理效率） ──
    if pm > 20: s += 1.5; parts.append(f"净利率{pm:.1f}%(>20%→+1.5)")
    elif pm > 10: s += 0.5; parts.append(f"净利率{pm:.1f}%(>10%→+0.5)")
    elif pm < 0: s -= 1.0; parts.append(f"净利率{pm:.1f}%(<0→-1.0)")

    # ── 营收增速（执行能力） ──
    if rev > 20: s += 1.5; parts.append(f"营收{rev:.1f}%(>20%→+1.5)")
    elif rev > 10: s += 1.0; parts.append(f"营收{rev:.1f}%(>10%→+1.0)")
    elif rev > 0: s += 0.5; parts.append(f"营收{rev:.1f}%(>0%→+0.5)")
    elif rev < -20: s -= 1.5; parts.append(f"营收{rev:.1f}%(<-20%→-1.5)")
    elif rev < 0: s -= 0.5; parts.append(f"营收{rev:.1f}%(<0→-0.5)")

    # ── 负债率（财务纪律） ──
    if dr > 0 and dr < 30: s += 0.5; parts.append(f"负债率{dr:.1f}%(<30%→+0.5)")

    score = _clamp10(s)
    debug = "+".join(parts)
    tag = _dim_conclusion(score, "卓越", "优秀", "平庸")
    conf = _dim_confidence(score)
    # 管理层追问回答
    mgmt_parts = []
    if roe > 20:
        mgmt_parts.append(f"ROE{roe:.1f}%超过20%，资本配置效率高")
    elif roe < 0:
        mgmt_parts.append(f"ROE为负，资本在毁灭价值")
    if pm > 20:
        mgmt_parts.append(f"净利率{pm:.1f}%超过20%，管理效率优秀")
    elif pm < 0:
        mgmt_parts.append(f"净利率为负，盈利能力差")
    if rev > 10:
        mgmt_parts.append(f"营收增长{rev:+.1f}%，执行能力良好")
    elif rev < 0:
        mgmt_parts.append(f"营收下滑{rev:.1f}%，需关注增长动力")
    if dr > 0 and dr < 30:
        mgmt_parts.append(f"负债率{dr:.1f}%低，财务纪律良好")
    elif dr > 70:
        mgmt_parts.append(f"负债率{dr:.1f}%过高，财务纪律存疑")
    conclusion = "，".join(mgmt_parts) if mgmt_parts else tag
    return score, debug, conclusion, conf


def dim_risk(p: Dict[str, Any]) -> Tuple[float, str, str, str]:
    """维度4：最大风险（芒格）— 满分10分（逆向打分，风险越低分越高）

    核心指标：负债率、营收增速(负值重扣)、净利增速(负值重扣)、ROE
    判断"这家公司可能怎么死？"
    """
    ind = p.get("ind", {}) or {}
    rev = p.get("rev", 0)
    ny = p.get("ny", 0)
    def _v(k): return ind.get(k) or ind.get(k.replace("_yoy", ""), 0)
    dr = _v("DEBT_ASSET_RATIO") or 0
    roe = _v("ROE") or _v("JQROE") or 0

    s = 6.0  # 基础分偏高，只有在发现风险时才扣分
    parts = [f"基础{s:.1f}"]

    # ── 负债率过高扣分 ──
    if dr > 0:
        if dr > 70: s -= 3.0; parts.append(f"负债率{dr:.1f}%(>70%→-3.0)")
        elif dr > 50: s -= 1.5; parts.append(f"负债率{dr:.1f}%(>50%→-1.5)")
        elif dr > 30: s -= 0.5; parts.append(f"负债率{dr:.1f}%(>30%→-0.5)")
        else: parts.append(f"负债率{dr:.1f}%(≤30%→0)")
    else: parts.append("负债率?(无数据→0)")

    # ── 营收下滑扣分 ──
    if rev < -30: s -= 3.0; parts.append(f"营收{rev:.1f}%(<-30%→-3.0)")
    elif rev < -10: s -= 1.5; parts.append(f"营收{rev:.1f}%(<-10%→-1.5)")
    elif rev < 0: s -= 0.5; parts.append(f"营收{rev:.1f}%(<0%→-0.5)")
    elif rev > 10: s += 1.0; parts.append(f"营收{rev:.1f}%(>10%→+1.0)")
    else: parts.append(f"营收{rev:.1f}%(0-10%→0)")

    # ── 净利暴跌扣分 ──
    if ny < -30: s -= 3.0; parts.append(f"净利{ny:.1f}%(<-30%→-3.0)")
    elif ny < -10: s -= 1.5; parts.append(f"净利{ny:.1f}%(<-10%→-1.5)")
    elif ny < 0: s -= 0.5; parts.append(f"净利{ny:.1f}%(<0%→-0.5)")
    elif ny > 20: s += 1.0; parts.append(f"净利{ny:.1f}%(>20%→+1.0)")
    else: parts.append(f"净利{ny:.1f}%(0-20%→0)")

    # ── ROE为负（亏损风险） ──
    if roe < 0: s -= 1.5; parts.append(f"ROE{roe:.1f}%(<0→-1.5)")

    score = _clamp10(s)
    debug = "+".join(parts)
    tag = "低风险" if score >= 7.5 else "可控" if score >= 5.0 else "高风险"
    conf = _dim_confidence(score)
    # 使用 _munger_question 的详细追问回答
    conclusion = _munger_question(p)
    return score, debug, conclusion, conf


def dim_trend(p: Dict[str, Any]) -> Tuple[float, str, str, str]:
    """维度5：文明趋势（李录）— 满分10分

    核心指标：营收增速(行业景气)、净利率、负债率、ROE
    判断"顺应文明趋势吗？10年后还在吗？"
    """
    ind = p.get("ind", {}) or {}
    q = p.get("q", {}) or {}
    rev = p.get("rev", 0)
    def _v(k): return ind.get(k) or ind.get(k.replace("_yoy", ""), 0)
    roe = _v("ROE") or _v("JQROE") or 0
    pm = q.get("profit_margin", 0) or 0
    dr = _v("DEBT_ASSET_RATIO") or 0

    s = 4.0
    parts = [f"基础{s:.1f}"]

    # ── 营收增速（行业趋势代理） ──
    if rev > 30: s += 2.5; parts.append(f"营收{rev:.1f}%(>30%→+2.5)")
    elif rev > 20: s += 2.0; parts.append(f"营收{rev:.1f}%(>20%→+2.0)")
    elif rev > 10: s += 1.0; parts.append(f"营收{rev:.1f}%(>10%→+1.0)")
    elif rev > 0: s += 0.5; parts.append(f"营收{rev:.1f}%(>0%→+0.5)")
    elif rev < -20: s -= 2.0; parts.append(f"营收{rev:.1f}%(<-20%→-2.0)")
    elif rev < 0: s -= 0.5; parts.append(f"营收{rev:.1f}%(<0→-0.5)")

    # ── 净利率（赚钱能力） ──
    if pm > 30: s += 1.5; parts.append(f"净利率{pm:.1f}%(>30%→+1.5)")
    elif pm > 15: s += 1.0; parts.append(f"净利率{pm:.1f}%(>15%→+1.0)")
    elif pm < 0: s -= 1.0; parts.append(f"净利率{pm:.1f}%(<0→-1.0)")

    # ── 负债率（低负债才能适应变化） ──
    if dr > 0:
        if dr < 30: s += 1.0; parts.append(f"负债率{dr:.1f}%(<30%→+1.0)")
        elif dr > 70: s -= 1.0; parts.append(f"负债率{dr:.1f}%(>70%→-1.0)")

    # ── ROE（持续竞争力） ──
    if roe > 20: s += 1.0; parts.append(f"ROE{roe:.1f}%(>20%→+1.0)")
    elif roe > 15: s += 0.5; parts.append(f"ROE{roe:.1f}%(>15%→+0.5)")
    elif roe < 0: s -= 1.0; parts.append(f"ROE{roe:.1f}%(<0→-1.0)")

    score = _clamp10(s)
    debug = "+".join(parts)
    tag = _dim_conclusion(score, "顺应趋势", "良好", "逆势")
    conf = _dim_confidence(score)
    # 使用 _lilu_question 的详细追问回答
    conclusion = _lilu_question(p)
    return score, debug, conclusion, conf


def dim_valuation(p: Dict[str, Any], sector: str, pe_limit: int) -> Tuple[float, str, str, str]:
    """维度6：估值（巴菲特+段永平）— 满分10分

    核心指标：PE相对估值、股息率
    判断"价格合理吗？有安全边际吗？"
    """
    q = p.get("q", {}) or {}
    pe = p.get("pe", 0)
    dy = q.get("dividend_yield", 0) or 0
    pb = q.get("pb", 0)

    s = 4.0
    parts = [f"基础{s:.1f}"]

    # ── PE 相对估值（安全边际） ──
    if pe > 0:
        pe_ratio = pe / max(pe_limit, 1)
        if pe_ratio <= 0.3: s += 3.0; prt = f"PE/阈值 {pe:.0f}/{pe_limit}={pe_ratio:.2f}≤0.3→+3.0"
        elif pe_ratio <= 0.5: s += 2.5; prt = f"PE/阈值 {pe:.0f}/{pe_limit}={pe_ratio:.2f}≤0.5→+2.5"
        elif pe_ratio <= 0.8: s += 1.5; prt = f"PE/阈值 {pe:.0f}/{pe_limit}={pe_ratio:.2f}≤0.8→+1.5"
        elif pe_ratio <= 1.0: s += 0.5; prt = f"PE/阈值 {pe:.0f}/{pe_limit}={pe_ratio:.2f}≤1.0→+0.5"
        elif pe_ratio <= 1.5: s -= 0.5; prt = f"PE/阈值 {pe:.0f}/{pe_limit}={pe_ratio:.2f}>1.0→-0.5"
        elif pe_ratio <= 2.0: s -= 1.5; prt = f"PE/阈值 {pe:.0f}/{pe_limit}={pe_ratio:.2f}>1.5→-1.5"
        else: s -= 2.5; prt = f"PE/阈值 {pe:.0f}/{pe_limit}={pe_ratio:.2f}>2.0→-2.5"
        parts.append(prt)
    elif pe < 0: s -= 3.0; parts.append("PE<0→-3.0")
    else: parts.append("PE?(无数据→0)")

    # ── 股息率（股东回报） ──
    if dy > 5: s += 1.5; parts.append(f"股息率{dy:.1f}%(>5%→+1.5)")
    elif dy > 3: s += 1.0; parts.append(f"股息率{dy:.1f}%(>3%→+1.0)")
    elif dy > 1: s += 0.5; parts.append(f"股息率{dy:.1f}%(>1%→+0.5)")

    # ── PB 市净率（资产安全垫） ──
    if pb > 0 and pb < 1: s += 0.5; parts.append(f"PB{pb:.2f}(<1→+0.5)")

    score = _clamp10(s)
    debug = "+".join(parts)
    tag = "低估" if score >= 7.5 else "合理" if score >= 5.0 else "偏贵"
    conf = _dim_confidence(score)
    # 使用 _buffett_question 的详细追问回答
    conclusion = _buffett_question(p, sector, pe_limit)
    return score, debug, conclusion, conf


def fb_score(
    p: Dict[str, Any],
    sector: str,
    pe_limit: int,
) -> float:
    """基本面评分 — 返回 (score, debug_str)，debug_str 展示各维度计算明细。"""
    ind = p.get("ind", {}) or {}
    q = p.get("q", {}) or {}
    rev = p.get("rev", 0)
    ny = p.get("ny", 0)

    def _v(k):
        return ind.get(k) or ind.get(k.replace("_yoy", ""), 0)

    roe = _v("ROE") or _v("JQROE") or 0
    gr = _v("GROSS_PROFIT_RATIO") or 0
    dr = _v("DEBT_ASSET_RATIO") or 0
    pe = p.get("pe", 0)
    pb = q.get("pb", 0)
    dy = q.get("dividend_yield", 0)
    pm = q.get("profit_margin", 0)

    s = 2.0
    parts = [f"基础{s:.1f}"]

    # ── 营收增速 ──
    if rev > 50: c = 2.0; t = ">50%"
    elif rev > 30: c = 1.5; t = ">30%"
    elif rev > 20: c = 1.0; t = ">20%"
    elif rev > 10: c = 0.5; t = ">10%"
    elif rev > 0: c = 0.0; t = ">0%"
    elif rev < -50: c = -2.0; t = "<-50%"
    elif rev < -30: c = -1.0; t = "<-30%"
    elif rev < -10: c = -0.5; t = "<-10%"
    else: c = 0.0; t = "无数据"
    s += c
    parts.append(f"营收{rev:.1f}%({t}→{c:+.1f})")

    # ── ROE ──
    if roe > 30: s += 2.0; parts.append(f"ROE{roe:.1f}%(>30%→+2.0)")
    elif roe > 20: s += 1.5; parts.append(f"ROE{roe:.1f}%(>20%→+1.5)")
    elif roe > 15: s += 1.0; parts.append(f"ROE{roe:.1f}%(>15%→+1.0)")
    elif roe > 10: s += 0.5; parts.append(f"ROE{roe:.1f}%(>10%→+0.5)")
    elif roe > 5: s += 0.0; parts.append(f"ROE{roe:.1f}%(>5%→0)")
    elif roe < 0: s -= 1.5; parts.append(f"ROE{roe:.1f}%(<0→-1.5)")
    elif 0 < roe < 3: s -= 0.5; parts.append(f"ROE{roe:.1f}%(0~3%→-0.5)")
    else: parts.append(f"ROE?(无数据→0)")

    # ── 毛利率 ──
    if gr > 80: s += 1.5; parts.append(f"毛利率{gr:.1f}%(>80%→+1.5)")
    elif gr > 60: s += 1.0; parts.append(f"毛利率{gr:.1f}%(>60%→+1.0)")
    elif gr > 40: s += 0.5; parts.append(f"毛利率{gr:.1f}%(>40%→+0.5)")
    elif gr > 20: s += 0.0; parts.append(f"毛利率{gr:.1f}%(>20%→0)")
    elif 0 < gr < 10: s -= 0.5; parts.append(f"毛利率{gr:.1f}%(<10%→-0.5)")
    else: parts.append(f"毛利率?(无数据→0)")

    # ── 负债率 ──
    if dr > 0:
        if dr < 20: s += 1.0; parts.append(f"负债率{dr:.1f}%(<20%→+1.0)")
        elif dr < 30: s += 0.5; parts.append(f"负债率{dr:.1f}%(<30%→+0.5)")
        elif dr < 50: s += 0.0; parts.append(f"负债率{dr:.1f}%(<50%→0)")
        elif dr < 70: s -= 0.5; parts.append(f"负债率{dr:.1f}%(<70%→-0.5)")
        else: s -= 1.0; parts.append(f"负债率{dr:.1f}%(≥70%→-1.0)")
    else:
        parts.append("负债率?(无数据→0)")

    # ── PE 相对估值 ──
    if pe > 0:
        pe_ratio = pe / max(pe_limit, 1)
        if pe_ratio <= 0.3: s += 1.0; prt = f"PE/阈值 {pe:.0f}/{pe_limit}={pe_ratio:.2f}≤0.3→+1.0"
        elif pe_ratio <= 0.5: s += 0.5; prt = f"PE/阈值 {pe:.0f}/{pe_limit}={pe_ratio:.2f}≤0.5→+0.5"
        elif pe_ratio <= 0.8: s += 0.0; prt = f"PE/阈值 {pe:.0f}/{pe_limit}={pe_ratio:.2f}≤0.8→0"
        elif pe_ratio <= 1.0: s -= 0.0; prt = f"PE/阈值 {pe:.0f}/{pe_limit}={pe_ratio:.2f}≤1.0→0"
        elif pe_ratio <= 1.5: s -= 0.5; prt = f"PE/阈值 {pe:.0f}/{pe_limit}={pe_ratio:.2f}>1.0→-0.5"
        elif pe_ratio <= 2.0: s -= 1.0; prt = f"PE/阈值 {pe:.0f}/{pe_limit}={pe_ratio:.2f}>1.5→-1.0"
        else: s -= 1.5; prt = f"PE/阈值 {pe:.0f}/{pe_limit}={pe_ratio:.2f}>2.0→-1.5"
        parts.append(prt)
    elif pe < 0:
        s -= 2.0; parts.append("PE<0→-2.0")
    else:
        parts.append("PE?(无数据→0)")

    # ── 净利同比 ──
    if ny > 100: s += 1.0; parts.append(f"净利{ny:.1f}%(>100%→+1.0)")
    elif ny > 50: s += 0.5; parts.append(f"净利{ny:.1f}%(>50%→+0.5)")
    elif ny > 0: s += 0.0; parts.append(f"净利{ny:.1f}%(>0%→0)")
    elif ny < -100: s -= 2.0; parts.append(f"净利{ny:.1f}%(<-100%→-2.0)")
    elif ny < -50: s -= 1.0; parts.append(f"净利{ny:.1f}%(<-50%→-1.0)")
    else: parts.append(f"净利{ny:.1f}%(0~-50%→0)")

    # ── PB 市净率 ──
    if pb > 0:
        if pb < 1: s += 1.0; parts.append(f"PB{pb:.2f}(<1→+1.0)")
        elif pb < 2: s += 0.5; parts.append(f"PB{pb:.2f}(<2→+0.5)")
        elif pb < 3: s += 0.0; parts.append(f"PB{pb:.2f}(<3→0)")
        elif pb < 5: s -= 0.0; parts.append(f"PB{pb:.2f}(<5→0)")
        elif pb < 10: s -= 0.5; parts.append(f"PB{pb:.2f}(<10→-0.5)")
        else: s -= 1.0; parts.append(f"PB{pb:.2f}(≥10→-1.0)")
    else:
        parts.append("PB?(无数据→0)")

    # ── 股息率 ──
    if dy > 0:
        if dy > 5: s += 1.0; parts.append(f"股息率{dy:.1f}%(>5%→+1.0)")
        elif dy > 3: s += 0.5; parts.append(f"股息率{dy:.1f}%(>3%→+0.5)")
        elif dy > 1: s += 0.0; parts.append(f"股息率{dy:.1f}%(>1%→0)")
        else: parts.append(f"股息率{dy:.1f}%(>0%→0)")
    else:
        s -= 0.5; parts.append("股息率0%(=0→-0.5)")

    # ── 净利率 ──
    if pm > 0:
        if pm > 30: s += 1.0; parts.append(f"净利率{pm:.1f}%(>30%→+1.0)")
        elif pm > 15: s += 0.5; parts.append(f"净利率{pm:.1f}%(>15%→+0.5)")
        elif pm > 5: s += 0.0; parts.append(f"净利率{pm:.1f}%(>5%→0)")
        else: parts.append(f"净利率{pm:.1f}%(>0%→0)")
    elif pm < -10: s -= 1.0; parts.append(f"净利率{pm:.1f}%(<-10%→-1.0)")
    elif pm < 0: s -= 0.5; parts.append(f"净利率{pm:.1f}%(<0→-0.5)")
    else: parts.append("净利率?(无数据→0)")

    debug = "+".join(parts)
    return s, debug  # 返回 (未clamp原始分, debug明细)


def hot_score(
    p: Dict[str, Any],
    kl: List[Dict],
    sector_ranking: Optional[List[Tuple[str, Any]]] = None,
    market: str = "hk",
) -> int:
    """热点评分 — 基于近5日成交额变化+股价收盘价变化（替代资金流向）。

    港股资金流向数据长期缺失，改用K线数据计算：
      ① 板块整体表现（板块平均5日涨跌幅排名）
      ② 近5日成交额变化（后5日/前5日成交额比）
      ③ 近5日收盘价变化
      ④ 量价共振（涨且量放大加分，跌且量放大减分）
      ⑤ 板块内相对强弱（个股vs板块平均）

    Args:
        p: 股票信息
        kl: 日K线数据
        sector_ranking: [(sector_name, {"avg_5d_pct": ..., "stock_count": ..., "rank": ...})]
        market: 市场标识
    """
    s, sec, c = 2.0, p.get("s", "其他"), p.get("c", "")

    # ① 板块整体表现 — 用板块平均5日涨跌幅排名代替资金流向排名
    if sector_ranking:
        for name, data in sector_ranking:
            if name == sec:
                rank = data.get("rank", 999)
                total_sectors = max(len(sector_ranking), 1)
                # 前1/3 加分，中间不动，后1/3 减分
                if rank == 0:
                    s += 1.5
                elif rank == 1:
                    s += 1.0
                elif rank == 2:
                    s += 0.5
                elif rank >= total_sectors * 0.7:
                    s -= 0.5
                break

    # ② 近5日成交额变化
    vol_5d_ratio = 1.0
    if kl and len(kl) >= 10:
        recent_5_vol = sum(k.get("volume", 0) or 0 for k in kl[-5:])
        prev_5_vol = sum(k.get("volume", 0) or 0 for k in kl[-10:-5])
        if prev_5_vol > 0 and recent_5_vol > 0:
            vol_5d_ratio = recent_5_vol / prev_5_vol
            if vol_5d_ratio > 2.0:
                s += 1.5
            elif vol_5d_ratio > 1.5:
                s += 1.0
            elif vol_5d_ratio > 1.2:
                s += 0.5
            elif vol_5d_ratio < 0.4:
                s -= 1.0
            elif vol_5d_ratio < 0.6:
                s -= 0.5
            elif vol_5d_ratio < 0.8:
                s -= 0.2

    # ③ 近5日收盘价变化
    pct_5d = 0.0
    if kl and len(kl) >= 6:
        close_5d_ago = kl[-6].get("close", 0) or 0
        close_now = kl[-1].get("close", 0) or 0
        if close_5d_ago > 0:
            pct_5d = (close_now - close_5d_ago) / close_5d_ago * 100
            if pct_5d > 15:
                s += 1.5
            elif pct_5d > 10:
                s += 1.0
            elif pct_5d > 5:
                s += 0.5
            elif pct_5d > 0:
                s += 0.2
            elif pct_5d < -15:
                s -= 1.5
            elif pct_5d < -10:
                s -= 1.0
            elif pct_5d < -5:
                s -= 0.5
            elif pct_5d < -2:
                s -= 0.2

    # ④ 量价共振
    if kl and len(kl) >= 10:
        recent_5_vol = sum(k.get("volume", 0) or 0 for k in kl[-5:])
        prev_5_vol = sum(k.get("volume", 0) or 0 for k in kl[-10:-5])
        close_5d_ago = kl[-6].get("close", 0) or 0
        close_now = kl[-1].get("close", 0) or 0
        if prev_5_vol > 0 and close_5d_ago > 0:
            v_ratio = recent_5_vol / prev_5_vol
            p_ratio = (close_now - close_5d_ago) / close_5d_ago * 100
            if p_ratio > 3 and v_ratio > 1.2:
                s += 0.5  # 量价齐升
            elif p_ratio < -3 and v_ratio > 1.2:
                s -= 0.5  # 放量下跌

    # ⑤ 板块内相对强弱（个股vs板块平均）
    if sector_ranking and kl and len(kl) >= 6:
        for name, data in sector_ranking:
            if name == sec:
                sector_avg_5d = data.get("avg_5d_pct", 0)
                close_5d_ago = kl[-6].get("close", 0) or 0
                close_now = kl[-1].get("close", 0) or 0
                if close_5d_ago > 0:
                    stock_5d = (close_now - close_5d_ago) / close_5d_ago * 100
                    relative = stock_5d - sector_avg_5d
                    if relative > 5:
                        s += 0.5
                    elif relative > 2:
                        s += 0.2
                    elif relative < -5:
                        s -= 0.5
                    elif relative < -2:
                        s -= 0.2
                break

    return s  # 未clamp，百分位排名会处理归一化


def chan_score(
    p: Dict[str, Any],
    kl: List[Dict],
) -> Tuple[int, Dict[str, Any]]:
    """缠论评分 — 统一评分规则（已细化多 tier 版本）。"""
    from scripts.quantrisk.indicators import calc_ma, calc_macd, chan_risk_assessment

    if not kl or len(kl) < 60:
        return 3, {}
    s, d = 2.0, {}
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
                # MA排列 — 细化 7 档
                if m5 > m20 > m60 and close > m5:
                    d["ma_alignment"] = "三线多头↑"
                    d["ma_trend"] = "强势"
                    s += 1.5
                elif m5 > m20 > m60:
                    d["ma_alignment"] = "多头排列↑"
                    d["ma_trend"] = "强势"
                    s += 1.2
                elif m5 < m20 < m60 and close < m60:
                    d["ma_alignment"] = "三线空头↓"
                    d["ma_trend"] = "弱势"
                    s -= 1.2
                elif m5 < m20 < m60:
                    d["ma_alignment"] = "空头排列↓"
                    d["ma_trend"] = "弱势"
                    s -= 0.6
                else:
                    if close > m60:
                        d["ma_trend"] = "偏多"
                        s += 0.5
                    else:
                        d["ma_trend"] = "偏空"
                        s -= 0.3
                    if m5 > m20:
                        d["ma_alignment"] = "短期金叉"
                        s += 0.3
                    else:
                        d["ma_alignment"] = "短期死叉"
                        s -= 0.3
                above_count = sum([close > m5, close > m20, close > m60])
                d["ma_above_count"] = above_count
                d["ma_pos_summary"] = {3: "三线之上", 2: "两线之上", 1: "一线之上"}.get(above_count, "三线之下")

            # MA交叉 — 细化 5 档
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
                        s += 1.0
                    elif prev_m20 >= prev_m60 and m20 < m60:
                        d["ma_cross_medium"] = "MA20死叉MA60↓"
                        s -= 1.0

        # MACD — 细化 6 档
        if md and len(md) > 0:
            m = md[-1]
            hi = m.get("macd_hist", (m["dif"] - m["dea"]) * 2)
            d["mh"] = round(hi, 4)
            if len(md) >= 2:
                pm = md[-2]
                ph = pm.get("macd_hist", (pm["dif"] - pm["dea"]) * 2)
                if ph < 0 < hi:
                    d["mc"] = "金叉↑"
                    s += 1.2 if hi > 0.5 else 0.8
                elif ph > 0 > hi:
                    d["mc"] = "死叉↓"
                    s -= 1.2 if hi < -0.5 else 0.8
                elif hi > 0:
                    s += 0.3
                else:
                    s -= 0.3
            elif hi > 0:
                s += 0.3
            else:
                s -= 0.3
            d["mc"] = d.get("mc", "无交叉")

        # 缠论信号 — 从 chan_risk_assessment 的 buy_sell_points 提取买卖点
        cv_data = cv if isinstance(cv, dict) else {}
        buy_pts = cv_data.get("buy_sell_points", {}).get("buy_points", [])
        sell_pts = cv_data.get("buy_sell_points", {}).get("sell_points", [])
        sig = ""
        if buy_pts:
            top_level = max(bp.get("level", "weak") for bp in buy_pts)
            sig = f"买点({top_level})"
            s += 1.5 if top_level == "strong" else 1.0
        elif sell_pts:
            top_level = max(sp.get("level", "potential") for sp in sell_pts)
            sig = f"卖点({top_level})"
            s -= 1.5 if top_level == "strong" else 1.0
        else:
            # 无明确买卖点，用 chan_verdict 补充趋势判断
            cv_verdict = cv_data.get("chan_verdict", "")
            if "偏多" in cv_verdict:
                sig = "趋势偏多"
                s += 0.3
            elif "偏空" in cv_verdict:
                sig = "趋势偏空"
                s -= 0.3
            else:
                sig = "中性震荡"
        d["v"] = sig

        # ── 深度缠论数据（2026-07-21 新增） ──
        # 最近底分型 / 顶分型
        fractals = cv_data.get("fractals", [])
        if fractals:
            # 最近一个底分型
            bottom_fx = [f for f in fractals if f.get("type") == "bottom"][-1]
            d["day_bottom_fx"] = bottom_fx.get("low")
            d["day_bottom_fx_date"] = bottom_fx.get("date", "")
            # 最近一个顶分型
            top_fx = [f for f in fractals if f.get("type") == "top"][-1]
            d["day_top_fx"] = top_fx.get("high")
            # 是否站上 MA5（底分型后价格站上 MA5）
            if m5 and bottom_fx.get("low"):
                d["day_above_ma5"] = close > m5

        # 最近一笔方向
        strokes = cv_data.get("strokes", [])
        if strokes:
            last_bi = strokes[-1]
            d["day_last_bi_dir"] = last_bi.get("direction", "")

        # 买卖点详情
        bs_parts = []
        for bp in buy_pts:
            bs_parts.append(f"{bp.get('type','')}-{bp.get('level','')}")
        for sp in sell_pts:
            bs_parts.append(f"{sp.get('type','')}-{sp.get('level','')}")
        d["buy_sell_detail"] = "; ".join(bs_parts) if bs_parts else "无"

        # 背驰详情
        div_parts = []
        for div in cv_data.get("divergences", []):
            div_parts.append(f"{div.get('type','')}({div.get('severity','')})")
        d["divergence_detail"] = "; ".join(div_parts) if div_parts else "无"

        # 缠论综合结论
        d["chan_verdict"] = cv_data.get("chan_verdict", "")
    except Exception as e:
        d["e"] = str(e)
    return s, d  # 未clamp，百分位排名会处理归一化


# ── 大师视角 + 其他大师质疑 生成（2026-07-22 新增） ──
MASTER_PERSPECTIVES = {
    "生意质量（段永平）": {"owner": "段永平", "question": "这是对的生意吗？", "others": ["巴菲特", "芒格", "李录"]},
    "护城河（巴菲特）": {"owner": "巴菲特", "question": "够便宜吗？有安全边际吗？", "others": ["段永平", "芒格", "李录"]},
    "管理层（段永平+巴菲特）": {"owner": "段永平+巴菲特", "question": "管理层值得信任吗？", "others": ["芒格", "李录"]},
    "最大风险（芒格）": {"owner": "芒格", "question": "怎么会死？有什么风险？", "others": ["段永平", "巴菲特", "李录"]},
    "文明趋势（李录）": {"owner": "李录", "question": "10年后还在吗？", "others": ["段永平", "巴菲特", "芒格"]},
    "估值（巴菲特+段永平）": {"owner": "巴菲特+段永平", "question": "价格有安全边际吗？", "others": ["芒格", "李录"]},
}


def _pe_text(pe):
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
    if dr is None: return "无数据"
    try:
        d = float(dr)
        if d > 70: return f"负债率{d}%过高，财务风险大"
        elif d > 50: return f"负债率{d}%超50%，杠杆偏高"
        else: return f"负债率{d}%，风险可控"
    except (ValueError, TypeError):
        return "无数据"


def _rev_text(rev):
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


def _gen_master_view(dim_key, pe, roe, gm, np_margin, rev_yoy, net_yoy, dr):
    """生成大师视角：核心追问 + 大师基于数据的观点"""
    if dim_key not in MASTER_PERSPECTIVES:
        return ""
    question = MASTER_PERSPECTIVES[dim_key]["question"]
    parts = [f"**核心追问**：{question}"]
    if "生意质量" in dim_key:
        parts.extend([f"毛利率{gm}%，{_gm_text(gm)}", f"ROE{roe}%，{_roe_text(roe)}", f"净利率{np_margin}%，{_np_text(np_margin)}"])
    elif "护城河" in dim_key:
        parts.extend([f"ROE{roe}%，{_roe_text(roe)}", f"毛利率{gm}%，{_gm_text(gm)}", f"负债率{dr}%，{_dr_text(dr)}"])
    elif "管理层" in dim_key:
        parts.extend([f"ROE{roe}%，{_roe_text(roe)}", f"营收增速{rev_yoy}%，{_rev_text(rev_yoy)}", f"净利率{np_margin}%，{_np_text(np_margin)}"])
    elif "最大风险" in dim_key:
        parts.extend([f"负债率{dr}%，{_dr_text(dr)}", f"营收增速{rev_yoy}%，{_rev_text(rev_yoy)}", f"净利增速{net_yoy}%，{_net_text(net_yoy)}"])
    elif "文明趋势" in dim_key:
        parts.extend([f"营收增速{rev_yoy}%，{_rev_text(rev_yoy)}", f"净利率{np_margin}%，{_np_text(np_margin)}", f"ROE{roe}%，{_roe_text(roe)}"])
    elif "估值" in dim_key:
        parts.extend([f"PE{pe}，{_pe_text(pe)}"])
    return "；".join(parts)


def _gen_other_masters_challenge(dim_key, pe, roe, gm, np_margin, rev_yoy, net_yoy, dr):
    """生成其他大师对当前维度的质疑"""
    if dim_key not in MASTER_PERSPECTIVES:
        return ""
    others = MASTER_PERSPECTIVES[dim_key]["others"]
    challenges = []
    for master in others:
        if master == "段永平":
            challenges.append(f"段永平：{_gm_text(gm)}；{_roe_text(roe)}；{_np_text(np_margin)}")
        elif master == "巴菲特":
            challenges.append(f"巴菲特：{_pe_text(pe)}；{_roe_text(roe)}；{_dr_text(dr)}")
        elif master == "芒格":
            challenges.append(f"芒格：{_dr_text(dr)}；{_rev_text(rev_yoy)}；{_net_text(net_yoy)}")
        elif master == "李录":
            challenges.append(f"李录：{_rev_text(rev_yoy)}；{_np_text(np_margin)}；{_dr_text(dr)}")
    return "<br/>".join(challenges)


def _gen_master_answer(dim_key, pe, roe, gm, np_margin, rev_yoy, net_yoy, dr):
    """生成大师答疑：归属大师针对其他大师质疑的回答"""
    if dim_key not in MASTER_PERSPECTIVES:
        return ""
    owner = MASTER_PERSPECTIVES[dim_key]["owner"]
    others = MASTER_PERSPECTIVES[dim_key]["others"]
    parts = [f"**{owner}回应**："]
    for master in others:
        if master == "巴菲特":
            parts.append(f"巴菲特说{_pe_text(pe)}、{_roe_text(roe)}")
            if "生意质量" in dim_key or "管理层" in dim_key:
                parts.append(f"但毛利率{gm}%说明生意本质好，{_np_text(np_margin)}")
            elif "文明趋势" in dim_key:
                parts.append(f"但营收增速{rev_yoy}%说明长期趋势向上，{_dr_text(dr)}")
            elif "最大风险" in dim_key:
                parts.append("但本维度核心是风险，估值和ROE只是辅助判断")
        elif master == "段永平":
            parts.append(f"段永平说{_gm_text(gm)}、{_roe_text(roe)}")
            if "护城河" in dim_key:
                parts.append(f"但护城河看的是综合竞争力，{_dr_text(dr)}")
            elif "最大风险" in dim_key:
                parts.append("但风险维度看的是下行保护，好生意也会面临风险")
            elif "文明趋势" in dim_key or "估值" in dim_key:
                parts.append(f"但本维度侧重不同——{_rev_text(rev_yoy)}")
        elif master == "芒格":
            parts.append(f"芒格说{_dr_text(dr)}、{_rev_text(rev_yoy)}")
            if "生意质量" in dim_key:
                parts.append(f"但生意质量看的是商业模式本质，{_gm_text(gm)}")
            elif "护城河" in dim_key:
                parts.append(f"但护城河看的是长期竞争优势，{_roe_text(roe)}")
            elif "文明趋势" in dim_key:
                parts.append(f"但长期趋势看的是10年确定性，{_np_text(np_margin)}")
            elif "估值" in dim_key:
                parts.append("但估值维度看的是价格安全边际，风险已体现在负债率中")
        elif master == "李录":
            parts.append(f"李录说{_rev_text(rev_yoy)}、{_dr_text(dr)}、{_np_text(np_margin)}")
            if "生意质量" in dim_key:
                parts.append(f"但生意质量更关注当期盈利能力，{_gm_text(gm)}")
            elif "护城河" in dim_key or "最大风险" in dim_key:
                parts.append(f"但本维度侧重不同——{_roe_text(roe)}")
            elif "估值" in dim_key:
                parts.append("但估值看的是当前价格是否合理，长期确定性是参考")
    return "；".join(parts)


def _raw_score_one(
    p: Dict[str, Any],
    kl: List[Dict],
    industry_thresholds: Dict[str, int],
    sector_ranking: Optional[List[Tuple[str, Any]]] = None,
    market: str = "hk",
) -> Dict[str, Any]:
    """计算单只股票的原始分（fb/hot/ch，未做百分位排名）。

    基本面评分采用六维评分（2026-07-22 重构）：
      - 生意质量(段永平) × 等权
      - 护城河(巴菲特) × 等权
      - 管理层(段永平+巴菲特) × 等权
      - 最大风险(芒格) × 等权
      - 文明趋势(李录) × 等权
      - 估值(巴菲特+段永平) × 等权
      六维等权合成 → 满分60分
    """
    c = p["c"]
    pe_limit = industry_thresholds.get(p.get("s", "其他"), 60)

    # 六维评分
    dim1_s, dim1_d, dim1_c, dim1_conf = dim_business_quality(p)
    dim2_s, dim2_d, dim2_c, dim2_conf = dim_moat(p)
    dim3_s, dim3_d, dim3_c, dim3_conf = dim_management(p)
    dim4_s, dim4_d, dim4_c, dim4_conf = dim_risk(p)
    dim5_s, dim5_d, dim5_c, dim5_conf = dim_trend(p)
    dim6_s, dim6_d, dim6_c, dim6_conf = dim_valuation(p, p.get("s", "其他"), pe_limit)

    # 合成基本面原始分（六维等权，用于百分位排名）
    fb_raw = (dim1_s + dim2_s + dim3_s + dim4_s + dim5_s + dim6_s) / 6

    # 芒格式逆向检验
    reverse_test = _munger_reverse_test(p)

    # 信息丰富度评级
    ir_rating, ir_detail = info_richness_rating(p)

    # 大师视角 + 其他大师质疑（2026-07-22 新增）
    ind = p.get("ind", {}) or {}
    q = p.get("q", {}) or {}
    pe_val = p.get("pe", None)
    roe_val = ind.get("ROE") or ind.get("JQROE") or None
    gm_val = ind.get("GROSS_PROFIT_RATIO") or None
    np_val = q.get("profit_margin", None) or None
    rev_val = p.get("rev", None)
    ny_val = p.get("ny", None)
    dr_val = ind.get("DEBT_ASSET_RATIO") or None

    dim_keys = [
        "生意质量（段永平）", "护城河（巴菲特）", "管理层（段永平+巴菲特）",
        "最大风险（芒格）", "文明趋势（李录）", "估值（巴菲特+段永平）",
    ]
    # 六维结论 = 大师视角（归属大师的基于财务数据的具体观点）
    dim_conclusions = [dim1_c, dim2_c, dim3_c, dim4_c, dim5_c, dim6_c]
    # 其他大师质疑 + 大师答疑
    other_masters = {}
    master_answers = {}
    for i, dk in enumerate(dim_keys):
        other_masters[f"dim{i+1}_other_masters"] = _gen_other_masters_challenge(dk, pe_val, roe_val, gm_val, np_val, rev_val, ny_val, dr_val)
        master_answers[f"dim{i+1}_master_answer"] = _gen_master_answer(dk, pe_val, roe_val, gm_val, np_val, rev_val, ny_val, dr_val)

    hot = hot_score(p, kl, sector_ranking, market)
    ch, cd = chan_score(p, kl)

    return {
        "c": c, "n": p["n"], "s": p["s"], "p": p["p"], "mc": p["mc"], "pe": p["pe"],
        "fb_raw": fb_raw, "hot_raw": hot, "ch_raw": ch,
        "fb_debug": f"生意质量:{dim1_d} | 护城河:{dim2_d} | 管理层:{dim3_d} | 风险:{dim4_d} | 趋势:{dim5_d} | 估值:{dim6_d}",
        # 六维原始分（用于百分位排名）
        "dim1_raw": dim1_s, "dim2_raw": dim2_s, "dim3_raw": dim3_s,
        "dim4_raw": dim4_s, "dim5_raw": dim5_s, "dim6_raw": dim6_s,
        "dim1_debug": dim1_d, "dim2_debug": dim2_d, "dim3_debug": dim3_d,
        "dim4_debug": dim4_d, "dim5_debug": dim5_d, "dim6_debug": dim6_d,
        # 六维结论 + 信心度（结论 = 大师视角，2026-07-23 更新）
        "dim1_conclusion": dim1_c, "dim2_conclusion": dim2_c, "dim3_conclusion": dim3_c,
        "dim4_conclusion": dim4_c, "dim5_conclusion": dim5_c, "dim6_conclusion": dim6_c,
        "dim1_confidence": dim1_conf, "dim2_confidence": dim2_conf, "dim3_confidence": dim3_conf,
        "dim4_confidence": dim4_conf, "dim5_confidence": dim5_conf, "dim6_confidence": dim6_conf,
        # 其他大师质疑 + 大师答疑（2026-07-23 新增）
        **other_masters,
        **master_answers,
        "reverse_test": reverse_test,
        "info_richness": ir_rating,
        "info_richness_detail": ir_detail,
        "pw": p.get("pw", ""), "ny": p.get("ny"), "rev": p.get("rev"),
        "q": p.get("q", {}), "ind": p.get("ind", {}), "kl": kl, "cd": cd,
    }


def percentile_score_all(
    raw_scores: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """对所有已算好原始分的候选股做池内百分位排名，归一化到 1-10。

    基本面评分采用六维等权合成（2026-07-22 重构）：
      六维各自百分位排名 → 等权求和 → 映射到 1~5 → × 12 = 60分

    Args:
        raw_scores: _raw_score_one 的返回结果列表，每项含 dim1_raw~dim6_raw/hot_raw/ch_raw。

    返回:
        按总分降序排列的 scored 列表，每项含 fb/hot/ch/total/advice。
    """
    if not raw_scores:
        return []

    # 各维度的原始分列表
    hot_raws = [r["hot_raw"] for r in raw_scores]
    ch_raws = [r["ch_raw"] for r in raw_scores]

    # 六维原始分
    dim_raws = {}
    for i in range(1, 7):
        dim_raws[i] = [r.get(f"dim{i}_raw", 4.0) for r in raw_scores]

    for r in raw_scores:
        # 六维百分位排名（各自在池内的百分位 0~1）
        dim_pcts = {}
        for i in range(1, 7):
            dim_pcts[i] = _percentile(dim_raws[i], r.get(f"dim{i}_raw", 4.0))

        # 等权合成基本面百分位（0~1）
        fb_pct = sum(dim_pcts.values()) / 6
        # 映射到 1~5
        fb_exact = 1 + fb_pct * 4
        r["fb"] = round(fb_exact, 1)
        r["fb_w"] = round(fb_exact * 12, 1)

        # 六维百分位展示（1~10）
        for i in range(1, 7):
            r[f"dim{i}"] = round(1 + dim_pcts[i] * 9, 1)  # 1~10 映射
            r[f"dim{i}_pct"] = round(dim_pcts[i], 3)

        # 技术面百分位
        hot_pct = _percentile(hot_raws, r["hot_raw"])
        ch_pct = _percentile(ch_raws, r["ch_raw"])
        hot_exact = 1 + hot_pct * 4
        ch_exact = 1 + ch_pct * 4
        r["hot"] = round(hot_exact, 1)
        r["ch"] = round(ch_exact, 1)

        # 加权得分：基本面60分(×12) + 技术面40分(hot×4 + ch×4) = 100分
        fb_w_exact = fb_exact * 12
        hot_w_exact = hot_exact * 4
        ch_w_exact = ch_exact * 4
        r["fb_w"] = round(fb_w_exact, 1)
        r["hot_w"] = round(hot_w_exact, 1)
        r["ch_w"] = round(ch_w_exact, 1)
        r["total"] = round(fb_w_exact + hot_w_exact + ch_w_exact, 1)

        # 建议（按100分制，考虑信息丰富度）
        t = r["total"]
        ir = r.get("info_richness", "?")
        if t >= 70:
            if ir == "C级":
                r["advice"] = "可关注"
            else:
                r["advice"] = "强烈关注"
        elif t >= 56:
            if ir == "C级":
                r["advice"] = "观察"
            else:
                r["advice"] = "可关注"
        elif t >= 44:
            r["advice"] = "观察"
        else:
            r["advice"] = "回避"

    return sorted(raw_scores, key=lambda r: r["total"], reverse=True)


def score_one(
    p: Dict[str, Any],
    kl: List[Dict],
    sector_ranking: Optional[List[Tuple[str, Any]]] = None,
    industry_thresholds: Dict[str, int] = None,
    market: str = "hk",
) -> Dict[str, Any]:
    """单只股票三维评分。"""
    c = p["c"]
    pe_limit = (industry_thresholds or {}).get(p.get("s", "其他"), 60)

    fb, _ = fb_score(p, p.get("s", "其他"), pe_limit)
    fb = _clamp(fb)
    hot = _clamp(hot_score(p, kl, sector_ranking, market))
    ch, cd = _clamp(chan_score(p, kl)[0]), chan_score(p, kl)[1]
    fb_w = round(fb * 12, 1)
    hot_w = round(hot * 4, 1)
    ch_w = round(ch * 4, 1)
    total = round(fb_w + hot_w + ch_w, 1)

    return {
        "c": c, "n": p["n"], "s": p["s"], "p": p["p"], "mc": p["mc"], "pe": p["pe"],
        "fb": fb, "hot": hot, "ch": ch, "total": total,
        "fb_w": fb_w, "hot_w": hot_w, "ch_w": ch_w,
        "pw": p.get("pw", ""),
        "ny": p.get("ny"), "rev": p.get("rev"), "kl": kl, "cd": cd,
        "q": p["q"], "ind": p["ind"],
    }


# ═══════════════════════════════════════════════════════════════
# 格式化输出辅助
# ═══════════════════════════════════════════════════════════════

def build_selection_data(
    ds: str,
    ss: Dict[str, Dict],
    elim: List[Tuple[str, str, str]],
    scored: List[Dict[str, Any]],
    passed_cnt: int,
    sector_ranking: Optional[List[Tuple[str, Any]]] = None,
    vetoed: Optional[List[Tuple[str, str, str]]] = None,
) -> dict:
    """将内部数据结构转为 format_output() 所需的 JSON Schema。

    Args:
        vetoed: 基本面一票否决的标的 [(code, name, reason)]，追加到 eliminated 之前展示
    """
    from scripts.quantrisk.indicators import calc_stop_loss_take_profit

    top10 = scored[:10]

    # sectors
    sectors_data = []
    for sec_name, s_info in ss.items():
        sectors_data.append({
            "sector": sec_name,
            "count": s_info.get("c", 0),
            "pct": round(s_info.get("ap", 0)),
            "up": s_info.get("up", 0),
            "dn": s_info.get("dn", 0),
        })

    # eliminated
    eliminated_data = [{"code": c, "name": n, "reason": r} for c, n, r in elim]

    # top10
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

    # details (top 5)
    details_data = []
    for s in top10[:5]:
        idx = scored.index(s) + 1
        chg = (s["q"].get("change_pct") or 0) if s.get("q") else 0
        ind = s.get("ind", {}) or {}
        d = s.get("cd", {}) or {}
        sltp = {}

        kl = s.get("kl", [])
        if kl and len(kl) >= 20:
            sltp = calc_stop_loss_take_profit(entry_price=s["p"], klines=kl[-60:])
        sl_point = sltp.get("stop_loss") or round(s["p"] * 0.92, 2)
        tp_point = sltp.get("take_profit") or round(s["p"] * 1.15, 2)
        t = s["total"]
        advice = ("强烈关注，适合布局" if t >= 70 else
                  "可适当关注，等待入场时机" if t >= 56 else
                  "纳入观察清单，等待催化剂" if t >= 44 else "暂时回避，等待改善")

        # 热点描述 — 基于近5日成交额变化+收盘价变化
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

        # 量比描述
        if vol_5d_ratio > 2.0:
            vol_desc = f"放巨量({vol_5d_ratio:.1f}x)"
        elif vol_5d_ratio > 1.5:
            vol_desc = f"放量({vol_5d_ratio:.1f}x)"
        elif vol_5d_ratio < 0.5:
            vol_desc = f"缩量({vol_5d_ratio:.1f}x)"
        else:
            vol_desc = f"量平({vol_5d_ratio:.1f}x)"

        pct_desc = f"{'%2B' if pct_5d >= 0 else ''}{pct_5d:.2f}%"
        hot_desc = f"{s['s']}板块 5日量{vol_desc} | 5日涨幅{pct_desc}"

        # 缠论信号
        v_str = str(d.get("v", ""))
        sig = v_str if v_str and v_str != "等待信号" else "macd待确认"
        macd_hist = d.get("mh", "?")
        ma60 = d.get("ma60", "?")
        ma60 = round(ma60, 2) if ma60 != "?" else "?"

        details_data.append({
            "rank": idx,
            "code": s["c"],
            "name": s["n"],
            "price": s.get("p"),
            "pct": chg,
            "advice": advice,
            "stop_loss": sl_point,
            "take_profit": tp_point,
            "total": s["total"],
            "fb": {
                "score": s["fb"],
                "score_w": s.get("fb_w", round(s["fb"] * 12, 1)),
                "debug": s.get("fb_debug", ""),
                "pe": s.get("pe", "?"),
                "revenue_yoy": s.get("rev", "?"),
                "net_profit_yoy": s.get("ny", "?"),
                "roe": ind.get("ROE") or ind.get("JQROE") or "?",
                "gross_margin": ind.get("GROSS_PROFIT_RATIO") or "?",
                "debt_ratio": ind.get("DEBT_ASSET_RATIO") or "?",
                # 六维评分（2026-07-22 重构）
                "dim1_score": s.get("dim1", "?"),
                "dim2_score": s.get("dim2", "?"),
                "dim3_score": s.get("dim3", "?"),
                "dim4_score": s.get("dim4", "?"),
                "dim5_score": s.get("dim5", "?"),
                "dim6_score": s.get("dim6", "?"),
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
                # 芒格式逆向检验
                "reverse_test": s.get("reverse_test", ""),
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
                "price": s.get("p"),
                "macd_hist": macd_hist,
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
                "day_ma5": d.get("ma5", "?"),
                "day_bottom_fx": d.get("day_bottom_fx", "?"),
                "day_top_fx": d.get("day_top_fx", "?"),
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

    # summary
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
            "buy": s.get("p"),
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
