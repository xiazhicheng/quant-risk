"""Per-stock gate execution and causality checks."""
import numpy as np
import pandas as pd
import pytest
from scripts.quantrisk.trendgate import TrendGateConfig, run_trendgate_backtest


def fixture():
    idx = pd.bdate_range('2025-01-01', periods=35)
    close = pd.DataFrame({'A': np.arange(10., 45.), 'B': np.arange(45., 10., -1)}, index=idx)
    scores = pd.DataFrame({'A': 1., 'B': .9}, index=idx)
    cfg = TrendGateConfig(gate_mode='stock', gate_ma=3, gate_confirm_days=3,
                          warmup_days=5, rebalance_days=100, top_n=2, lot_size=1)
    return close, close.shift(1), scores, cfg


def run(c, o, s, cfg, index=None):
    return run_trendgate_backtest(c, o, index, cfg, scores_override=s)


def test_independent_gate_leaves_closed_sleeve_cash():
    c, o, s, cfg = fixture()
    r = run(c, o, s, cfg)
    assert r.holdings['A'].iloc[0] > 0
    assert 'B' not in r.holdings or not r.holdings['B'].any()
    assert r.cash_curve.iloc[0] >= cfg.initial_cash * .65 - 1
    assert r.fills[0]['amount'] <= cfg.initial_cash * .35


def test_close_and_reopen_without_rebalance():
    c, o, s, cfg = fixture()
    c.loc[c.index[12:18], 'A'] = [10, 9, 8, 7, 6, 5]
    r = run(c, c.shift(1), s, cfg)
    sells = [f for f in r.fills if f['side'] == 'sell']
    buys = [f for f in r.fills if f['side'] == 'buy']
    assert sells and len(buys) >= 2
    assert len(r.trades) == 1
    assert buys[1]['date'] > sells[0]['date']


@pytest.mark.parametrize('mode', ['stock', 'index'])
def test_missing_open_retains_position_and_valuation(mode):
    c, o, s, cfg = fixture()
    cfg.gate_mode = mode
    ix = pd.Series(np.arange(100., 135.), index=c.index)
    c.loc[c.index[12], 'A'] = 1
    ix.loc[ix.index[12]] = 1
    o.loc[o.index[13], 'A'] = np.nan
    r = run(c, o, s, cfg, ix)
    assert r.holdings.loc[c.index[13], 'A'] > 0
    assert r.holdings.loc[c.index[14], 'A'] == 0
    assert not any(f['date'] == str(c.index[13].date()) and f['code'] == 'A' for f in r.fills)


def test_missing_index_fails_closed():
    c, o, s, cfg = fixture()
    cfg.gate_mode = 'index'
    r = run(c, o, s, cfg)
    assert not r.fills
    assert (r.equity_curve == cfg.initial_cash).all()


def test_stock_missing_signal_fails_closed():
    c, o, s, cfg = fixture()
    c.loc[c.index[12], 'A'] = np.nan
    r = run(c, o, s, cfg)
    assert r.holdings.loc[c.index[13], 'A'] == 0


def test_future_mutation_does_not_change_past_actions():
    c, o, s, cfg = fixture()
    r = run(c, o, s, cfg)
    mutated = c.copy()
    mutated.iloc[20:] *= .01
    r2 = run(mutated, o, s, cfg)
    cutoff = str(c.index[20].date())
    assert [f for f in r.fills if f['date'] <= cutoff] == [f for f in r2.fills if f['date'] <= cutoff]
    pd.testing.assert_series_equal(r.equity_curve.iloc[:15], r2.equity_curve.iloc[:15])


def test_accounting_and_first_day_fee():
    c, o, s, cfg = fixture()
    cfg.commission_rate = .002
    r = run(c, o, s, cfg)
    expected = cfg.initial_cash
    for t in r.equity_curve.index:
        for f in r.fills:
            if f['date'] == str(t.date()):
                expected += (f['amount'] if f['side'] == 'sell' else -f['amount']) - f['fee']
        assert r.cash_curve.loc[t] == pytest.approx(expected)
        assert expected >= 0
    assert r.metrics['total_return'] == pytest.approx(r.equity_curve.iloc[-1] / cfg.initial_cash - 1)
    assert r.metrics['fees'] > 0
