"""
quantrisk — 双策略信号检测模块

两个交易策略：
  - 策略1「回调一买」：趋势跟踪定方向 + 缠论回调找买点 + 趋势跟踪管离场
  - 策略2「突破三买」：大周期定趋势 + 中枢突破 + 回踩确认三买

用法:
    from scripts.quantrisk.strategy import check_strategy_1, check_strategy_2
    signal = check_strategy_1(daily_klines, klines_60min)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


# ═══════════════════════════════════════════════════════════════
# 策略信号结构
# ═══════════════════════════════════════════════════════════════

class StrategySignal:
    """策略信号输出结构"""

    def __init__(
        self,
        strategy_name: str = "暂无策略信号",
        direction: bool = False,
        structure: bool = False,
        entry: bool = False,
        stop_loss: float = 0.0,
        exit_trigger: str = "",
        summary: str = "",
    ):
        self.strategy_name = strategy_name
        self.direction = direction
        self.structure = structure
        self.entry = entry
        self.stop_loss = stop_loss
        self.exit_trigger = exit_trigger
        self.summary = summary

    @property
    def matched(self) -> bool:
        """方向 + 结构 + 入场 全部通过才算匹配"""
        return self.direction and self.structure and self.entry

    def to_dict(self) -> dict:
        return {
            "strategy_name": self.strategy_name,
            "direction": self.direction,
            "structure": self.structure,
            "entry": self.entry,
            "stop_loss": self.stop_loss,
            "exit_trigger": self.exit_trigger,
            "summary": self.summary,
            "matched": self.matched,
        }


# ═══════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════

def _sf(v, d=0.0):
    """安全数值转换"""
    try:
        return float(v) if v not in (None, "-", "", 0, "0") else d
    except (ValueError, TypeError):
        return d


def _last_ma(klines: list, period: int) -> Optional[float]:
    """计算指定周期均线的最新值"""
    from scripts.quantrisk.chan import calc_ma
    if not klines or len(klines) < period:
        return None
    ma_list = calc_ma(klines, [period])
    if not ma_list:
        return None
    val = ma_list[-1].get(f"ma{period}")
    return _sf(val) if val is not None else None


def _latest_price(klines: list) -> Optional[float]:
    """获取最新收盘价"""
    return _sf(klines[-1]["close"]) if klines else None


# ═══════════════════════════════════════════════════════════════
# 策略1: 回调一买系统
# ═══════════════════════════════════════════════════════════════

def check_strategy_1(
    daily_klines: List[Dict[str, Any]],
    klines_60min: Optional[List[Dict[str, Any]]] = None,
) -> StrategySignal:
    """回调一买系统

    ① 方向过滤: 日线收盘价 > 200MA（趋势跟踪，只做多不做空）
    ② 结构判断: 日线上涨趋势中 + 正在走日线向下笔（缠论形态学）
    ③ 入场信号: 60分钟级别底背驰 / 一买（缠论动力学）
    ④ 止损: 60分钟一买最低点下方
    ⑤ 离场: 日线收盘跌破 MA10（趋势跟踪离场）

    Args:
        daily_klines: 日K线数据（至少 200 根）
        klines_60min: 60分钟K线数据（可选，无则只做日线级别判断）

    Returns:
        StrategySignal
    """
    sig = StrategySignal(strategy_name="回调一买")
    detail_parts = []
    price = _latest_price(daily_klines)
    if not price:
        sig.summary = "数据不足，无法判断"
        return sig

    # ── ① 方向过滤: 200MA ──
    ma200 = _last_ma(daily_klines, 200)
    if ma200 is not None and price > ma200:
        sig.direction = True
        detail_parts.append(f"方向: 200MA({ma200:.2f})之上，现价{price:.2f} ✅")
    else:
        reason = f"200MA({ma200:.2f})之下或数据不足" if ma200 else "200MA数据不足"
        detail_parts.append(f"方向: {reason} ❌")
        sig.summary = f"股价{price:.2f}未站上200MA，方向过滤不通过"
        return sig

    # ── ② 结构判断: 日线上涨趋势 + 向下笔回调 ──
    from scripts.quantrisk.chan import chan_risk_assessment
    daily_ca = chan_risk_assessment(daily_klines)
    daily_trend = daily_ca.get("trend", {})
    daily_strokes = daily_ca.get("strokes", [])

    trend_up = daily_trend.get("direction") == "up"
    last_stroke_down = False
    if daily_strokes:
        last_stroke = daily_strokes[-1]
        last_stroke_down = last_stroke.get("direction") == "down"

    if trend_up and last_stroke_down:
        sig.structure = True
        detail_parts.append("结构: 日线上涨趋势 + 向下笔回调 ✅")
    elif trend_up and not last_stroke_down:
        detail_parts.append("结构: 日线上涨趋势中，但未形成向下笔回调 ⚠️")
    elif not trend_up:
        detail_parts.append(f"结构: 日线趋势为{daily_trend.get('direction','?')}，非上涨趋势 ❌")
        sig.summary = "日线非上涨趋势，不满足回调结构"
        return sig
    else:
        detail_parts.append("结构: 不满足回调条件 ❌")
        sig.summary = "日线结构不满足回调条件"
        return sig

    # ── ③ 入场信号: 60分钟底背驰 / 一买 ──
    if klines_60min and len(klines_60min) >= 30:
        from scripts.quantrisk.chan import chan_theory_full
        chan_60 = chan_theory_full(klines_60min)
        divergences_60 = chan_60.get("divergences", [])
        buy_sell_60 = chan_60.get("buy_sell_points", {})
        buy_points_60 = buy_sell_60.get("buy_points", [])
        has_bottom_div = any(d.get("type") == "bottom_divergence" for d in divergences_60)
        has_first_buy = any(bp.get("type") == "first_buy" for bp in buy_points_60)

        # 计算一买最低价（用于止损）
        first_buy_low = 0.0
        if has_first_buy:
            for bp in buy_points_60:
                if bp.get("type") == "first_buy":
                    first_buy_low = _sf(bp.get("price", 0))
                    break
        elif has_bottom_div:
            # 用最近底分型最低价作为一买近似
            fractals = chan_60.get("fractals", [])
            bottom_fractals = [f for f in fractals if f.get("type") == "bottom"]
            if bottom_fractals:
                first_buy_low = _sf(bottom_fractals[-1].get("low", 0))

        if has_first_buy or has_bottom_div:
            sig.entry = True
            signals = []
            if has_first_buy:
                signals.append("一买")
            if has_bottom_div:
                div_severity = next(
                    (d.get("severity", "weak") for d in divergences_60 if d.get("type") == "bottom_divergence"),
                    "weak",
                )
                signals.append(f"底背驰({div_severity})")
            detail_parts.append(f"入场: 60分钟{' + '.join(signals)} ✅")
        else:
            # 检查是否有潜在一买（用最近底分型判断）
            fractals = chan_60.get("fractals", [])
            bottom_fractals = [f for f in fractals if f.get("type") == "bottom"]
            macd_60 = chan_60.get("klines_count", 0)
            detail_parts.append(f"入场: 60分钟无底背驰/一买信号 ❌")
            sig.summary = "结构成立但60分钟无入场信号，等待底背驰"
            # 但结构已经成立，可以继续传递止损和离场信息
            sig.exit_trigger = "日线收盘跌破MA10离场"
            return sig

        # ── ④ 止损 ──
        if first_buy_low > 0:
            sig.stop_loss = round(first_buy_low * 0.99, 2)
            detail_parts.append(f"止损: {sig.stop_loss}（一买最低价{first_buy_low:.2f}下方）")
        else:
            # 用当前价 - 2ATR 作为止损
            from scripts.quantrisk.indicators import calc_stop_loss_take_profit
            sltp = calc_stop_loss_take_profit(entry_price=price, klines=daily_klines[-60:])
            sig.stop_loss = round(sltp.get("stop_loss", price * 0.92), 2)
            detail_parts.append(f"止损: {sig.stop_loss}（ATR计算）")
    else:
        # 无60分钟数据，降级为日线级别判断
        reason = "60分钟数据不足" if not klines_60min else f"60分钟K线仅{len(klines_60min)}根"
        detail_parts.append(f"入场: ⚠️ {reason}，使用日线级别近似信号")

        # 用日线底背驰/一买作为近似
        divergences_daily = daily_ca.get("divergences", [])
        buy_sell_daily = daily_ca.get("buy_sell_points", {})
        has_bottom_div = any(d.get("type") == "bottom_divergence" for d in divergences_daily)
        has_first_buy = any(bp.get("type") == "first_buy" for bp in buy_sell_daily.get("buy_points", []))

        if has_first_buy or has_bottom_div:
            sig.entry = True
            detail_parts.append("入场: 日线级别底背驰/一买（近似）✅")
            # 日线止损
            from scripts.quantrisk.indicators import calc_stop_loss_take_profit
            sltp = calc_stop_loss_take_profit(entry_price=price, klines=daily_klines[-60:])
            sig.stop_loss = round(sltp.get("stop_loss", price * 0.92), 2)
            detail_parts.append(f"止损: {sig.stop_loss}（ATR计算）")
        else:
            detail_parts.append("入场: 日线级别也无底背驰/一买 ❌")
            sig.summary = "结构成立但无入场信号，等待底背驰"
            sig.exit_trigger = "日线收盘跌破MA10离场"
            return sig

    # ── ⑤ 离场 ──
    ma10 = _last_ma(daily_klines, 10)
    if ma10:
        sig.exit_trigger = f"日线收盘跌破MA10({ma10:.2f})离场"
        detail_parts.append(f"离场: 日线收盘跌破MA10({ma10:.2f})")
    else:
        sig.exit_trigger = "日线收盘跌破MA10离场"
        detail_parts.append("离场: 日线收盘跌破MA10")

    sig.summary = " | ".join(detail_parts)
    return sig


# ═══════════════════════════════════════════════════════════════
# 策略2: 突破三买系统
# ═══════════════════════════════════════════════════════════════

def check_strategy_2(
    daily_klines: List[Dict[str, Any]],
    weekly_klines: Optional[List[Dict[str, Any]]] = None,
    klines_30min: Optional[List[Dict[str, Any]]] = None,
) -> StrategySignal:
    """突破三买系统

    ① 方向过滤: 周线MA60之上 + 周线趋势偏多（大周期定大势）
    ② 结构判断: 日线有中枢 + 股价在中枢上沿附近（蓄势待突破）
    ③ 入场信号: 30分钟级别三买（突破回踩确认）
    ④ 止损: 中枢上沿下方
    ⑤ 离场: 日线收盘跌破 MA20

    Args:
        daily_klines: 日K线数据
        weekly_klines: 周K线数据（可选，无则只做日线级别判断）
        klines_30min: 30分钟K线数据（可选，无则只做日线级别判断）

    Returns:
        StrategySignal
    """
    sig = StrategySignal(strategy_name="突破三买")
    detail_parts = []
    price = _latest_price(daily_klines)
    if not price:
        sig.summary = "数据不足，无法判断"
        return sig

    from scripts.quantrisk.chan import chan_risk_assessment, chan_theory_full

    # ── ① 方向过滤: 周线MA60之上 + 周线偏多 ──
    if weekly_klines and len(weekly_klines) >= 15:
        weekly_ca = chan_risk_assessment(weekly_klines)
        weekly_ma60 = _last_ma(weekly_klines, 60)
        weekly_price = _latest_price(weekly_klines)
        weekly_verdict = weekly_ca.get("chan_verdict", "")

        above_week_ma60 = weekly_ma60 is not None and weekly_price is not None and weekly_price > weekly_ma60
        weekly_bullish = weekly_verdict in ("偏多",)

        if above_week_ma60 and weekly_bullish:
            sig.direction = True
            detail_parts.append(f"方向: 周线MA60({weekly_ma60:.2f})之上 + {weekly_verdict} ✅")
        elif above_week_ma60 and not weekly_bullish:
            detail_parts.append(f"方向: 周线MA60之上但趋势{weekly_verdict} ⚠️")
            sig.direction = True  # 站上MA60即算通过，但标注
        else:
            detail_parts.append(f"方向: 周线未站上MA60({weekly_ma60})或趋势{weekly_verdict} ❌")
            sig.summary = f"周线方向不满足（MA60={weekly_ma60}，现价={weekly_price}）"
            return sig
    else:
        # 无周线数据，降级为日线方向判断
        ma60 = _last_ma(daily_klines, 60)
        if ma60 is not None and price > ma60:
            sig.direction = True
            detail_parts.append(f"方向: ⚠️ 周线数据不足，使用日线MA60({ma60:.2f})之上 ✅")
        else:
            detail_parts.append(f"方向: 数据不足 ❌")
            sig.summary = "方向数据不足"
            return sig

    # ── ② 结构判断: 日线有中枢 + 股价在中枢上沿附近 ──
    daily_ca = chan_risk_assessment(daily_klines)
    daily_pivots = daily_ca.get("pivots", [])
    relative_pos = daily_ca.get("relative_position", "unknown")

    has_pivot = len(daily_pivots) > 0
    above_pivot = relative_pos == "above_pivot"

    if has_pivot and above_pivot:
        sig.structure = True
        last_pivot = daily_pivots[-1]
        zg = last_pivot.get("zg", 0)
        detail_parts.append(f"结构: 日线中枢({zg:.2f})上方，股价{price:.2f} ✅")
    elif has_pivot and not above_pivot:
        if relative_pos == "within_pivot":
            last_pivot = daily_pivots[-1]
            zg = last_pivot.get("zg", 0)
            zd = last_pivot.get("zd", 0)
            detail_parts.append(f"结构: 日线中枢内震荡({zd:.2f}~{zg:.2f})，未突破上沿 ⚠️")
        else:
            detail_parts.append(f"结构: 股价在中枢下方({relative_pos}) ❌")
        sig.summary = "日线结构未形成中枢突破"
        return sig
    else:
        detail_parts.append("结构: 日线无中枢形态 ❌")
        sig.summary = "日线无中枢结构"
        return sig

    # ── ③ 入场信号: 30分钟三买 ──
    pivot_zg = daily_pivots[-1].get("zg", 0)

    if klines_30min and len(klines_30min) >= 30:
        chan_30 = chan_theory_full(klines_30min)
        buy_sell_30 = chan_30.get("buy_sell_points", {})
        buy_points_30 = buy_sell_30.get("buy_points", [])
        has_third_buy = any(bp.get("type") == "third_buy" for bp in buy_points_30)
        has_first_buy = any(bp.get("type") == "first_buy" for bp in buy_points_30)
        has_second_buy = any(bp.get("type") == "second_buy" for bp in buy_points_30)

        # 突破回踩确认：股价曾突破中枢上沿，现在回踩但不破
        # 用30分钟K线最后20根判断是否在中枢上沿附近企稳
        recent_30 = klines_30min[-20:] if len(klines_30min) >= 20 else klines_30min
        recent_low = min(k.get("low", 0) for k in recent_30)
        recent_high = max(k.get("high", 0) for k in recent_30)
        pullback_hold = recent_low > pivot_zg * 0.98  # 回踩不低于中枢上沿的98%

        if has_third_buy or (pullback_hold and has_first_buy):
            sig.entry = True
            signals = []
            if has_third_buy:
                signals.append("三买")
            if pullback_hold:
                signals.append(f"回踩确认(中枢{zg:.2f})")
            detail_parts.append(f"入场: 30分钟{' + '.join(signals)} ✅")
        elif pullback_hold:
            # 回踩确认但无明确三买信号
            sig.entry = True
            detail_parts.append(f"入场: 30分钟回踩中枢上沿企稳 ✅")
        else:
            detail_parts.append(f"入场: 30分钟无三买信号（最近低点{recent_low:.2f}，中枢上沿{pivot_zg:.2f}）❌")
            sig.summary = f"结构成立但30分钟无三买，突破后回踩未确认"
            sig.exit_trigger = "日线收盘跌破MA20离场"
            return sig

        # ── ④ 止损 ──
        sig.stop_loss = round(pivot_zg * 0.98, 2)
        detail_parts.append(f"止损: {sig.stop_loss}（中枢上沿{pivot_zg:.2f}下方2%）")
    else:
        # 无30分钟数据，降级为日线级别判断
        reason = "30分钟数据不足" if not klines_30min else f"30分钟K线仅{len(klines_30min)}根"
        detail_parts.append(f"入场: ⚠️ {reason}，使用日线级别近似信号")

        # 日线三买判断
        buy_sell_daily = daily_ca.get("buy_sell_points", {})
        buy_points_daily = buy_sell_daily.get("buy_points", [])
        has_third_buy_daily = any(bp.get("type") == "third_buy" for bp in buy_points_daily)
        above_zg = price > pivot_zg

        if has_third_buy_daily or above_zg:
            sig.entry = True
            detail_parts.append("入场: 日线级别三买/站稳中枢上沿（近似）✅")
            sig.stop_loss = round(pivot_zg * 0.97, 2)
            detail_parts.append(f"止损: {sig.stop_loss}（日线中枢上沿下方）")
        else:
            detail_parts.append("入场: 日线级别也无三买信号 ❌")
            sig.summary = "结构成立但无入场信号，等待回踩确认"
            sig.exit_trigger = "日线收盘跌破MA20离场"
            return sig

    # ── ⑤ 离场 ──
    ma20 = _last_ma(daily_klines, 20)
    if ma20:
        sig.exit_trigger = f"日线收盘跌破MA20({ma20:.2f})离场"
        detail_parts.append(f"离场: 日线收盘跌破MA20({ma20:.2f})")
    else:
        sig.exit_trigger = "日线收盘跌破MA20离场"
        detail_parts.append("离场: 日线收盘跌破MA20")

    sig.summary = " | ".join(detail_parts)
    return sig