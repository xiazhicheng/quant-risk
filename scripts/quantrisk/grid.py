"""网格交易策略（Grid Trading，V1.16.0）——与 rotation/multifactor/TrendGate 哲学相反。

**网格 vs 趋势策略的本质差异**

| | 网格 | TrendGate 等趋势策略 |
|:--|:--|:--|
| 买卖方向 | 逆向：跌了买、涨了卖 | 顺势：涨得强才买 |
| 触发 | 价格触及网格档位 | 时间（每 20 交易日） |
| 赚钱行情 | **震荡市**（来回波动赚差价） | **趋势市**（单边拿住） |
| 怕的行情 | 单边趋势（涨则卖光踏空、跌则买满套牢） | 震荡市（闸门反复开关） |

**实现选择（2026-10-09）**

- 标的：宽基 ETF（默认中证500ETF 510500）——网格怕个股暴雷/退市，ETF 无此风险且免印花税
- 网格：**等比网格**（每档固定百分比间距，适应不同价位），区间 `[P0·(1-lower), P0·(1+upper)]`
- 档位：`n_grids` 格，每格资金 = 现金池 / n_grids（等额），份额按 100 份取整
- 初始仓位：`init_position`（默认 0.5，即半仓起步，上下预留对称空间）
- 逐日撮合：用当日 **low/high 判断穿越的档位**；同日多档按保守顺序处理（`open→low→high→close`，
  即"先跌后涨"= 先买后卖，对收益偏保守）；`--optimistic` 可切到 `open→high→low→close` 给收益上界
- **网格不移位**（固定价位），跌破下界则满仓持有、涨破上界则清仓观望（网格的天然缺陷，如实展示）
- 交易成本：默认单边 0.02%（ETF 免印花税，佣金双边），网格高频交易对费用极敏感 → 必须做敏感性

**回测无前瞻**：所有判定用当日已实现的 low/high（盘中挂单触发，非未来数据）；
档位价格由**前一交易日收盘**决定锚点 P0（首个交易日开盘价为 P0），不偷看当日收盘。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .rotation import _metrics


@dataclass
class GridConfig:
    n_grids: int = 20               # 网格档位数（每档一注）
    spacing: float = 0.015          # 每档间距（等比，1.5%）
    lower: float = 0.15             # 下界 = P0*(1-lower)
    upper: float = 0.15             # 上界 = P0*(1+upper)
    init_position: float = 0.5      # 初始仓位比例（0.5=半仓）
    lot_size: int = 100             # ETF 最小 100 份
    initial_cash: float = 1_000_000.0
    commission_rate: float = 0.0002  # 单边费率（ETF 免印花税）
    breakout_action: str = "hold"   # 跌破下界：hold=满仓持有 / stop=清仓止损
    optimistic: bool = False        # 同日顺序：False=先跌后涨（保守）/ True=先涨后跌（乐观）
    name: str = "grid"


@dataclass
class GridResult:
    config: GridConfig
    equity_curve: pd.Series
    trades: list[dict]
    metrics: dict[str, float] = field(default_factory=dict)
    filled_ratio: pd.Series | None = None      # 逐日仓位占比
    n_buy: int = 0
    n_sell: int = 0
    full_days: int = 0                          # 满仓天数（跌穿下界后）
    empty_days: int = 0                         # 清仓天数（涨穿上界后）


def grid_levels(p0: float, cfg: GridConfig) -> list[float]:
    """由**间距 spacing** 驱动生成的等比网格价位（升序，末档=上界）。

    间距是网格的核心参数（"每格 1%"），档数由区间跨度派生：
    n = round(ln(上界/下界)/ln(1+spacing)) + 1，再等比均分使末档正好落在上界
    （2026-10-09 修正：早期版本"补上界"会造出间距畸变的尾档，
    引发同日反复买卖抖动 + 份额分配不整除）。
    """
    lo, hi = p0 * (1 - cfg.lower), p0 * (1 + cfg.upper)
    if lo <= 0 or hi <= lo or cfg.spacing <= 0:
        return [lo, hi]
    step = 1 + cfg.spacing
    n = int(round(np.log(hi / lo) / np.log(step))) + 1
    n = min(max(n, 2), max(cfg.n_grids, 2) * 10)
    ratio = (hi / lo) ** (1 / (n - 1))
    return [lo * ratio ** i for i in range(n)]


def run_grid_backtest(klines: pd.DataFrame, config: GridConfig | None = None) -> GridResult:
    """网格回测。

    klines 需含 open/high/low/close，index=日期（升序）。
    逻辑：以首个交易日开盘价为锚点 P0 生成固定网格；初始建`init_position`仓位，
    其余现金按 `n_grids` 等分作为每格买入侵额。逐日按 low/high 穿越档位成交。
    """
    cfg = config or GridConfig()
    df = klines.sort_index()
    if len(df) < 2:
        raise ValueError("K 线不足")

    p0 = float(df["open"].iloc[0])
    levels = grid_levels(p0, cfg)
    n = len(levels)
    invest_cash = cfg.initial_cash * cfg.init_position
    cash = cfg.initial_cash - invest_cash
    # 当前所处档位（按首日开盘价定位）；其下方格数 = 可买入次数 → 据此等分现金
    def locate(px: float) -> int:
        for i in range(n - 1, -1, -1):
            if px >= levels[i]:
                return i
        return 0

    lvl0 = locate(p0)
    n_up = (n - 1) - lvl0          # 上方可卖档数
    n_down = lvl0                   # 下方可买档数
    # 上下各自自洽的预算分配（否则涨穿上界卖不光 / 跌穿下界买不满）：
    #   每格卖出份额 = 初始持仓 ÷ 上方档数 → 涨到上界刚好卖光
    #   每格买入侵额 = 现金池 ÷ 下方档数   → 跌到下界刚好买满
    per_grid = cash / n_down if n_down > 0 else 0.0
    shares = int(invest_cash / p0 // cfg.lot_size) * cfg.lot_size
    cash += invest_cash - shares * p0 * (1 + cfg.commission_rate)
    qty_per_grid = int(shares / n_up // cfg.lot_size) * cfg.lot_size if n_up > 0 else 0

    lvl = lvl0
    equity_curve, filled = {}, {}
    trades: list[dict] = []
    n_buy = n_sell = full_days = empty_days = 0

    for d, row in df.iterrows():
        o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
        seq = [o, h, l, c] if cfg.optimistic else [o, l, h, c]

        for px in seq:
            # 向下穿越：逐格买入（每格 per_grid 元）
            while lvl > 0 and px <= levels[lvl - 1]:
                budget = per_grid
                can = int(budget / (levels[lvl - 1] * (1 + cfg.commission_rate)) // cfg.lot_size) * cfg.lot_size
                if can > 0 and can * levels[lvl - 1] * (1 + cfg.commission_rate) <= cash:
                    cost = can * levels[lvl - 1] * (1 + cfg.commission_rate)
                    cash -= cost
                    shares += can
                    lvl -= 1
                    n_buy += 1
                    trades.append({"date": str(pd.Timestamp(d).date()), "side": "buy",
                                   "price": levels[lvl + 1], "qty": can, "level": lvl})
                else:
                    lvl -= 1                      # 资金不足也下移档位（避免死循环）
            # 向上穿越：逐格卖出；**最高档清掉全部剩余份额**（避免取整零头永远卖不掉）
            while lvl < n - 1 and px >= levels[lvl + 1]:
                px_sell = levels[lvl + 1]
                qty = shares if lvl + 1 == n - 1 else min(qty_per_grid, shares)
                if qty > 0:
                    cash += qty * px_sell * (1 - cfg.commission_rate)
                    shares -= qty
                    lvl += 1
                    n_sell += 1
                    trades.append({"date": str(pd.Timestamp(d).date()), "side": "sell",
                                   "price": px_sell, "qty": qty, "level": lvl})
                else:
                    lvl += 1

        # 跌破下界处置
        if cfg.breakout_action == "stop" and c < levels[0] and shares > 0:
            cash += shares * c * (1 - cfg.commission_rate)
            trades.append({"date": str(pd.Timestamp(d).date()), "side": "sell",
                           "price": c, "qty": shares, "level": -1, "note": "跌破下界止损"})
            shares = 0
            lvl = 0
            n_sell += 1

        mv = cash + shares * c
        equity_curve[d] = mv
        filled[d] = (shares * c) / mv if mv > 0 else 0.0
        if lvl == 0:
            full_days += 1
        if shares == 0:
            empty_days += 1

    eq = pd.Series(equity_curve).sort_index()
    res = GridResult(
        config=cfg, equity_curve=eq, trades=trades,
        filled_ratio=pd.Series(filled),
        n_buy=n_buy, n_sell=n_sell, full_days=full_days, empty_days=empty_days,
    )
    res.metrics = _metrics(eq)
    # 补充网格专属指标
    res.metrics["n_trades"] = float(n_buy + n_sell)
    res.metrics["avg_exposure"] = float(pd.Series(filled).mean())
    res.metrics["full_days_ratio"] = full_days / len(df)
    res.metrics["empty_days_ratio"] = empty_days / len(df)
    return res


def buy_hold(klines: pd.DataFrame, cfg: GridConfig | None = None) -> pd.Series:
    """同区间 buy&hold 基准（首日开盘价全额买入，含单边费用）。"""
    cfg = config_default = cfg or GridConfig()
    df = klines.sort_index()
    p0 = float(df["open"].iloc[0])
    shares = int(cfg.initial_cash / (p0 * (1 + cfg.commission_rate)) // cfg.lot_size) * cfg.lot_size
    cash = cfg.initial_cash - shares * p0 * (1 + cfg.commission_rate)
    return (cash + shares * df["close"]).rename("buy_hold")


def grid_metrics_vs_bh(grid_res: GridResult, bh: pd.Series) -> dict:
    """网格 vs buy&hold 对照指标。"""
    g = grid_res.metrics
    b = _metrics(bh)
    return {
        "grid_return": g.get("total_return", 0.0),
        "bh_return": b.get("total_return", 0.0),
        "excess": g.get("total_return", 0.0) - b.get("total_return", 0.0),
        "grid_mdd": g.get("max_drawdown", 0.0),
        "bh_mdd": b.get("max_drawdown", 0.0),
        "grid_sharpe": g.get("sharpe", 0.0),
        "bh_sharpe": b.get("sharpe", 0.0),
        "avg_exposure": g.get("avg_exposure", 0.0),
        "n_trades": g.get("n_trades", 0.0),
    }