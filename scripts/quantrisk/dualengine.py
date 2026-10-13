"""双引擎组合（DualEngine，V1.17.0）——趋势引擎 × 震荡引擎 资金分层并行。

**为什么这样组合**

四套策略里 TrendGate（顺势）与 grid（逆向）的市场假设**互为反面**：
- TrendGate：趋势市赚钱、震荡市被闸门反复打脸（空仓率 60.9%）
- grid：震荡市赚钱、单边趋势踏空/套牢（空仓 37.6% 或满仓挨打）

若两者日收益低相关，等权并行就能靠**分散化**同时改善收益与回撤——这是量化里唯一合法的
"免费的午餐"。**不做市场状态预测**（趋势/震荡判别器极易过拟合），而是让两条腿各自
按自己的规则跑、按固定权重并行，把"选哪个引擎"这件事交给市场自己。

**组合实现（纯组合层，不改任何引擎）**

1. 各引擎用**分配到的资金**独立回测，得到日度权益曲线
2. 对齐交易日 → 各腿归一化 → 按权重加权求和 → 组合权益曲线
3. 可选**年度再平衡**：每年首个交易日把两腿市值拉回目标权重
   （`rebalance="annual"`；默认 `none` = 两腿独立复利，权重自然漂移）
4. 指标口径与单引擎一致（复用 `rotation._metrics`）
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .rotation import _metrics


@dataclass
class DualEngineResult:
    equity_curve: pd.Series
    weights: dict[str, float]
    legs: dict[str, pd.Series]
    metrics: dict[str, float]
    rebalance: str = "none"


def combine_equity(legs: dict[str, pd.Series], weights: dict[str, float],
                   initial_cash: float = 1_000_000.0,
                   rebalance: str = "none") -> DualEngineResult:
    """把多条单引擎权益曲线按权重组合成一条组合曲线。

    legs:    {引擎名: 日度权益曲线}（各自用"分配资金"跑出的曲线，index=日期）
    weights: {引擎名: 权重}，和应为 1；缺省腿权重按 0 处理
    rebalance: "none"（独立复利，权重漂移）| "annual"（每年初拉回目标权重）
    """
    names = [n for n in legs if n in weights and weights[n] > 0]
    if not names:
        raise ValueError("没有有效权重")
    idx = None
    for n in names:
        s = legs[n].dropna()
        idx = s.index if idx is None else idx.intersection(s.index)
    idx = idx.sort_values()
    if len(idx) < 2:
        raise ValueError("对齐后交易日不足")

    w = np.array([weights[n] for n in names], dtype=float)
    w = w / w.sum()

    curves = {n: legs[n].reindex(idx).ffill().bfill() for n in names}
    # 各腿归一化到分配到的资金
    norm = {n: curves[n] / curves[n].iloc[0] * (initial_cash * w[i]) for i, n in enumerate(names)}

    if rebalance == "annual":
        equity = {}
        leg_val = {n: initial_cash * w[i] for i, n in enumerate(names)}
        prev_date = idx[0]
        for d in idx:
            for i, n in enumerate(names):
                r = curves[n].loc[d] / curves[n].loc[prev_date] if prev_date != d else 1.0
                leg_val[n] *= r
            total = sum(leg_val.values())
            # 年度再平衡：跨年首个交易日拉回目标权重
            if d.year != prev_date.year:
                for i, n in enumerate(names):
                    leg_val[n] = total * w[i]
            equity[d] = total
            prev_date = d
        eq = pd.Series(equity).sort_index()
    else:
        eq = sum(norm[n] for n in names).sort_index()

    res = DualEngineResult(equity_curve=eq, weights={n: float(w[i]) for i, n in enumerate(names)},
                           legs={n: norm[n] for n in names}, metrics=_metrics(eq),
                           rebalance=rebalance)
    return res


def leg_correlation(legs: dict[str, pd.Series]) -> float:
    """两腿日收益相关性（越低 → 分散化收益越大）。"""
    names = list(legs)
    if len(names) < 2:
        return float("nan")
    df = pd.DataFrame({n: legs[n] for n in names}).dropna()
    if len(df) < 3:
        return float("nan")
    return float(df.pct_change().dropna().corr().iloc[0, 1])


def weight_sweep(legs: dict[str, pd.Series], weights_grid: list[float],
                 initial_cash: float = 1_000_000.0,
                 rebalance: str = "none", first_name: str | None = None) -> list[dict]:
    """扫描第一条腿的权重（如 TrendGate 占比），返回每档的组合指标。"""
    names = list(legs)
    a = first_name or names[0]
    b = names[1]
    out = []
    for w in weights_grid:
        r = combine_equity(legs, {a: w, b: 1 - w}, initial_cash, rebalance)
        m = r.metrics
        out.append({
            "w_first": w, "total_return": m.get("total_return", 0.0),
            "annual_return": m.get("annual_return", 0.0),
            "max_drawdown": m.get("max_drawdown", 0.0),
            "sharpe": m.get("sharpe", 0.0),
            "calmar": (m.get("annual_return", 0.0) / abs(m.get("max_drawdown", 0.0))
                       if m.get("max_drawdown", 0.0) < 0 else float("nan")),
        })
    return out


def yearly(eq: pd.Series) -> dict[int, float]:
    return {int(y): float(g.iloc[-1] / g.iloc[0] - 1) for y, g in eq.groupby(eq.index.year) if len(g) > 1}