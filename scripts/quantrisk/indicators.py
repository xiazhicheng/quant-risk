"""
quantrisk — 技术指标 + 辅助分析 + 缠论统一导入模块

技术指标 (纯 Python 计算): MA / EMA / MACD / RSI / KDJ / 布林带
辅助分析: 支撑压力 / 止损止盈 / 成交额估算
缠论 API: 从 .chan 导入并 re-export，一站式调用

用法:
    from scripts.quantrisk.indicators import calc_macd, chan_risk_assessment
"""

from .chan import (
    kline_contain,
    find_fractals,
    build_strokes,
    build_segments,
    find_pivots,
    detect_divergence,
    find_buy_sell_points,
    classify_trend,
    chan_theory_full,
    chan_risk_assessment,
)

# ═══════════════════════════════════════════════
# Layer 3: 技术指标层（纯计算）
# ═══════════════════════════════════════════════


def _ema(values: list[float], period: int) -> list[float]:
    """指数移动平均 (EMA) 内部计算"""
    if not values:
        return []
    result = [values[0]]
    k = 2 / (period + 1)
    for v in values[1:]:
        result.append(v * k + result[-1] * (1 - k))
    return result


def calc_ma(klines: list[dict], periods: list[int] = None) -> list[dict]:
    """计算简单移动平均 (MA) 和 EMA12/EMA26。

    Args:
        klines: [{date, open, high, low, close, volume}, ...]
        periods: 需要计算的 MA 周期，默认 [5, 10, 20, 60]

    Returns:
        每条 K 线追加 ma{period} / ema12 / ema26 字段
    """
    if periods is None:
        periods = [5, 10, 20, 60]
    closes = [k["close"] for k in klines]
    ema12, ema26 = _ema(closes, 12), _ema(closes, 26)
    result = []
    for i, k in enumerate(klines):
        row = {"date": k["date"], "close": k["close"]}
        for p in periods:
            row[f"ma{p}"] = round(sum(closes[i - p + 1 : i + 1]) / p, 4) if i >= p - 1 else None
        row["ema12"], row["ema26"] = round(ema12[i], 4), round(ema26[i], 4)
        result.append(row)
    return result


def calc_macd(klines: list[dict], fast: int = 12, slow: int = 26, signal: int = 9) -> list[dict]:
    """计算 MACD 指标。

    Returns:
        每条 K 线追加 dif / dea / macd_hist 字段
    """
    closes = [k["close"] for k in klines]
    dif = [round(f - s, 4) for f, s in zip(_ema(closes, fast), _ema(closes, slow))]
    dea = _ema(dif, signal)
    return [
        {
            "date": k["date"],
            "close": k["close"],
            "dif": round(dif[i], 4),
            "dea": round(dea[i], 4),
            "macd_hist": round((dif[i] - dea[i]) * 2, 4),
        }
        for i, k in enumerate(klines)
    ]


def calc_rsi(klines: list[dict], periods: list[int] = None) -> list[dict]:
    """计算相对强弱指标 (RSI)。

    Args:
        klines: [{date, open, high, low, close, volume}, ...]
        periods: RSI 计算周期，默认 [6, 12, 24]

    Returns:
        每条 K 线追加 rsi{period} 字段
    """
    if periods is None:
        periods = [6, 12, 24]
    closes = [k["close"] for k in klines]
    changes = [0.0] + [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(c, 0) for c in changes]
    losses = [max(-c, 0) for c in changes]
    result = []
    for i, k in enumerate(klines):
        row = {"date": k["date"], "close": k["close"]}
        for p in periods:
            if i < p:
                row[f"rsi{p}"] = None
                continue
            ag = sum(gains[i - p + 1 : i + 1]) / p
            al = sum(losses[i - p + 1 : i + 1]) / p
            row[f"rsi{p}"] = 100.0 if al == 0 else round(100 - 100 / (1 + ag / al), 2)
        result.append(row)
    return result


def calc_kdj(klines: list[dict], n: int = 9, m1: int = 3, m2: int = 3) -> list[dict]:
    """计算 KDJ 随机指标。

    Args:
        n: 周期 (默认 9)
        m1: K 平滑因子 (默认 3)
        m2: D 平滑因子 (默认 3)

    Returns:
        每条 K 线追加 k / d / j 字段
    """
    k_val, d_val = 50.0, 50.0
    result = []
    for i, kline in enumerate(klines):
        if i < n - 1:
            result.append({"date": kline["date"], "close": kline["close"], "k": None, "d": None, "j": None})
            continue
        window = klines[i - n + 1 : i + 1]
        hn = max(i["high"] for i in window)
        ln = min(i["low"] for i in window)
        rsv = (kline["close"] - ln) / (hn - ln) * 100 if hn != ln else 50.0
        k_val = (1 / m1) * rsv + (1 - 1 / m1) * k_val
        d_val = (1 / m2) * k_val + (1 - 1 / m2) * d_val
        result.append(
            {
                "date": kline["date"],
                "close": kline["close"],
                "k": round(k_val, 2),
                "d": round(d_val, 2),
                "j": round(3 * k_val - 2 * d_val, 2),
            }
        )
    return result


