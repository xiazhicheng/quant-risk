#!/usr/bin/env python
"""市场轮动选股策略 回测 CLI（A股中证500 / 港股成交额Top100）。

用法:
  uv run scripts/backtest_rotation.py --market cn --days 800
  uv run scripts/backtest_rotation.py --market hk --days 800
  uv run scripts/backtest_rotation.py --market cn --no-cache   # 强制重拉数据

数据源: 成分池=东财 clist；日K=A股腾讯/港股腾讯→Yahoo；基准=A股中证500指数 / 港股恒生指数。
输出: 绩效指标表 + 调仓摘要 + 报告 markdown 落 report/rotation_{market}_YYYYmmdd.md。

策略规格见 scripts/quantrisk/rotation.py 头部 docstring。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from quantrisk import rotation
from quantrisk.rotation import (
    RotationBacktestConfig, backtest_benchmark, run_backtest,
)
from quantrisk.rotation import cache_matrix, save_cache  # noqa: F401  # 缓存读写


def _fmt_pct(x: float | None) -> str:
    return f"{x * 100:.2f}%" if x is not None else "—"


def _fmt_num(x: float | None) -> str:
    return f"{x:.3f}" if x is not None else "—"


async def _index_kline_async(symbol: str, days: int) -> "pd.Series | None":
    """基准指数日K收盘序列（腾讯通用 kline 通道）。"""
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


async def load_data(market: str, days: int, use_cache: bool):
    """池 + 行情矩阵（带缓存）。"""
    cache_key = f"{market}_d{days}"
    if use_cache:
        hit = cache_matrix(cache_key)
        uni = rotation.load_universe_cache(market)
        if hit and uni:
            return uni, hit[0], hit[1]

    if market == "cn":
        universe = await rotation.fetch_zz500_constituents()
        print(f"中证500成分: {len(universe)} 只")
    else:
        universe = await rotation.fetch_hk_top_amount()
        print(f"港股成交额Top{len(universe)}: {len(universe)} 只")

    close, open_df = await rotation.load_close_open(universe, market, days)
    if use_cache:
        save_cache(cache_key, close, open_df)
        rotation.save_universe_cache(market, universe)
    return universe, close, open_df


def render_report(market: str, universe, close, open_df, result, bench_series=None) -> str:
    """渲染 markdown 报告。"""
    cfg = result.config
    m = result.metrics

    # 基准
    if market == "cn":
        bench_name = "中证500指数 (000905.SH)"
    else:
        bench_name = "恒生指数 (HSI)"
    bench = {}
    if bench_series is not None:
        bench = backtest_benchmark(bench_series, result.equity_curve.index[0], result.equity_curve.index[-1])

    # 空仓占比 / 调仓次数 / 持仓覆盖率
    n_days = len(result.equity_curve)
    cash_days = (result.holdings.sum(axis=1) == 0).sum()
    avg_hold = result.holdings[result.holdings.sum(axis=1) > 0].apply(
        lambda r: (r > 0).sum(), axis=1).mean() if result.holdings.shape[0] else float("nan")

    lines = []
    lines.append(f"# 市场轮动选股策略回测 | {market.upper()} | {result.equity_curve.index[0].date()} → {result.equity_curve.index[-1].date()}")
    lines.append("")
    lines.append("## 参数")
    lines.append("")
    lines.append("| 参数 | 值 |")
    lines.append("|:--|:--|")
    lines.append(f"| 股票池 | {'中证500成分股 (000905.SH)' if market=='cn' else f'港股成交额 Top{len(universe)}'} |")
    lines.append(f"| 池规模 | {len(universe)} 只 |")
    lines.append(f"| 综合得分 | 0.5×rank(近20日涨跌) + 0.5×rank(近60日涨跌) |")
    lines.append(f"| 选股门槛 | 得分 ≥ {cfg.min_score}，降序前 {cfg.top_n} |")
    lines.append(f"| 调仓周期 | 每 {cfg.rebalance_days} 个交易日 |")
    lines.append(f"| 仓位 | 等权，{cfg.lot_size} 股整数倍 |")
    lines.append(f"| 预热 | {cfg.warmup_days} 个交易日 |")
    lines.append(f"| 初始资金 | {cfg.initial_cash:,.0f} |")
    lines.append(f"| 交易成本 | {cfg.commission_rate * 100:.2f}% / 边 |")
    lines.append(f"| 无合格标的 | 空仓 |")
    lines.append("")
    lines.append("> 选股无前瞻性：调仓日 t 用 **t-1 已收盘行情** 决策，t 日开盘价成交，t 日收盘价计市值。")
    lines.append("")
    lines.append("## 绩效（策略 vs 基准）")
    lines.append("")
    lines.append("| 指标 | 策略 | 基准 |")
    lines.append("|:--|:--|:--|")
    lines.append(f"| 累计收益 | {_fmt_pct(m.get('total_return'))} | {_fmt_pct(bench.get('total_return'))} |")
    lines.append(f"| 年化收益 | {_fmt_pct(m.get('annual_return'))} | {_fmt_pct(bench.get('annual_return'))} |")
    lines.append(f"| 最大回撤 | {_fmt_pct(m.get('max_drawdown'))} | {_fmt_pct(bench.get('max_drawdown'))} |")
    lines.append(f"| 夏普比率 | {_fmt_num(m.get('sharpe'))} | {_fmt_num(bench.get('sharpe'))} |")
    lines.append(f"| 年化波动 | {_fmt_pct(m.get('annual_vol'))} | {_fmt_pct(bench.get('annual_vol'))} |")
    lines.append("")
    lines.append(f"> 基准：{bench_name}")
    lines.append("")
    lines.append("## 持仓统计")
    lines.append("")
    lines.append(f"| 统计 | 值 |")
    lines.append("|:--|:--|")
    lines.append(f"| 回测交易日数 | {n_days} |")
    lines.append(f"| 调仓次数 | {len(result.trades)} |")
    lines.append(f"| 空仓天数占比 | {cash_days / n_days * 100:.1f}% |")
    if avg_hold == avg_hold:  # not NaN
        lines.append(f"| 平均持仓数 | {avg_hold:.1f} 只 |")
    lines.append("")

    lines.append("## 最近调仓记录")
    lines.append("")
    lines.append("| 调仓日 | 决策日 | 持仓代码（按得分降序） |")
    lines.append("|:--|:--|:--|")
    if result.trades:
        name_map = {u["code"]: u["name"] for u in universe}
        for tr in result.trades[-8:]:
            pos_names = "、".join(f"{c} {name_map.get(c,'')}" for c in tr["positions"])
            lines.append(f"| {tr['date']} | {tr['decision_date']} | {pos_names or '空仓'} |")
    lines.append("")

    total_ret = m.get("total_return", 0.0)
    bench_ret = bench.get("total_return")
    if bench_ret is not None:
        verdict = f"跑赢基准 {total_ret - bench_ret:+.2%}" if total_ret > bench_ret else f"跑输基准 {total_ret - bench_ret:+.2%}"
        lines.append(f"**小结**：策略累计 {_fmt_pct(total_ret)}，{verdict}（基准 {_fmt_pct(bench_ret)}）。")
    lines.append("")
    lines.append("> ⚠️ 声明：免费公开数据源（腾讯/东财）回测，未含滑点与停牌冲击，不构成投资建议。")
    lines.append("")
    return "\n".join(lines)


async def main_async(args) -> int:
    cfg = RotationBacktestConfig(
        top_n=args.top_n, min_score=args.min_score,
        rebalance_days=args.rebalance_days, commission_rate=args.commission,
    )

    universe, close, open_df = await load_data(args.market, args.days, not args.no_cache)
    if close.empty:
        print("❌ 行情数据为空，回测中止", file=sys.stderr)
        return 1

    bench_series = await _index_kline_async(
        "sh000905" if args.market == "cn" else "hkHSI", len(close))

    result = run_backtest(close, open_df, cfg, universe)
    report = render_report(args.market, universe, close, open_df, result, bench_series)

    out_dir = Path(__file__).resolve().parent.parent / "report"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"rotation_{args.market}_{datetime.now():%Y%m%d}.md"
    out_file.write_text(report, encoding="utf-8")
    print(report)
    print(f"\n📄 报告已保存: {out_file}")

    from quantrisk import data
    await data.close_async_session()   # 关闭 aiohttp 全局 session，避免未关闭警告
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="市场轮动选股策略回测")
    ap.add_argument("--market", choices=["cn", "hk"], default="cn")
    ap.add_argument("--days", type=int, default=800, help="拉取日K根数（需 ≥ warmup+回测窗口）")
    ap.add_argument("--no-cache", action="store_true", help="忽略本地缓存强制重拉")
    ap.add_argument("--top-n", type=int, default=rotation.TOP_N)
    ap.add_argument("--min-score", type=float, default=rotation.MIN_SCORE)
    ap.add_argument("--rebalance-days", type=int, default=rotation.REBALANCE_DAYS)
    ap.add_argument("--commission", type=float, default=0.0, help="双边费率（如 0.001=单边0.1%×2 简化）")
    args = ap.parse_args()

    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())