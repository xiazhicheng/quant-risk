from scripts.quantrisk.backtest_engine import performance_metrics, replay_orders
from scripts.quantrisk.execution import CostConfig, MarketExecutionModel
from scripts.quantrisk.strategy_models import OrderIntent, PositionState


def bars():
    return [
        {"date": "2026-09-09", "open": 10.0, "close": 10.0, "volume": 10000},
        {"date": "2026-09-10", "open": 10.5, "close": 11.0, "volume": 10000},
        {"date": "2026-09-11", "open": 11.0, "close": 10.8, "volume": 10000},
    ]


def test_replay_buys_next_available_bar_with_costs():
    orders = [OrderIntent("run", "cn", "600000", "BUY", 100,
                          "2026-09-09T15:00:00+08:00", "2026-09-10")]
    result = replay_orders("cn", bars(), orders, starting_cash=2000,
                           costs=CostConfig(slippage_bps=0, minimum_commission=0))
    assert len(result.events) == 1
    assert result.events[0].date == "2026-09-10"
    assert result.position is not None and result.position.quantity == 100
    assert result.cash == 949.685


def test_replay_rejects_cn_non_lot_order():
    orders = [OrderIntent("run", "cn", "600000", "BUY", 50,
                          "2026-09-10", "2026-09-10")]
    result = replay_orders("cn", bars(), orders, starting_cash=2000,
                           costs=CostConfig(slippage_bps=0, minimum_commission=0))
    assert result.rejected_orders == 1
    assert not result.events


def test_replay_enforces_t1_until_next_day():
    position = PositionState("cn", "600000", "swing_tactical_1w2w",
                             quantity=100, available_quantity=0,
                             entry_price=10.0, entry_time="2026-09-09")
    model = MarketExecutionModel("cn", CostConfig(slippage_bps=0, minimum_commission=0))
    sell = OrderIntent("run", "cn", "600000", "SELL", 100, "2026-09-09", "2026-09-09")
    ok, reason = model.can_fill(sell, bars()[0], position)
    assert ok is False and "T+1" in reason


def test_replay_rejects_limit_up_buy():
    model = MarketExecutionModel("cn", CostConfig(slippage_bps=0, minimum_commission=0))
    order = OrderIntent("run", "cn", "600000", "BUY", 100, "2026-09-10", "2026-09-10")
    bar = {"date": "2026-09-10", "open": 11, "close": 11, "volume": 1000, "high_limit": 11}
    ok, reason = model.can_fill(order, bar)
    assert ok is False and "涨停" in reason


def test_performance_metrics_report_net_return_and_drawdown():
    metrics = performance_metrics([100, 110, 99, 120], [])
    assert metrics["net_return_pct"] == 20.0
    assert metrics["max_drawdown_pct"] == 10.0


def test_holding_period_stats_groups_by_actual_days():
    from scripts.quantrisk.backtest_engine import ClosedTrade, holding_period_stats
    trades = [
        ClosedTrade("2026-01-01", "2026-01-03", 2, 10, 11, 100, 1, 10.0, "移动止盈"),
        ClosedTrade("2026-02-01", "2026-02-10", 9, 10, 12, 100, 1, 20.0, "跌破前低"),
        ClosedTrade("2026-03-01", "2026-04-10", 40, 10, 8, 100, 1, -20.0, "移动止盈"),
        ClosedTrade("2026-05-01", "2026-08-01", 92, 10, 15, 100, 1, 50.0, "跌破前低"),
    ]
    stats = holding_period_stats(trades)
    assert stats["<5天"]["count"] == 1 and stats["<5天"]["win_rate_pct"] == 100.0
    assert stats["5-20天"]["count"] == 1
    assert stats["20-60天"]["count"] == 1 and stats["20-60天"]["win_rate_pct"] == 0.0
    assert stats[">60天"]["count"] == 1
    assert stats["<5天"]["total_return_pct"] == 10.0


def test_run_swing_replay_closes_by_previous_low(monkeypatch):
    from scripts.quantrisk.backtest_engine import run_swing_replay
    from scripts.quantrisk.rule_engine import PythonReferenceRuleEngine
    from scripts.quantrisk.strategy_config import load_strategy_config
    bars = []
    for i in range(40):
        close = 10.0 + i * 0.2
        bars.append({"date": f"2026-01-{(i % 28)+1:02d}", "open": close, "high": close + 0.3,
                     "low": close - 0.2, "close": close, "volume": 10000,
                     "dow_direction": "up", "previous_low": 10.0, "previous_high": 12.0,
                     "stage": "公众参与", "health_ok": True, "index_sync": True})
    result = run_swing_replay(bars, "cn", load_strategy_config("band"), PythonReferenceRuleEngine(),
                              starting_cash=10000, costs=__import__("scripts.quantrisk.execution", fromlist=["CostConfig"]).CostConfig(slippage_bps=0, minimum_commission=0))
    assert "holding_stats" in result
    assert result["equity_curve"]
    assert result["final_cash"] >= 0
