#!/usr/bin/env python
"""Walk-forward 闸门验证 CLI：滚动窗口比较「指数统一闸门」vs「个股独立闸门」。

目的：全区间回测只给一个数，无法回答「优势是否稳健」。本工具把样本切成
多个滚动评测段（每段前置预热），逐段独立回测两种闸门，统计个股闸门的
窗口胜率、超额分布（均值/中位/最差/最好）与风险指标差，用于判断
「个股闸门纳入候选」是否有稳健证据。

无前瞻：每段只用该段及其之前的数据（预热段属于历史）；段内保持
t-1 收盘决策 → t 开盘成交 → t 收盘计值的引擎时序。

用法:
  uv run scripts/walkforward_gate.py --market hk --pool hsi --top-ns 3,5,10
  uv run scripts/walkforward_gate.py --market cn --top-ns 3,5,10 --eval-days 60
  uv run scripts/walkforward_gate.py --market hk --pool hsi --top-ns 5 --eval-days 120 --step 20
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from quantrisk import rotation
from quantrisk.rotation import _metrics
from quantrisk.trendgate import (HS300_SYMBOL, HSI_SYMBOL, TrendGateConfig,
                                 run_trendgate_backtest)


def _fmt_pct(x) -> str:
    return f"{x * 100:.2f}%" if x is not None and np.isfinite(x) else "—"


def _fmt_num(x) -> str:
    return f"{x:.3f}" if x is not None and np.isfinite(x) else "—"


async def _load_data(market: str, pool: str, days: int):
    """返回 (universe, close, open_df, gate_index)。缓存缺失时报错退出。"""
    use_hsi = market == "hk" and pool == "hsi"
    uni_key = "hk_hsi" if use_hsi else market
    cache_key = f"{uni_key}_d{days}"
    hit = rotation.cache_matrix(cache_key)
    universe = rotation.load_universe_cache(uni_key)
    if not (hit and universe):
        raise SystemExit(f"❌ 缓存缺失（{cache_key} / universe_{uni_key}.json）——"
                         f"请先跑 backtest_trendgate.py --market {market} 生成缓存")
    close, open_df = hit[0], hit[1]
    symbol = HS300_SYMBOL if market == "cn" else HSI_SYMBOL
    gate_index = await _index_kline_async(symbol, len(close))
    if gate_index is None:
        raise SystemExit(f"❌ 闸门指数 {symbol} 获取失败（fail-closed）")
    return universe, close, open_df, gate_index


async def _index_kline_async(symbol: str, days: int):
    """复用 backtest_trendgate 的指数行情实现（同一数据源，符号直传）。"""
    from backtest_trendgate import _index_kline_async as _impl
    return await _impl(symbol, days)


def _rolling_starts(n_dates: int, warmup: int, eval_days: int, step: int) -> list[int]:
    """评测段起点位置：每段前置 warmup 天预热，评测段长 eval_days。"""
    if n_dates <= warmup + eval_days:
        raise ValueError(f"数据不足：{n_dates} 日，需 > 预热({warmup})+评测段({eval_days})")
    return list(range(warmup, n_dates - eval_days + 1, step))


def _eval_segment(curve: pd.Series, seg_dates) -> pd.Series:
    """按评测段日期裁出净值并归一到 1.0。

    引擎只从 warmup 之后记录净值（range(cfg.warmup_days, len(dates))），
    因此必须按日期对齐，不能按窗口内位置切片。
    """
    seg = curve.reindex(pd.DatetimeIndex(list(seg_dates))).dropna().astype(float)
    if len(seg) < 2 or seg.iloc[0] <= 0:
        return seg
    return seg / seg.iloc[0]


def _base_cfg(args, top_n: int) -> TrendGateConfig:
    return TrendGateConfig(
        gate_mode="index", top_n=top_n, rebalance_days=args.rebalance_days,
        commission_rate=args.commission, use_ma20_timing=True,
        gate_ma=args.gate_ma, gate_confirm_days=args.confirm,
        max_exposure=args.exposure, warmup_days=args.warmup,
        market=args.market, slippage=args.slippage,
        enforce_price_limits=not args.no_limit_check,
        enforce_halts=not args.no_halt_check,
    )


def _run_pair(close, open_df, gate_index, cfg: TrendGateConfig, universe, seg_dates):
    """同窗口跑两种闸门，返回评测段指标对（seg_dates=该段实际交易日）。"""
    r_idx = run_trendgate_backtest(close, open_df, gate_index, cfg, universe)
    r_stk = run_trendgate_backtest(close, open_df, None, replace(cfg, gate_mode="stock"), universe)
    m_idx = _metrics(_eval_segment(r_idx.equity_curve, seg_dates))
    m_stk = _metrics(_eval_segment(r_stk.equity_curve, seg_dates))
    return m_idx, m_stk


def _full_period(close, open_df, gate_index, cfg, universe, seg_dates):
    """全区间口径（预热后），用于与滚动结论对照。"""
    r_idx = run_trendgate_backtest(close, open_df, gate_index, cfg, universe)
    r_stk = run_trendgate_backtest(close, open_df, None, replace(cfg, gate_mode="stock"), universe)
    return _metrics(_eval_segment(r_idx.equity_curve, seg_dates)), \
        _metrics(_eval_segment(r_stk.equity_curve, seg_dates))


def _render(args, label: str, full_rows: list[dict], roll_rows: list[dict],
            detail_rows: list[dict], n_dates: int, start, end) -> str:
    L = []
    L.append(f"# Walk-forward 闸门验证：指数统一 vs 个股独立（{label}）")
    L.append("")
    L.append(f"区间：{start:%Y-%m-%d} → {end:%Y-%m-%d}；{n_dates} 交易日（最近约 3 年口径）。")
    L.append(f"滚动设置：评测段 {args.eval_days} 交易日、步进 {args.step}、预热 {args.warmup}；"
             f"每段独立从 {args.initial_cash:,.0f} 起始资金。")
    L.append(f"共同参数：MA{args.gate_ma}、连续{args.confirm}日、敞口{args.exposure:.0%}、"
             f"每{args.rebalance_days}日调仓、单边费用 {args.commission:.2%}。")
    L.append("")
    L.append("> 无前瞻：每段只用该段及其之前的数据（预热段属历史）；段内 t-1 收盘决策 → t 开盘成交 → t 收盘计值。")
    L.append("")
    L.append("## 一、全区间口径（多 N 对照）")
    L.append("")
    L.append("| 持仓数 N | 指数累计 | 个股累计 | 超额 | 指数回撤 | 个股回撤 | 指数夏普 | 个股夏普 |")
    L.append("|:--|--:|--:|--:|--:|--:|--:|--:|")
    for r in full_rows:
        L.append(f"| {r['n']} | {_fmt_pct(r['idx_ret'])} | {_fmt_pct(r['stk_ret'])} | "
                 f"{_fmt_pct(r['exc'])} | {_fmt_pct(r['idx_dd'])} | {_fmt_pct(r['stk_dd'])} | "
                 f"{_fmt_num(r['idx_sharpe'])} | {_fmt_num(r['stk_sharpe'])} |")
    L.append("")
    L.append("## 二、滚动窗口验证（核心：优势是否稳健）")
    L.append("")
    L.append("| 持仓数 N | 窗口数 | 个股胜率 | 平均超额 | 中位超额 | 最差窗口 | 最好窗口 | 夏普差均值 | 回撤差均值 |")
    L.append("|:--|--:|--:|--:|--:|--:|--:|--:|--:|")
    for r in roll_rows:
        L.append(f"| {r['n']} | {r['n_win']} | {r['win_rate']:.1%} | {_fmt_pct(r['exc_mean'])} | "
                 f"{_fmt_pct(r['exc_med'])} | {_fmt_pct(r['exc_min'])} | {_fmt_pct(r['exc_max'])} | "
                 f"{_fmt_num(r['sharpe_diff'])} | {_fmt_pct(r['dd_diff'])} |")
    L.append("")
    L.append("> 超额 = 个股闸门评测段收益 − 指数闸门评测段收益；胜率 = 超额 > 0 的窗口占比；"
             "夏普差 = 个股夏普 − 指数夏普（均值）；回撤差 = 个股回撤 − 指数回撤（均值，负值表示个股回撤更浅）。")
    L.append("")
    L.append("## 三、滚动窗口明细")
    L.append("")
    L.append("| 持仓数 N | 评测段 | 指数收益 | 个股收益 | 超额 | 指数回撤 | 个股回撤 |")
    L.append("|:--|:--|--:|--:|--:|--:|--:|")
    for r in detail_rows:
        L.append(f"| {r['n']} | {r['seg']} | {_fmt_pct(r['idx_ret'])} | {_fmt_pct(r['stk_ret'])} | "
                 f"{_fmt_pct(r['exc'])} | {_fmt_pct(r['idx_dd'])} | {_fmt_pct(r['stk_dd'])} |")
    L.append("")
    L.append("## 四、边界与风险")
    L.append("")
    L.append("- 各段共享同一份历史行情与同一池快照，段间高度相关，**不是独立样本外**；"
             "滚动验证只回答「优势是否在不同时间窗重复出现」，不消除池快照前视偏差。")
    L.append("- 港股恒指成分池无法 PIT 重建 → 绝对收益与超额均含成分快照红利，样本外需打折。")
    L.append("- 未模拟涨跌停、停牌、滑点与港股每手股数差异（lot_size 统一按 100）。")
    n_seg = roll_rows[0]["n_win"] if roll_rows else 0
    L.append(f"- 段数有限（本口径 {n_seg} 段/N），胜率与超额分布的统计功效有限。")
    L.append("")
    return "\n".join(L)


async def main_async(args) -> int:
    universe, close, open_df, gate_index = await _load_data(args.market, args.pool, args.days)
    dates = list(close.index)
    warmup, eval_days, step = args.warmup, args.eval_days, args.step
    if len(dates) <= warmup + eval_days:
        raise SystemExit(f"❌ 数据不足：{len(dates)} 日，需 > 预热({warmup})+评测段({eval_days})")
    starts = _rolling_starts(len(dates), warmup, eval_days, step)
    top_ns = [int(x) for x in str(args.top_ns).split(",") if x.strip()]
    label = (f"{args.market} / {'恒指成分池' if args.pool == 'hsi' and args.market == 'hk' else args.pool}"
             f" / N={'/'.join(map(str, top_ns))}")

    full_rows, roll_rows, detail_rows = [], [], []
    for n in top_ns:
        cfg = _base_cfg(args, n)
        m_idx, m_stk = _full_period(close, open_df, gate_index, cfg, universe, dates[warmup:])
        full_rows.append({
            "n": n,
            "idx_ret": m_idx.get("total_return"), "stk_ret": m_stk.get("total_return"),
            "exc": (m_stk.get("total_return", 0) - m_idx.get("total_return", 0)),
            "idx_dd": m_idx.get("max_drawdown"), "stk_dd": m_stk.get("max_drawdown"),
            "idx_sharpe": m_idx.get("sharpe"), "stk_sharpe": m_stk.get("sharpe"),
        })
        excs, sharpe_diffs, dd_diffs = [], [], []
        for i in starts:
            lo, hi = i - warmup, i + eval_days
            c, o = close.iloc[lo:hi], open_df.iloc[lo:hi]
            g = gate_index.iloc[lo:hi]
            m_i, m_s = _run_pair(c, o, g, cfg, universe, dates[i:i + eval_days])
            exc = m_s.get("total_return", 0) - m_i.get("total_return", 0)
            excs.append(exc)
            sharpe_diffs.append(m_s.get("sharpe", 0) - m_i.get("sharpe", 0))
            dd_diffs.append(m_s.get("max_drawdown", 0) - m_i.get("max_drawdown", 0))
            detail_rows.append({
                "n": n, "seg": f"{dates[i]:%Y-%m-%d}~{dates[i + eval_days - 1]:%Y-%m-%d}",
                "idx_ret": m_i.get("total_return"), "stk_ret": m_s.get("total_return"),
                "exc": exc, "idx_dd": m_i.get("max_drawdown"), "stk_dd": m_s.get("max_drawdown"),
            })
        arr = np.array(excs, dtype=float)
        roll_rows.append({
            "n": n, "n_win": len(arr), "win_rate": float((arr > 0).mean()) if len(arr) else 0.0,
            "exc_mean": float(arr.mean()) if len(arr) else 0.0,
            "exc_med": float(np.median(arr)) if len(arr) else 0.0,
            "exc_min": float(arr.min()) if len(arr) else 0.0,
            "exc_max": float(arr.max()) if len(arr) else 0.0,
            "sharpe_diff": float(np.mean(sharpe_diffs)) if sharpe_diffs else 0.0,
            "dd_diff": float(np.mean(dd_diffs)) if dd_diffs else 0.0,
        })

    report = _render(args, label, full_rows, roll_rows, detail_rows, len(dates), dates[0], dates[-1])
    out_dir = Path(__file__).resolve().parent.parent / "report"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"walkforward_gate_{args.market}_{datetime.now():%Y%m%d_%H%M}.md"
    out_file.write_text(report, encoding="utf-8")
    print(report)
    print(f"\n📄 报告已保存: {out_file}")
    from quantrisk import data
    await data.close_async_session()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Walk-forward 闸门验证（指数统一 vs 个股独立）")
    ap.add_argument("--market", choices=["cn", "hk"], default="hk")
    ap.add_argument("--pool", choices=["amount", "hsi"], default="hsi",
                    help="hk 池来源；hsi=恒指成分（默认，当前推荐配置）")
    ap.add_argument("--top-ns", default="3,5,10", help="待验证持仓数，逗号分隔（默认 3,5,10）")
    ap.add_argument("--days", type=int, default=800, help="行情天数（缓存 key，默认 800≈最近3年）")
    ap.add_argument("--eval-days", type=int, default=120, help="评测段长度（交易日，默认 120≈半年）")
    ap.add_argument("--step", type=int, default=20, help="滚动步进（交易日，默认 20）")
    ap.add_argument("--warmup", type=int, default=120, help="每段预热天数（默认 120，与引擎一致）")
    ap.add_argument("--gate-ma", type=int, default=30)
    ap.add_argument("--confirm", type=int, default=3)
    ap.add_argument("--exposure", type=float, default=0.7)
    ap.add_argument("--rebalance-days", type=int, default=20)
    ap.add_argument("--commission", type=float, default=0.001, help="单边费用（默认 0.1%）")
    ap.add_argument("--initial-cash", type=float, default=1_000_000.0)
    args = ap.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
