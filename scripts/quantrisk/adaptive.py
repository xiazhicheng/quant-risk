"""自适应策略切换（Adaptive，V1.19.0）——先判断震荡/趋势，再切换网格/趋势子策略。

**用户设想**：先判定股票是震荡型还是趋势型 → 分别用网格 / 趋势门控。

**两个必须先解决的硬伤**

1. **趋势门控不能直接套单股**：TrendGate 是组合策略（需 500 只池子横截面排名选前 10），
   单股版只能降级为「单股趋势跟随」——即 TrendGate 的闸门逻辑（价格/指数 MA 开关）用于单标的。
2. **⚠️ 类型判定必须是「滚动」的**：`fit.py` 的 IR/ER 用**全区间**数据计算，是站在终点回看，
   拿它选策略就是前视偏差。可执行的形式只能是：**每个判定日只用截至当时的数据算 IR**，
   判定当前状态，再切换子策略。状态判定天然滞后——这正是本模块要检验的东西。

**三层验证（本模块提供）**

1. `rolling_regime()`：滚动判定（无前视，只用 ≤ 判定日的数据）
2. `regime_predictive_power()`：判定有没有预测力——判定为"趋势"后，随后一段的 |IR| 是否真的更高？
3. `adaptive_backtest()`：自适应切换 vs 单一子策略的收益对比（收益拼接 + 显式切换摩擦）
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class AdaptiveConfig:
    lookback: int = 120          # 判定窗口（用过去 N 日算 IR）
    step: int = 20               # 判定频率（每 N 日重新判一次）
    ir_choppy: float = 0.25      # |IR| ≤ 此值 → 震荡（网格）
    ir_trend: float = 0.50       # |IR| ≥ 此值 → 趋势（趋势跟随）
    grid_spacing: float = 0.02   # 网格间距
    trend_ma: int = 20           # 趋势子策略均线
    exposure: float = 0.70       # 趋势子策略敞口
    switch_cost: float = 0.003   # 每次切换的摩擦成本（双边 0.3%）
    commission: float = 0.001
    initial_cash: float = 1_000_000.0
    lot_size: int = 100


@dataclass
class AdaptiveResult:
    equity_curve: pd.Series
    regimes: pd.Series
    segments: list[dict] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    n_switches: int = 0
    legs: dict = field(default_factory=dict)


def rolling_regime(close: pd.Series, cfg: AdaptiveConfig) -> pd.Series:
    """滚动判定走势类型（无前视）：每个判定日只用**截至该日**的 lookback 日数据算 |IR|。

    返回 Series(index=判定日, value="choppy"/"trend"/"carry")，carry = 落在滞后带内维持前值。
    带滞后带（hysteresis）是为了避免在阈值附近反复横跳。
    """
    c = close.dropna()
    idx = list(c.index)
    out = {}
    prev = None
    for i in range(cfg.lookback, len(idx), cfg.step):
        win = c.iloc[i - cfg.lookback:i + 1]           # 只用截至当日的窗口
        ret = win.pct_change().dropna()
        if len(ret) < 30:
            continue
        ann_vol = float(ret.std() * np.sqrt(252))
        period = float(win.iloc[-1] / win.iloc[0] - 1)
        ann_ret = (1 + period) ** (252 / max(len(win), 1)) - 1
        ir = abs(ann_ret / ann_vol) if ann_vol > 0 else 0.0
        if ir <= cfg.ir_choppy:
            state = "choppy"
        elif ir >= cfg.ir_trend:
            state = "trend"
        else:
            state = prev or "choppy"                      # 滞后带：维持前值
        out[idx[i]] = state
        prev = state
    return pd.Series(out).sort_index()


def regime_predictive_power(close: pd.Series, cfg: AdaptiveConfig,
                            horizon: int = 20) -> dict:
    """判定有没有预测力：判定为 trend 后的随后 horizon 日 |IR|，vs 判定为 choppy 后。

    若"判定 trend → 未来 |IR| 更高"不明显，则"先判定再切换"缺乏依据。
    """
    reg = rolling_regime(close, cfg)
    c = close.dropna()
    idx = list(c.index)
    pos = {d: i for i, d in enumerate(idx)}
    rows = []
    for d, state in reg.items():
        i = pos[d]
        fwd = c.iloc[i:min(i + horizon + 1, len(idx))]
        if len(fwd) < 5:
            continue
        r = fwd.pct_change().dropna()
        av = float(r.std() * np.sqrt(252))
        pr = float(fwd.iloc[-1] / fwd.iloc[0] - 1)
        ar = (1 + pr) ** (252 / max(len(fwd), 1)) - 1
        rows.append({"date": d, "state": state,
                     "fwd_ir": abs(ar / av) if av > 0 else 0.0,
                     "fwd_ret": pr})
    if not rows:
        return {}
    df = pd.DataFrame(rows)
    t = df[df["state"] == "trend"]
    h = df[df["state"] == "choppy"]
    return {
        "n_trend": len(t), "n_choppy": len(h),
        "trend_fwd_ir": float(t["fwd_ir"].mean()) if len(t) else float("nan"),
        "choppy_fwd_ir": float(h["fwd_ir"].mean()) if len(h) else float("nan"),
        "trend_fwd_ret": float(t["fwd_ret"].mean()) if len(t) else float("nan"),
        "choppy_fwd_ret": float(h["fwd_ret"].mean()) if len(h) else float("nan"),
        "hit_rate": float((t["fwd_ir"] > h["fwd_ir"].mean()).mean()) if len(t) and len(h) else float("nan"),
    }


def _grid_daily_returns(klines: pd.DataFrame, cfg: AdaptiveConfig) -> pd.Series:
    """网格子策略的日收益（满额资金）。"""
    from . import grid
    gc = grid.GridConfig(spacing=cfg.grid_spacing, lower=0.20, upper=0.20,
                         commission_rate=cfg.commission, lot_size=cfg.lot_size)
    r = grid.run_grid_backtest(klines, gc)
    return r.equity_curve.pct_change().fillna(0.0)


def _trend_daily_returns(klines: pd.DataFrame, cfg: AdaptiveConfig) -> pd.Series:
    """单股趋势跟随子策略日收益：t-1 收盘价 > MA(t-1) → t 日持有（满敞口/杠杆=1）。

    这是 TrendGate 闸门逻辑的单股降级版（去掉池内选股）。
    """
    close, open_ = klines["close"].astype(float), klines["open"].astype(float)
    ma = close.rolling(cfg.trend_ma).mean()
    hold = (close.shift(1) > ma.shift(1)).astype(float)      # t-1 判定 → t 持有
    # 按开盘成交、收盘计市值
    ret = close.pct_change().fillna(0.0)
    pos_ret = hold * ret
    tc = hold.diff().abs().fillna(0.0) * cfg.commission      # 每次进出成本
    return (pos_ret - tc).fillna(0.0)


def adaptive_backtest(klines: pd.DataFrame, cfg: AdaptiveConfig | None = None) -> AdaptiveResult:
    """自适应切换回测：按滚动判定的状态，在网格/趋势子策略之间切换日收益。

    实现为**收益拼接**（切换日按新子策略的日收益计），并每次切换扣 `switch_cost` 摩擦。
    这是近似（真实切换还涉及两策略仓位状态不同），已在文档中标注为估计口径。
    """
    cfg = cfg or AdaptiveConfig()
    df = klines.sort_index()
    close = df["close"].astype(float)
    reg = rolling_regime(close, cfg)
    if reg.empty:
        raise ValueError("判定为空：数据不足以覆盖 lookback")

    g_ret = _grid_daily_returns(df, cfg)
    t_ret = _trend_daily_returns(df, cfg)

    # 把判定状态前向填充到每个交易日（判定日之后沿用，直到下次判定）
    state_daily = pd.Series(index=close.index, dtype=object)
    cur = None
    j = 0
    reg_dates = list(reg.index)
    for d in close.index:
        while j < len(reg_dates) and reg_dates[j] <= d:
            cur = reg.loc[reg_dates[j]]
            j += 1
        state_daily.loc[d] = cur
    state_daily = state_daily.ffill().fillna("choppy")

    strat_ret = pd.Series(0.0, index=close.index)
    switches = 0
    prev_state = None
    for d in close.index:
        s = state_daily.loc[d]
        if s != prev_state and prev_state is not None:
            switches += 1
            strat_ret.loc[d] = (g_ret.loc[d] if s == "choppy" else t_ret.loc[d]) - cfg.switch_cost
        else:
            strat_ret.loc[d] = g_ret.loc[d] if s == "choppy" else t_ret.loc[d]
        prev_state = s

    eq = cfg.initial_cash * (1 + strat_ret).cumprod()
    from .rotation import _metrics
    res = AdaptiveResult(
        equity_curve=eq, regimes=state_daily, metrics=_metrics(eq),
        n_switches=switches,
        legs={"grid_only": cfg.initial_cash * (1 + g_ret).cumprod(),
              "trend_only": cfg.initial_cash * (1 + t_ret).cumprod()},
    )
    res.metrics["n_switches"] = float(switches)
    res.metrics["choppy_days_ratio"] = float((state_daily == "choppy").mean())
    return res