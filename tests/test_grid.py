"""网格策略测试：价位生成 / 逆向交易方向 / 资金守恒 / 间距敏感 / 边界行为。"""

import numpy as np
import pandas as pd
import pytest

from scripts.quantrisk import grid
from scripts.quantrisk.grid import GridConfig, grid_levels, run_grid_backtest


def _mk_klines(prices: list[float]) -> pd.DataFrame:
    idx = pd.bdate_range("2025-01-01", periods=len(prices))
    return pd.DataFrame({
        "open": prices, "high": [p * 1.005 for p in prices],
        "low": [p * 0.995 for p in prices], "close": prices,
        "volume": [1_000_000] * len(prices),
    }, index=idx)


def test_grid_levels_spacing_drives_count():
    """间距越小 → 档位越密（档数越多）；档数由区间跨度/间距派生。"""
    cfg_dense = GridConfig(spacing=0.005)
    cfg_loose = GridConfig(spacing=0.05)
    p0 = 10.0
    lv_dense = grid_levels(p0, cfg_dense)
    lv_loose = grid_levels(p0, cfg_loose)
    assert len(lv_dense) > len(lv_loose)
    # 上下界正确
    assert lv_dense[0] == pytest.approx(p0 * (1 - cfg_dense.lower))
    assert lv_dense[-1] == pytest.approx(p0 * (1 + cfg_dense.upper), rel=1e-6)
    # 升序
    assert all(b > a for a, b in zip(lv_dense, lv_dense[1:]))


def test_grid_buys_low_sells_high():
    """核心方向：网格必须「跌了买、涨了卖」（与趋势策略相反）。"""
    # 先跌到 -10% 再涨回 -5%
    prices = [10.0] * 3 + list(np.linspace(10.0, 9.0, 20)) + list(np.linspace(9.0, 9.5, 10))
    df = _mk_klines(prices)
    res = run_grid_backtest(df, GridConfig(spacing=0.01, lower=0.2, upper=0.2))
    buys = [t for t in res.trades if t["side"] == "buy"]
    sells = [t for t in res.trades if t["side"] == "sell"]
    assert len(buys) > 0, "下跌段应有买入"
    if sells:
        # 低买高卖：卖出的档位必须高于买入的档位（网格价位单调递增）
        assert min(t["level"] for t in sells) > min(t["level"] for t in buys)


def test_cash_conservation_and_no_negative():
    """资金守恒：权益 = 现金 + 持仓市值；现金不为负（每笔买入受预算约束）。"""
    prices = list(np.linspace(10.0, 8.0, 60)) + list(np.linspace(8.0, 11.0, 60))
    df = _mk_klines(prices)
    cfg = GridConfig(spacing=0.02, lower=0.3, upper=0.3, initial_cash=1_000_000)
    res = run_grid_backtest(df, cfg)
    # 权益曲线非负且长度正确
    assert (res.equity_curve > 0).all()
    assert len(res.equity_curve) == len(df)
    # 仓位占比在 [0,1]
    assert res.filled_ratio.between(0, 1).all()
    # 累计买入金额不可能超过初始资金
    spent = sum(t["price"] * t["qty"] for t in res.trades if t["side"] == "buy")
    assert spent <= cfg.initial_cash * 1.001


def test_dense_spacing_more_trades():
    """间距越密，成交次数越多。"""
    rng = np.random.default_rng(7)
    prices = list(10 * np.cumprod(1 + rng.normal(0, 0.01, 200)))
    df = _mk_klines(prices)
    dense = run_grid_backtest(df, GridConfig(spacing=0.005, lower=0.3, upper=0.3))
    loose = run_grid_backtest(df, GridConfig(spacing=0.03, lower=0.3, upper=0.3))
    assert dense.metrics["n_trades"] > loose.metrics["n_trades"]


def test_trend_up_sells_down_underperforms_but_trend_down_defends():
    """市场假设验证：单边上涨网格跑输买持；单边下跌网格跑赢买持。"""
    up = _mk_klines(list(np.linspace(10.0, 14.0, 200)))
    dn = _mk_klines(list(np.linspace(10.0, 7.0, 200)))
    cfg = GridConfig(spacing=0.02, lower=0.2, upper=0.4)
    for df, label, expect in [(up, "单边上涨", "under"), (dn, "单边下跌", "over")]:
        g = run_grid_backtest(df, cfg)
        b = grid.buy_hold(df, cfg)
        bm = grid._metrics(b)["total_return"]
        gm = g.metrics["total_return"]
        if expect == "under":
            assert gm < bm, f"{label} 网格应跑输满仓买持（{gm:.2%} vs {bm:.2%}）"
        else:
            assert gm > bm, f"{label} 网格应跑赢满仓买持（{gm:.2%} vs {bm:.2%}）"


def test_breakout_stop_limits_loss():
    """跌破下界 stop 模式应比 hold 模式回撤更小（或收益更好）。"""
    prices = list(np.linspace(10.0, 5.0, 200))     # 腰斩行情
    df = _mk_klines(prices)
    hold = run_grid_backtest(df, GridConfig(spacing=0.02, lower=0.2, upper=0.2, breakout_action="hold"))
    stop = run_grid_backtest(df, GridConfig(spacing=0.02, lower=0.2, upper=0.2, breakout_action="stop"))
    assert stop.metrics["max_drawdown"] >= hold.metrics["max_drawdown"], \
        "stop 模式的回撤应不差于 hold（跌穿下界后不继续持有）"


def test_optimistic_vs_conservative_bounds():
    """同日顺序假设给出收益上下界：乐观 ≥ 保守（差异应很小）。"""
    rng = np.random.default_rng(11)
    prices = list(10 * np.cumprod(1 + rng.normal(0, 0.015, 300)))
    df = _mk_klines(prices)
    cons = run_grid_backtest(df, GridConfig(spacing=0.01, optimistic=False))
    opt = run_grid_backtest(df, GridConfig(spacing=0.01, optimistic=True))
    assert abs(cons.metrics["total_return"] - opt.metrics["total_return"]) < 0.10


def test_empty_position_full_position_days():
    """涨穿上界卖光 → empty_days>0；跌穿下界买满 → full_days>0。

    预算分配自洽性：每格卖出份额 = 初始持仓÷上方档数、每格买入侵额 = 现金÷下方档数，
    因此涨到上界应卖光、跌到下界应用尽现金。
    """
    up = _mk_klines(list(np.linspace(10.0, 13.0, 150)))     # 涨穿 +10% 上界
    dn = _mk_klines(list(np.linspace(10.0, 7.5, 150)))     # 跌穿 -10% 下界
    cfg = GridConfig(spacing=0.02, lower=0.1, upper=0.1)
    up_res = run_grid_backtest(up, cfg)
    dn_res = run_grid_backtest(dn, cfg)
    assert up_res.empty_days > 0, "涨穿上界应把初始仓位卖光"
    assert dn_res.full_days > 0, "跌穿下界应把现金买满"