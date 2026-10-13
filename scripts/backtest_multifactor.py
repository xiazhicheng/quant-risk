#!/usr/bin/env python
"""多因子选股策略 回测 CLI（A股中证500 / 港股成交额Top100）。

用法:
  uv run scripts/backtest_multifactor.py --market cn --days 800
  uv run scripts/backtest_multifactor.py --market hk --days 600
  uv run scripts/backtest_multifactor.py --market cn --no-timing   # 关闭沪深300 MA20 择时
  uv run scripts/backtest_multifactor.py --market cn --commission 0.001

策略规格见 scripts/quantrisk/multifactor.py 头部 docstring。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from quantrisk import rotation
from quantrisk.multifactor import (
    HS300_SYMBOL, MultiFactorConfig, run_multifactor_backtest,
    fetch_net_profit_table,
)
from quantrisk.rotation import _metrics  # noqa: F401


def _fmt_pct(x: float | None) -> str:
    return f"{x * 100:.2f}%" if x is not None else "—"


def _fmt_num(x: float | None) -> str:
    return f"{x:.3f}" if x is not None else "—"


async def _index_kline_async(symbol: str, days: int) -> "pd.Series | None":
    """基准/择时指数日K收盘序列（腾讯通用 kline 通道）。"""
    import pandas as pd
    from quantrisk import data

    d = await data._tencent_kline_get(f"{symbol},day,,,{days},qfq")
    kdata = (((d or {}).get("data") or {}).get(symbol) or {})
    rows = kdata.get("day") or kdata.get("qfqday") or kdata.get("qfq") or []
    if not rows:
        return None
    s = pd.Series({r[0]: float(r[2]) for r in rows if len(r) >= 3})
    s.index = pd.to_datetime(s.index)
    return s.sort_index()


def _report_dates_range(start: str, end: str) -> list[str]:
    """生成 [start, end] 区间内全部季度报告期（3/6/9/12月 末），供净利润表拉取。"""
    import pandas as pd
    out: list[str] = []
    d = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    while d <= end_ts:
        m = ((d.month - 1) // 3 + 1) * 3            # 所在季度末月
        rd = pd.Timestamp(year=d.year, month=m, day=1) + pd.offsets.MonthEnd(0)
        out.append(rd.strftime("%Y-%m-%d"))
        d = rd + pd.Timedelta(days=1)
    return sorted(set(out))


def render_report(market: str, universe, close, open_df, volume, hs300, result,
                  bench_series=None) -> str:
    """渲染 markdown 报告。"""
    cfg = result.config
    m = result.metrics
    bench_name = "中证500指数 (000905.SH)" if market == "cn" else "恒生指数 (HSI)"
    bench = {}
    if bench_series is not None:
        seg = bench_series.loc[(bench_series.index >= result.equity_curve.index[0])
                               & (bench_series.index <= result.equity_curve.index[-1])]
        if len(seg) >= 2:
            bench = _metrics(seg.sort_index())

    cash_days = (result.holdings.sum(axis=1) == 0).sum()
    n_days = len(result.equity_curve)
    avg_hold = result.holdings[result.holdings.sum(axis=1) > 0].apply(
        lambda r: (r > 0).sum(), axis=1).mean() if result.holdings.shape[0] else float("nan")

    # 风控触发统计
    actions = [t for t in result.trades if t.get("action") in ("sell", "timing_close")]
    stop_cnt = sum(1 for t in actions if "止损" in t.get("note", ""))
    tp_cnt = sum(1 for t in actions if "止盈" in t.get("note", ""))
    timing_cnt = sum(1 for t in actions if t.get("action") == "timing_close")

    L = []
    L.append(f"# 多因子选股策略回测 | {market.upper()} | {result.equity_curve.index[0].date()} → {result.equity_curve.index[-1].date()}")
    L.append("")
    L.append("## 参数")
    L.append("")
    L.append("| 参数 | 值 |")
    L.append("|:--|:--|")
    L.append(f"| 股票池 | {'中证500成分股 (000905.SH)' if market=='cn' else f'港股成交额 Top{len(universe)}'} |")
    L.append(f"| 池规模 | {len(universe)} 只 |")
    L.append("| 硬过滤 | 停牌 / ST·退 / 亏损 / 20日均成交额<1000万 |")
    from quantrisk import multifactor
    L.append(f"| 因子权重 | 趋势 {multifactor.FACTOR_W['trend']*100:.0f}% + 波动率 {multifactor.FACTOR_W['vol']*100:.0f}%（低波加分）+ 成交额 {multifactor.FACTOR_W['amount']*100:.0f}% |")
    L.append(f"| 持仓上限 | {cfg.top_n} 只 |")
    L.append(f"| 仓位 | 按波动率三档：标准×1.0 / 中×0.7 / 高×0.4，剩余现金 |")
    L.append(f"| 调仓周期 | 每 {cfg.rebalance_days} 交易日 |")
    L.append(f"| 择时 | {'沪深300 收盘≥MA20 才持仓（fail-closed）' if cfg.use_ma20_timing else '关闭'} |")
    L.append(f"| 止损 | {cfg.stop_loss*100:.0f}%（成本回撤） |")
    L.append(f"| 止盈 | {cfg.take_profit*100:.0f}% 浮盈后峰值回撤 {cfg.take_profit_drawdown*100:.0f}% |")
    L.append(f"| 预热 | {cfg.warmup_days} 交易日 |")
    L.append(f"| 初始资金 | {cfg.initial_cash:,.0f} |")
    L.append(f"| 交易成本 | {cfg.commission_rate*100:.2f}% / 边 |")
    L.append("")
    L.append("> 无前瞻：调仓日 t 用 **t-1 已收盘行情** 决策，t 开盘价成交，t 收盘价计市值；择时/止损/止盈 t-1 收盘评估 → t 开盘执行。")
    L.append(f"> 亏损过滤（{'A股已启用' if market=='cn' else '港股数据源不可用 → fail-open 未启用'}）：财报披露滞后 {multifactor.DISCLOSURE_LAG_DAYS} 天防未来函数。")
    L.append("")
    L.append("## 绩效（策略 vs 基准）")
    L.append("")
    L.append("| 指标 | 策略 | 基准 |")
    L.append("|:--|:--|:--|")
    L.append(f"| 累计收益 | {_fmt_pct(m.get('total_return'))} | {_fmt_pct(bench.get('total_return'))} |")
    L.append(f"| 年化收益 | {_fmt_pct(m.get('annual_return'))} | {_fmt_pct(bench.get('annual_return'))} |")
    L.append(f"| 最大回撤 | {_fmt_pct(m.get('max_drawdown'))} | {_fmt_pct(bench.get('max_drawdown'))} |")
    L.append(f"| 夏普比率 | {_fmt_num(m.get('sharpe'))} | {_fmt_num(bench.get('sharpe'))} |")
    L.append(f"| 年化波动 | {_fmt_pct(m.get('annual_vol'))} | {_fmt_pct(bench.get('annual_vol'))} |")
    L.append("")
    L.append(f"> 基准：{bench_name}")
    L.append("")
    L.append("## 持仓与风控统计")
    L.append("")
    L.append("| 统计 | 值 |")
    L.append("|:--|:--|")
    L.append(f"| 回测交易日数 | {n_days} |")
    L.append(f"| 调仓次数 | {len([t for t in result.trades if t.get('action')=='rebalance'])} |")
    L.append(f"| 空仓天数占比 | {cash_days / n_days * 100:.1f}% |")
    L.append(f"| 止损触发 | {stop_cnt} 次 |")
    L.append(f"| 止盈触发 | {tp_cnt} 次 |")
    L.append(f"| 择时清仓 | {timing_cnt} 次 |")
    if avg_hold == avg_hold:
        L.append(f"| 平均持仓数 | {avg_hold:.1f} 只 |")
    L.append("")

    L.append("## 最近调仓记录")
    L.append("")
    L.append("| 调仓日 | 决策日 | 持仓代码（波动档位） |")
    L.append("|:--|:--|:--|")
    name_map = {u["code"]: u.get("name", "") for u in universe}
    reb = [t for t in result.trades if t.get("action") == "rebalance"]
    for tr in reb[-8:]:
        tier_names = {0: "标准", 1: "70%", 2: "40%"}
        pos = "、".join(f"{c} {name_map.get(c,'')}({tier_names.get(tier,'?')})"
                       for c, tier in tr.get("target", []) if c in tr.get("positions", {})) or "空仓"
        L.append(f"| {tr['date']} | {tr['decision_date']} | {pos} |")
    L.append("")

    total_ret = m.get("total_return", 0.0)
    bench_ret = bench.get("total_return")
    if bench_ret is not None:
        verdict = f"跑赢基准 {total_ret - bench_ret:+.2%}" if total_ret > bench_ret else f"跑输基准 {total_ret - bench_ret:+.2%}"
        L.append(f"**小结**：策略累计 {_fmt_pct(total_ret)}，{verdict}（基准 {_fmt_pct(bench_ret)}）。")
    L.append("")
    L.append("> ⚠️ 声明：免费公开数据源（腾讯/东财）回测，未含滑点与停牌冲击，不构成投资建议。")
    L.append("")
    return "\n".join(L)


async def main_async(args) -> int:
    import pandas as pd
    from quantrisk import multifactor
    cfg = MultiFactorConfig(
        top_n=args.top_n, rebalance_days=args.rebalance_days,
        commission_rate=args.commission, use_ma20_timing=not args.no_timing,
    )

    cache_key = f"mf_{args.market}_d{args.days}"
    hit = None
    if not args.no_cache:
        hit = rotation.cache_matrix(cache_key)
        uni = rotation.load_universe_cache(args.market)
        if hit and uni and len(hit) == 3:
            universe, close, open_df, volume = uni, hit[0], hit[1], hit[2]
            print(f"缓存命中: 池 {len(universe)} 只, 行情 {len(close)} 日")

    if hit is None:
        if args.market == "cn":
            universe = await rotation.fetch_zz500_constituents()
            print(f"中证500成分: {len(universe)} 只")
        else:
            universe = await rotation.fetch_hk_top_amount()
            print(f"港股成交额Top{len(universe)}: {len(universe)} 只")
        close, open_df, volume = await rotation.load_close_open_volume(
            universe, args.market, args.days)
        if not args.no_cache:
            rotation.save_cache(cache_key, close, open_df, volume)
            rotation.save_universe_cache(args.market, universe)

    # 净利润表（仅 A股；港股接口脏 → fail-open）
    np_df = None
    if args.market == "cn":
        pf = rotation.CACHE_DIR / f"netprofit_{args.market}.csv"
        if not args.no_cache and pf.exists():
            try:
                np_df = pd.read_csv(pf, index_col=0)
            except Exception:
                np_df = None
        if np_df is None:
            start = close.index[0] - pd.Timedelta(days=150)
            report_dates = _report_dates_range(str(start.date()), datetime.now().strftime("%Y-%m-%d"))
            np_df = await multifactor.fetch_net_profit_table(report_dates)
            if not args.no_cache and not np_df.empty:
                rotation.CACHE_DIR.mkdir(parents=True, exist_ok=True)
                np_df.to_csv(rotation.CACHE_DIR / f"netprofit_{args.market}.csv")

    # 沪深300 指数（择时）
    hs300 = await _index_kline_async(HS300_SYMBOL, len(close))
    # 基准指数
    bench_series = await _index_kline_async(
        "sh000905" if args.market == "cn" else "hkHSI", len(close))

    result = run_multifactor_backtest(close, open_df, volume, hs300, np_df, cfg, universe)
    report = render_report(args.market, universe, close, open_df, volume, hs300, result, bench_series)

    out_dir = Path(__file__).resolve().parent.parent / "report"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"multifactor_{args.market}_{datetime.now():%Y%m%d}.md"
    out_file.write_text(report, encoding="utf-8")
    print(report)
    print(f"\n📄 报告已保存: {out_file}")

    from quantrisk import data
    await data.close_async_session()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="多因子选股策略回测")
    ap.add_argument("--market", choices=["cn", "hk"], default="cn")
    ap.add_argument("--days", type=int, default=800, help="拉取日K根数")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--no-timing", action="store_true", help="关闭沪深300 MA20 择时")
    ap.add_argument("--top-n", type=int, default=10)
    ap.add_argument("--rebalance-days", type=int, default=20)
    ap.add_argument("--commission", type=float, default=0.0)
    args = ap.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())