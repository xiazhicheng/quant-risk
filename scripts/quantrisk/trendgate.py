"""TrendGate: rotation selection with index-wide or per-stock MA gates.

Decisions use t-1 closes, fills use t opens, valuation uses t closes.
Stock mode retains the scheduled top-N basket and leaves closed sleeves in cash.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .rotation import RotationBacktestConfig, cross_section_scores, select_on_date, _metrics
from .multifactor import STOP_LOSS, TAKE_PROFIT, TAKE_PROFIT_DRAWDOWN

HS300_SYMBOL = "sh000300"
HSI_SYMBOL = "hkHSI"


@dataclass
class TrendGateConfig(RotationBacktestConfig):
    gate_mode: str = "index"
    rebalance_mode: str = "periodic"  # periodic=每 N 日强制换仓；event=只按卖出信号离场、买入信号加仓
    exit_on_rank_drop: bool = False   # event 模式：掉出双动量 TOP N 是否也算卖出信号
    add_tolerance: float = 0.05       # event 模式：持仓低于目标权重 (1-该比例) 才补足加仓
    use_ma20_timing: bool = True
    gate_ma: int = 20
    gate_confirm_days: int = 3
    max_exposure: float = 0.7
    target_vol: float | None = None
    use_stock_risk: bool = False
    stop_loss: float = STOP_LOSS
    take_profit: float = TAKE_PROFIT
    take_profit_drawdown: float = TAKE_PROFIT_DRAWDOWN
    # ── 交易摩擦与可成交性（2026-10-14 新增）──
    market: str = "cn"                # cn=有涨跌停约束；hk=无涨跌停
    slippage: float = 0.0             # 单边滑点：买价×(1+s)、卖价×(1-s)
    enforce_price_limits: bool = True  # 开盘涨停买不进 / 开盘跌停卖不出（仅 cn）
    enforce_halts: bool = True         # 停牌（成交量 0/缺失）当日不可成交（需 volume 矩阵）
    limit_pct: float = 0.10            # 主板涨跌停幅度（创业板/科创板 20%、北交所 30%、ST 5% 自动覆写）
    name: str = "trendgate"


@dataclass
class TrendGateResult:
    config: TrendGateConfig
    equity_curve: pd.Series
    holdings: pd.DataFrame
    trades: list[dict]
    rebalance_dates: list
    universe: list[dict]
    metrics: dict[str, float] = field(default_factory=dict)
    fills: list[dict] = field(default_factory=list)
    cash_curve: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    execution: dict = field(default_factory=dict)


def run_trendgate_backtest(close_df: pd.DataFrame, open_df: pd.DataFrame,
                           gate_index: pd.Series | None,
                           config: TrendGateConfig | None = None,
                           universe: list[dict] | None = None,
                           scores_override: pd.DataFrame | None = None,
                           volume_df: pd.DataFrame | None = None) -> TrendGateResult:
    """Same ranking, schedule, costs and execution for both gate modes.

    Stock mode: freeze top-N and equal sleeve budgets at each scheduled rebalance.
    A closed sleeve stays in cash; reopen within that basket at its original budget,
    capped by available cash. No substitution and no index gate in stock mode.
    Missing signals fail closed; missing execution prices defer the trade.

    Tradeability (2026-10-14): opening limit-up blocks buys, opening limit-down blocks
    sells (A-share boards), zero/missing volume means the name is halted that day, and
    a fill slippage is applied on both sides. Blocked sells are retried every later day
    until they clear; blocked buys simply lapse until the next scheduled rebalance.
    """
    cfg = config or TrendGateConfig()
    if cfg.gate_mode not in {"index", "stock"}:
        raise ValueError("gate_mode must be index or stock")
    if cfg.rebalance_mode not in {"periodic", "event"}:
        raise ValueError("rebalance_mode must be periodic or event")
    if not 0 <= cfg.add_tolerance < 1:
        raise ValueError("add_tolerance must be in [0, 1)")
    if not 0 <= cfg.slippage < 1 or not 0 < cfg.limit_pct < 1:
        raise ValueError("slippage must be in [0, 1) and limit_pct in (0, 1)")
    if cfg.market not in {"cn", "hk"}:
        raise ValueError("market must be cn or hk")
    if min(cfg.gate_ma, cfg.gate_confirm_days, cfg.top_n, cfg.rebalance_days,
           cfg.warmup_days, cfg.lot_size) < 1 or cfg.initial_cash <= 0 \
            or not 0 <= cfg.max_exposure <= 1 or not 0 <= cfg.commission_rate < 1:
        raise ValueError("Invalid gate, capital, exposure or cost parameters")
    if cfg.gate_mode == "stock" and (cfg.target_vol or cfg.use_stock_risk):
        raise ValueError("Stock gate comparison does not use index volatility or fixed stock stops")
    close_df = close_df.astype(float).sort_index()
    open_df = open_df.astype(float).reindex(index=close_df.index, columns=close_df.columns)
    volume_df = (volume_df.astype(float).reindex(index=close_df.index, columns=close_df.columns)
                 if volume_df is not None else None)
    scores = cross_section_scores(close_df, (20, 60)) if scores_override is None else \
        scores_override.reindex(index=close_df.index, columns=close_df.columns)
    dates = list(close_df.index)
    if len(dates) <= cfg.warmup_days + 1:
        raise ValueError(f"Insufficient data: need > warmup({cfg.warmup_days}), got {len(dates)}")

    def confirmed(prices):
        ma = prices.rolling(cfg.gate_ma).mean()
        above = prices.notna() & ma.notna() & prices.ge(ma) & prices.gt(0)
        return above.rolling(cfg.gate_confirm_days).sum().eq(cfg.gate_confirm_days)

    index_prices = (gate_index.sort_index().reindex(close_df.index)
                    if gate_index is not None else pd.Series(np.nan, index=close_df.index))
    index_on = confirmed(index_prices)
    stock_on = confirmed(close_df)
    if not cfg.use_ma20_timing:
        index_on[:] = True
        stock_on[:] = True
    exposure = None
    if cfg.target_vol:
        vol = index_prices.pct_change().rolling(20).std() * np.sqrt(252)
        exposure = (cfg.target_vol / vol).clip(lower=0, upper=cfg.max_exposure)

    rebalance_set = set(dates[cfg.warmup_days::cfg.rebalance_days])
    cash = cfg.initial_cash
    positions: dict[str, dict] = {}
    budgets: dict[str, float] = {}
    last_prices: dict[str, float] = {}
    gate_prev_on = False
    equity_curve, holdings_rows, cash_curve = {}, {}, {}
    trades, fills = [], []

    # ── 可成交性：涨跌停 / 停牌 / 滑点（2026-10-14 新增）──
    st_codes = {str(u.get("code")) for u in (universe or [])
                if "ST" in str(u.get("name", "")).upper()}
    pending_sells: dict[str, str] = {}
    blocked = {"limit_up_blocked": 0, "limit_down_blocked": 0, "halt_blocked": 0}

    def limit_pct_for(code: str) -> float:
        if cfg.market != "cn":
            return float("inf")            # 港股无涨跌停
        c = str(code)
        if c in st_codes:
            return 0.05                    # ST/*ST
        if c.startswith(("300", "301", "688", "689")):
            return 0.20                    # 创业板 / 科创板
        if c.startswith(("4", "8")):
            return 0.30                    # 北交所
        return cfg.limit_pct               # 主板

    def fill_price(code, side, ctx):
        """成交价；不可成交返回 None。ctx = (open_row, prev_close_row, vol_row)。"""
        open_row, prev_close_row, vol_row = ctx
        px = open_row.get(code, np.nan)
        if not np.isfinite(px) or px <= 0:
            return None
        if cfg.enforce_halts and vol_row is not None:
            v = vol_row.get(code, np.nan)
            if not np.isfinite(v) or v <= 0:
                blocked["halt_blocked"] += 1
                return None                # 停牌/停板无量
        if cfg.enforce_price_limits and cfg.market == "cn":
            pc = prev_close_row.get(code, np.nan)
            lim = limit_pct_for(code)
            if np.isfinite(pc) and pc > 0 and np.isfinite(lim):
                eps = max(1e-9, pc * 1e-6)
                if side == "buy" and px >= pc * (1 + lim) - eps:
                    blocked["limit_up_blocked"] += 1
                    return None            # 开盘涨停：买不进
                if side == "sell" and px <= pc * (1 - lim) + eps:
                    blocked["limit_down_blocked"] += 1
                    return None            # 开盘跌停：卖不出
        return float(px) * (1 + cfg.slippage) if side == "buy" else float(px) * (1 - cfg.slippage)

    def sell(code, ctx, t, t_prev, reason):
        nonlocal cash
        px = fill_price(code, "sell", ctx)
        if px is None:
            pending_sells[code] = reason   # 跌停/停牌：登记待卖，后续每日重试
            return False
        shares = positions[code]["shares"]
        amount = shares * float(px)
        fee = amount * cfg.commission_rate
        cash += amount - fee
        positions.pop(code)
        pending_sells.pop(code, None)
        fills.append({"date": str(t.date()), "decision_date": str(t_prev.date()),
                      "code": code, "side": "sell", "shares": shares, "price": float(px),
                      "amount": amount, "fee": fee, "reason": reason})
        return True

    def buy(code, budget, ctx, t, t_prev, reason):
        nonlocal cash
        px = fill_price(code, "buy", ctx)
        if px is None:
            return                         # 涨停/停牌买不进：本次放弃，下个调仓日再评估
        shares = int(min(budget, cash) / (float(px) * (1 + cfg.commission_rate))
                     // cfg.lot_size) * cfg.lot_size
        if shares <= 0:
            return
        amount = shares * float(px)
        fee = amount * cfg.commission_rate
        cash -= amount + fee
        positions[code] = {"shares": shares, "cost": float(px), "peak": float(px)}
        last_prices[code] = float(px)
        fills.append({"date": str(t.date()), "decision_date": str(t_prev.date()),
                      "code": code, "side": "buy", "shares": shares, "price": float(px),
                      "amount": amount, "fee": fee, "reason": reason})

    for i in range(cfg.warmup_days, len(dates)):
        t, t_prev = dates[i], dates[i - 1]
        # First-day budget and halted positions must be valued from known past prices.
        known = close_df.loc[t_prev]
        for code, pos in positions.items():
            px = known.get(code, np.nan)
            if np.isfinite(px) and px > 0:
                last_prices[code] = float(px)
        open_row = open_df.loc[t]
        ctx = (open_row, known, volume_df.loc[t] if volume_df is not None else None)
        # 跌停/停牌未成交的卖单：后续每日重试（清仓意图不因一个跌停日作废）
        for code, reason in list(pending_sells.items()):
            if code in positions:
                sell(code, ctx, t, t_prev,
                     reason if reason.endswith("_retry") else reason + "_retry")
        on = bool(index_on.loc[t_prev])

        if cfg.rebalance_mode == "event":
            # ── 事件驱动：不强制换仓；每日只认卖出信号，调仓日才评估买入/加仓 ──
            per_stock_gate = cfg.gate_mode == "stock"

            def gate_ok(code):
                return bool(stock_on.loc[t_prev, code]) if per_stock_gate else bool(on)

            # ① 卖出信号（每日检查）：个股/指数闸门关闭即离场
            if per_stock_gate:
                for code in list(positions):
                    if not gate_ok(code):
                        sell(code, ctx, t, t_prev, "stock_gate_close")
            elif not on and positions:
                for code in list(positions):
                    sell(code, ctx, t, t_prev, "index_gate_close")
                trades.append({"date": str(t.date()), "decision_date": str(t_prev.date()),
                               "action": "timing_close",
                               "note": f"Index MA{cfg.gate_ma} gate closed"})

            # ② 买入/加仓信号（调仓日评估）：新信号入场 + 已有持仓补足目标
            if t in rebalance_set:
                target = select_on_date(scores, t_prev, cfg.min_score, cfg.top_n)
                codes = list(target.index)
                if cfg.exit_on_rank_drop:
                    for code in list(positions):
                        if code not in codes:
                            sell(code, ctx, t, t_prev, "rank_drop")
                prev_equity = cash + sum(p["shares"] * last_prices.get(c, p["cost"])
                                         for c, p in positions.items())
                per = prev_equity * cfg.max_exposure / len(codes) if codes else 0.0
                # 新信号入场：持仓数达 top_n 即停（旧仓不因掉出排名被卖 → 自然占位）
                for code in codes:
                    if len(positions) >= cfg.top_n:
                        break
                    if code in positions or not gate_ok(code):
                        continue
                    buy(code, per, ctx, t, t_prev, "event_entry")
                # 已有持仓：低于目标权重才补足（"单纯买入信号加仓"）
                for code in codes:
                    if code not in positions or not gate_ok(code):
                        continue
                    px = open_row.get(code, np.nan)
                    if not np.isfinite(px) or px <= 0:
                        continue
                    held = positions[code]["shares"] * float(px)
                    if held < per * (1 - cfg.add_tolerance):
                        buy(code, per - held, ctx, t, t_prev, "event_add")
                trades.append({"date": str(t.date()), "decision_date": str(t_prev.date()),
                               "action": "event_review", "target": codes,
                               "positions": {c: p["shares"] for c, p in positions.items()},
                               "cash": round(cash, 2)})
            gate_prev_on = on
        elif cfg.gate_mode == "stock":
            if t in rebalance_set:
                target = select_on_date(scores, t_prev, cfg.min_score, cfg.top_n)
                prev_equity = cash + sum(p["shares"] * last_prices.get(c, p["cost"])
                                         for c, p in positions.items())
                per = prev_equity * cfg.max_exposure / len(target) if len(target) else 0
                budgets = {c: per for c in target.index}
                for code in list(positions):
                    sell(code, ctx, t, t_prev, "rebalance")
                trades.append({"date": str(t.date()), "decision_date": str(t_prev.date()),
                               "action": "rebalance", "target": list(target.index)})
            for code in list(positions):
                if code not in budgets or not stock_on.loc[t_prev, code]:
                    sell(code, ctx, t, t_prev, "stock_gate_close")
            for code, budget in budgets.items():
                if code not in positions and stock_on.loc[t_prev, code]:
                    buy(code, budget, ctx, t, t_prev, "stock_gate_open")
        else:
            if not on and positions:
                for code in list(positions):
                    sell(code, ctx, t, t_prev, "index_gate_close")
                trades.append({"date": str(t.date()), "decision_date": str(t_prev.date()),
                               "action": "timing_close", "note": f"Index MA{cfg.gate_ma} gate closed"})
            elif on and positions and cfg.use_stock_risk:
                for code, pos in list(positions.items()):
                    px = known.get(code, np.nan)
                    if not np.isfinite(px) or px <= 0:
                        continue
                    pnl = px / pos["cost"] - 1
                    reason = None
                    if pnl <= -cfg.stop_loss:
                        reason = "stop_loss"
                    elif pos["peak"] >= pos["cost"] * (1 + cfg.take_profit) \
                            and px <= pos["peak"] * (1 - cfg.take_profit_drawdown):
                        reason = "trailing_profit"
                    if reason and sell(code, ctx, t, t_prev, reason):
                        trades.append({"date": str(t.date()), "action": "sell", "code": code,
                                       "note": reason})
            should_build = on and (t in rebalance_set or (not gate_prev_on and not positions))
            if should_build:
                target = select_on_date(scores, t_prev, cfg.min_score, cfg.top_n)
                for code in list(positions):
                    sell(code, ctx, t, t_prev, "rebalance")
                exp = cfg.max_exposure
                if exposure is not None and pd.notna(exposure.loc[t_prev]):
                    exp = float(exposure.loc[t_prev])
                per = cash * exp / len(target) if len(target) else 0
                for code in target.index:
                    if code not in positions:
                        buy(code, per, ctx, t, t_prev, "rebalance")
                trades.append({"date": str(t.date()), "decision_date": str(t_prev.date()),
                               "action": "rebalance", "target": list(target.index),
                               "positions": {c: p["shares"] for c, p in positions.items()},
                               "cash": round(cash, 2)})
            gate_prev_on = on

        mv = cash
        for code, pos in positions.items():
            px = close_df.loc[t, code]
            if np.isfinite(px) and px > 0:
                last_prices[code] = float(px)
                pos["peak"] = max(pos["peak"], float(px))
            mv += pos["shares"] * last_prices.get(code, pos["cost"])
        equity_curve[t] = mv
        cash_curve[t] = cash
        holdings_rows[t] = {c: p["shares"] for c, p in positions.items()}

    eq = pd.Series(equity_curve).sort_index()
    holdings = pd.DataFrame.from_dict(holdings_rows, orient="index").reindex(eq.index).fillna(0).astype(int)
    cash_series = pd.Series(cash_curve).reindex(eq.index)
    # Include the initial capital: first-day costs/return must not disappear from metrics.
    metric_curve = pd.concat([pd.Series([cfg.initial_cash], index=[dates[cfg.warmup_days - 1]]), eq])
    metrics = _metrics(metric_curve)
    metrics["annual_return"] = float((eq.iloc[-1] / cfg.initial_cash) ** (252 / len(eq)) - 1)
    metrics["fees"] = sum(f["fee"] for f in fills)
    metrics["turnover"] = sum(f["amount"] for f in fills) / eq.mean()
    metrics["average_exposure"] = float((1 - cash_series / eq).mean())
    metrics["blocked_fills"] = float(sum(blocked.values()))
    metrics["pending_sells"] = float(len(pending_sells))
    return TrendGateResult(cfg, eq, holdings, trades, sorted(rebalance_set.intersection(eq.index)),
                           universe or [], metrics, fills, cash_series,
                           execution={**blocked, "pending_sells": len(pending_sells),
                                      "has_volume": volume_df is not None,
                                      "slippage": cfg.slippage,
                                      "price_limits": bool(cfg.enforce_price_limits),
                                      "halts": bool(cfg.enforce_halts)})