def calc_boll(klines: list[dict], period: int = 20, num_std: float = 2.0) -> list[dict]:
    """计算布林带 (Bollinger Bands)。

    Returns:
        每条 K 线追加 upper / middle / lower / bandwidth 字段
    """
    closes = [k["close"] for k in klines]
    result = []
    for i, k in enumerate(klines):
        if i < period - 1:
            result.append(
                {
                    "date": k["date"],
                    "close": k["close"],
                    "upper": None,
                    "middle": None,
                    "lower": None,
                    "bandwidth": None,
                }
            )
            continue
        w = closes[i - period + 1 : i + 1]
        ma = sum(w) / period
        std = (sum((x - ma) ** 2 for x in w) / period) ** 0.5
        up = ma + num_std * std
        lo = ma - num_std * std
        result.append(
            {
                "date": k["date"],
                "close": k["close"],
                "upper": round(up, 4),
                "middle": round(ma, 4),
                "lower": round(lo, 4),
                "bandwidth": round((up - lo) / ma * 100, 2) if ma else None,
            }
        )
    return result


# ═══════════════════════════════════════════════
# 辅助分析函数（纯计算，基于已有数据）
# ═══════════════════════════════════════════════


def calc_support_resistance(klines: list[dict], lookback: int = 60) -> dict:
    """从 K 线数据计算支撑位和压力位。

    支撑位 = 最近 lookback 个交易日中最低价的 EMA(5)
    压力位 = 最近 lookback 个交易日中最高价的 EMA(5)

    Returns:
        {support, resistance, current_support, current_resistance}
    """
    if not klines or len(klines) < 10:
        return {"support": None, "resistance": None}
    window = klines[-min(lookback, len(klines)):]
    lows = [k["low"] for k in window]
    highs = [k["high"] for k in window]

    def _ema5(vals):
        if not vals:
            return [0]
        k = 2 / (5 + 1)
        r = [vals[0]]
        for v in vals[1:]:
            r.append(v * k + r[-1] * (1 - k))
        return r

    s_ema = _ema5(lows)
    r_ema = _ema5(highs)
    return {
        "support": round(s_ema[-1], 2),
        "resistance": round(r_ema[-1], 2),
        "current_support": round(lows[-1], 2),
        "current_resistance": round(highs[-1], 2),
    }


def calc_stop_loss_take_profit(
    entry_price: float,
    atr: float = None,
    klines: list[dict] = None,
) -> dict:
    """止损 / 止盈触发条件。

    如果提供了 ATR，按 ATR 倍数计算；
    否则按最近 N 日最低 / 最高计算（ATR 14）。

    Args:
        entry_price: 入场价
        atr: 平均真实波幅 (ATR)，不提供则从 klines 计算
        klines: 用于计算 ATR 的 K 线数据

    Returns:
        {stop_loss, stop_loss_trigger, take_profit, take_profit_trigger, atr}
    """
    if atr is None and klines and len(klines) > 14:
        closes = [k["close"] for k in klines]
        highs = [k["high"] for k in klines]
        lows = [k["low"] for k in klines]
        tr = []
        for i in range(1, min(15, len(klines))):
            tr.append(
                max(
                    highs[-i] - lows[-i],
                    abs(highs[-i] - closes[-i - 1]),
                    abs(lows[-i] - closes[-i - 1]),
                )
            )
        atr = sum(tr) / len(tr)

    if atr:
        sl = round(entry_price - 2 * atr, 2)
        tp = round(entry_price + 3 * atr, 2)
        sl_pct = round(2 * atr / entry_price * 100, 1)
        tp_pct = round(3 * atr / entry_price * 100, 1)
        return {
            "stop_loss": sl,
            "stop_loss_trigger": f"收盘价跌破 {sl}（-{sl_pct}%）",
            "take_profit": tp,
            "take_profit_trigger": f"收盘价突破 {tp}（+{tp_pct}%）",
            "atr": round(atr, 2),
        }
    return {"stop_loss": None, "take_profit": None, "atr": None}


def calc_turnover_amount(quote: dict, price: float = None) -> dict:
    """从行情数据提取成交额和估算换手率。

    Args:
        quote: 行情字典，支持腾讯/新浪/东财 push2 格式
        price: 当前价格（预留参数，当前从 quote 自动提取）

    Returns:
        {volume_shares, amount_100m, turnover_rate}
    """
    volume = quote.get("volume_shares") or quote.get("volume") or 0
    amount = quote.get("amount_100m") or 0
    turnover = quote.get("turnover_rate")
    amount_100m = round(amount / 1e8, 2) if amount > 1e8 else round(amount, 2)
    return {"volume_shares": int(volume), "amount_100m": amount_100m, "turnover_rate": turnover}


__all__ = [
    # 自有函数
    "_ema",
    "calc_ma",
    "calc_macd",
    "calc_rsi",
    "calc_kdj",
    "calc_boll",
    "calc_support_resistance",
    "calc_stop_loss_take_profit",
    "calc_turnover_amount",
    # 从 .chan re-export
    "kline_contain",
    "find_fractals",
    "build_strokes",
    "build_segments",
    "find_pivots",
    "detect_divergence",
    "find_buy_sell_points",
    "classify_trend",
    "chan_theory_full",
    "chan_risk_assessment",
]
