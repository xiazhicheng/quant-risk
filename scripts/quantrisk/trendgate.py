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
    use_ma20_timing: bool = True
    gate_ma: int = 20
    gate_confirm_days: int = 3
    max_exposure: float = 0.7
    target_vol: float | None = None
    use_stock_risk: bool = False
    stop_loss: float = STOP_LOSS
    take_profit: float = TAKE_PROFIT
    take_profit_drawdown: float = TAKE_PROFIT_DRAWDOWN
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


def run_trendgate_backtest(close_df: pd.DataFrame, open_df: pd.DataFrame,
                           gate_index: pd.Series | None,
                           config: TrendGateConfig | None = None,
                           universe: list[dict] | None = None,
                           scores_override: pd.DataFrame | None = None) -> TrendGateResult:
    """Same ranking, schedule, costs and execution for both gate modes.

    Stock mode: freeze top-N and equal sleeve budgets at each scheduled rebalance.
    A closed sleeve stays in cash; reopen within that basket at its original budget,
    capped by available cash. No substitution and no index gate in stock mode.
    Missing signals fail closed; missing execution prices defer the trade.
    """
    cfg = config or TrendGateConfig()
    if cfg.gate_mode not in {"index", "stock"}:
        raise ValueError("gate_mode must be index or stock")
    if min(cfg.gate_ma, cfg.gate_confirm_days, cfg.top_n, cfg.rebalance_days,
           cfg.warmup_days, cfg.lot_size) < 1 or cfg.initial_cash <= 0 \
            or not 0 <= cfg.max_exposure <= 1 or not 0 <= cfg.commission_rate < 1:
        raise ValueError("Invalid gate, capital, exposure or cost parameters")
    if cfg.gate_mode == "stock" and (cfg.target_vol or cfg.use_stock_risk):
        raise ValueError("Stock gate comparison does not use index volatility or fixed stock stops")
    close_df = close_df.astype(float).sort_index()
    open_df = open_df.astype(float).reindex(index=close_df.index, columns=close_df.columns)
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

    def sell(code, row, t, t_prev, reason):
        nonlocal cash
        px = row.get(code, np.nan)
        if not np.isfinite(px) or px <= 0:
            return False
        shares = positions[code]["shares"]
        amount = shares * float(px)
        fee = amount * cfg.commission_rate
        cash += amount - fee
        positions.pop(code)
        fills.append({"date": str(t.date()), "decision_date": str(t_prev.date()),
                      "code": code, "side": "sell", "shares": shares, "price": float(px),
                      "amount": amount, "fee": fee, "reason": reason})
        return True

    def buy(code, budget, row, t, t_prev, reason):
        nonlocal cash
        px = row.get(code, np.nan)
        if not np.isfinite(px) or px <= 0:
            return
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
        on = bool(index_on.loc[t_prev])

        if cfg.gate_mode == "stock":
            if t in rebalance_set:
                target = select_on_date(scores, t_prev, cfg.min_score, cfg.top_n)
                prev_equity = cash + sum(p["shares"] * last_prices.get(c, p["cost"])
                                         for c, p in positions.items())
                per = prev_equity * cfg.max_exposure / len(target) if len(target) else 0
                budgets = {c: per for c in target.index}
                for code in list(positions):
                    sell(code, open_row, t, t_prev, "rebalance")
                trades.append({"date": str(t.date()), "decision_date": str(t_prev.date()),
                               "action": "rebalance", "target": list(target.index)})
            for code in list(positions):
                if code not in budgets or not stock_on.loc[t_prev, code]:
                    sell(code, open_row, t, t_prev, "stock_gate_close")
            for code, budget in budgets.items():
                if code not in positions and stock_on.loc[t_prev, code]:
                    buy(code, budget, open_row, t, t_prev, "stock_gate_open")
        else:
            if not on and positions:
                for code in list(positions):
                    sell(code, open_row, t, t_prev, "index_gate_close")
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
                    if reason and sell(code, open_row, t, t_prev, reason):
                        trades.append({"date": str(t.date()), "action": "sell", "code": code,
                                       "note": reason})
            should_build = on and (t in rebalance_set or (not gate_prev_on and not positions))
            if should_build:
                target = select_on_date(scores, t_prev, cfg.min_score, cfg.top_n)
                for code in list(positions):
                    sell(code, open_row, t, t_prev, "rebalance")
                exp = cfg.max_exposure
                if exposure is not None and pd.notna(exposure.loc[t_prev]):
                    exp = float(exposure.loc[t_prev])
                per = cash * exp / len(target) if len(target) else 0
                for code in target.index:
                    if code not in positions:
                        buy(code, per, open_row, t, t_prev, "rebalance")
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
    return TrendGateResult(cfg, eq, holdings, trades, sorted(rebalance_set.intersection(eq.index)),
                           universe or [], metrics, fills, cash_series)
