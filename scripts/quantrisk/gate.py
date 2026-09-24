"""基本面门禁（2026-09-24 grill Q1/Q5/Q6/Q11 落地）。

定位（铁律，改动时同步 AGENTS.md）：
- 基本面**只否决不加分**：不进 100 分评分（评分仍纯技术：趋势30/量价25/日线道氏20/30m道氏25）
- 触发规则 → 从推荐 TOP10 剔除并渲染 ⛔ 行；回测记录 veto=True 供分组对比（Q4-B）
- 已持仓只标"不加仓"，**卖出裁决仍完全由道氏 `_dow_verdict()` 决定**（Q6=C）
- 执行位置 = 后置门禁（Q11=B）：只对完成 swing 评分的候选（≤80 只/市场）+ 持仓标的拉财务，
  不扫全池（避免打爆东财 datacenter 限流）

规则（Q5=C 分市场）：
- A股严（cn_strict）：归母净利为负 / 负债率>70% / 营收同比<-20% / ST·退市，任一触发
- 港股松（hk_loose）：退市风险 / 负债率>80%（港股未盈利成长股是主体，严规则误杀率过高）
- 金融业豁免（2026-09-24 用户确认）：名称含 银行/证券/保险/信托 → **仅豁免负债率规则**
  （银行负债=存款、保险负债=保费准备金，高杠杆是商业模式而非资不抵债信号；
  净利为负/营收崩塌/ST 规则对金融业照常生效），触发豁免时 notes 留痕便于报告解释。

数据缺失：fail-open 不否决，state="unknown"（回测分组归"未评估"，不硬凑样本——共识四.3）。
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

RULE_SETS = {"cn": "cn_strict", "hk": "hk_loose"}
# 金融业（负债=存款/保费/客户保证金，负债率天然是监管结构而非风险信号）→ 豁免负债率规则
FINANCIAL_KEYWORDS = ("银行", "证券", "保险", "信托")


def _num(v: Any) -> Optional[float]:
    """转 float；None/空串/非法值返回 None（与"数据缺失"区分于触发）。"""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _ratio(v: Any) -> Optional[float]:
    """负债率必须落在 (0,100] 才可信（腾讯 f[74] 曾误映射为 5965%/负数杠杆率），
    越界视为字段脏数据 → None（数据缺失，不否决）。"""
    x = _num(v)
    if x is None or not (0 < x <= 100):
        return None
    return x


def evaluate_gate(market: str, name: str, metrics: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """纯函数：按分市场规则评估门禁。

    Args:
        market: "cn" / "hk"
        name: 标的名称（用于 ST/退市风险判定）
        metrics: {"net_profit": 归母净利(任意单位,只看符号),
                  "debt_ratio": 负债率(%),
                  "revenue_yoy": 营收同比(%)}；可含 None

    Returns:
        {"state": "pass"|"veto"|"unknown", "reasons": [str], "notes": [str], "rule_set": str}
        - veto: 至少一条规则触发（即使部分指标缺失）
        - unknown: 无触发 但所有适用数值指标均缺失
        - pass: 有指标可查且全部通过
        - notes: 豁免留痕（如"金融业豁免负债率规则"），供报告解释
    """
    m = metrics or {}
    rule_set = RULE_SETS.get(market, "hk_loose")
    name_s = str(name or "")
    is_financial = any(kw in name_s for kw in FINANCIAL_KEYWORDS)
    reasons: List[str] = []
    notes: List[str] = []
    any_checked = False

    if market == "cn":
        # ① ST/退市（名称即事实，不需要财务数据）
        if "ST" in name_s.upper() or "退" in name_s:
            reasons.append(f"ST/退市风险（{name_s}）")
        # ② 归母净利为负（只看符号，单位无关）
        np_ = _num(m.get("net_profit"))
        if np_ is not None:
            any_checked = True
            if np_ < 0:
                reasons.append(f"归母净利为负（{np_:.2f}）")
        # ③ 负债率 > 70%（金融业豁免：负债=存款/保费，高杠杆是商业模式）
        dr = _ratio(m.get("debt_ratio"))
        if dr is not None:
            any_checked = True
            if dr > 70:
                if is_financial:
                    notes.append(f"金融业豁免负债率规则（{dr:.1f}%>70% 不作否决）")
                else:
                    reasons.append(f"负债率{dr:.1f}%（>70%）")
        # ④ 营收同比 < -20%
        rev = _num(m.get("revenue_yoy"))
        if rev is not None:
            any_checked = True
            if rev < -20:
                reasons.append(f"营收同比{rev:.1f}%（<-20%）")
    else:  # hk（松规则）
        # ① 退市风险
        if "退" in name_s or "摘牌" in name_s:
            reasons.append(f"退市风险（{name_s}）")
        # ② 负债率 > 80%（金融业豁免同 A股）
        dr = _ratio(m.get("debt_ratio"))
        if dr is not None:
            any_checked = True
            if dr > 80:
                if is_financial:
                    notes.append(f"金融业豁免负债率规则（{dr:.1f}%>80% 不作否决）")
                else:
                    reasons.append(f"负债率{dr:.1f}%（>80%）")

    if reasons:
        state = "veto"
    elif not any_checked:
        state = "unknown"
    else:
        state = "pass"
    return {"state": state, "reasons": reasons, "notes": notes, "rule_set": rule_set}


async def fetch_gate_metrics(code: str, market: str) -> Optional[Dict[str, Any]]:
    """拉取门禁所需财务字段；失败/空数据返回 None（上层按 unknown 处理，fail-open）。"""
    try:
        if market == "cn":
            from .data import cn_key_indicators_async, cn_key_indicators_fallback
            rows = await cn_key_indicators_async(code)
            if not rows:
                rows = await cn_key_indicators_fallback(code)
            if not rows:
                return None
            r0 = rows[0] or {}
            np_ = r0.get("HOLDER_PROFIT")
            if np_ is None:
                np_ = r0.get("PARENT_NETPROFIT")
            return {"net_profit": np_,
                    "debt_ratio": r0.get("DEBT_ASSET_RATIO"),
                    "revenue_yoy": r0.get("OPERATE_INCOME_YOY")}
        from .data import hk_fundamentals_async
        payload = await hk_fundamentals_async(code)
        latest = (payload or {}).get("latest") or {}
        if not latest:
            return None
        return {"net_profit": latest.get("HOLDER_PROFIT") or latest.get("NET_PROFIT"),
                "debt_ratio": latest.get("DEBT_ASSET_RATIO"),
                "revenue_yoy": latest.get("OPERATE_INCOME_YOY")}
    except Exception as exc:  # 单只失败绝不拖垮 daily 主流程
        print(f"[WARN] 门禁财务获取失败({code}/{market}): {type(exc).__name__}: {str(exc)[:80]}")
        return None


async def apply_fundamental_gate(results: List[Dict[str, Any]], market: str,
                                 concurrency: int = 4) -> Dict[str, int]:
    """对候选结果并发跑门禁，原地写入每个 result：
      result["gate"] = {"state", "reasons", "rule_set"}
      result["veto"] = state == "veto"
    返回统计 {"evaluated": n, "vetoed": k}。单只异常降级为 unknown，不中断。
    """
    sem = asyncio.Semaphore(concurrency)

    async def one(r: Dict[str, Any]) -> None:
        try:
            async with sem:
                metrics = await fetch_gate_metrics(str(r.get("code") or ""), market)
            gate = evaluate_gate(market, r.get("name") or "", metrics)
        except Exception as exc:
            print(f"[WARN] 门禁评估异常({r.get('code')}): {type(exc).__name__}: {str(exc)[:80]}")
            gate = {"state": "unknown", "reasons": [], "notes": [],
                    "rule_set": RULE_SETS.get(market, "hk_loose")}
        r["gate"] = gate
        r["veto"] = gate["state"] == "veto"

    await asyncio.gather(*[one(r) for r in results])
    vetoed = sum(1 for r in results if r.get("veto"))
    return {"evaluated": len(results), "vetoed": vetoed}


__all__ = ["evaluate_gate", "fetch_gate_metrics", "apply_fundamental_gate", "RULE_SETS"]
