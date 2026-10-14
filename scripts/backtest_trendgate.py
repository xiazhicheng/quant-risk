#!/usr/bin/env python
"""闸门动量回测 CLI（TrendGate = rotation 动量 × 沪深300 MA20 择时闸门）。

用法:
  uv run scripts/backtest_trendgate.py --market cn --days 800
  uv run scripts/backtest_trendgate.py --market cn --no-timing   # 关掉择时 = 退化为 rotation
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from quantrisk import rotation
from quantrisk.trendgate import HS300_SYMBOL, HSI_SYMBOL, TrendGateConfig, run_trendgate_backtest
from quantrisk.rotation import _metrics


def _fmt_pct(x): return f"{x * 100:.2f}%" if x is not None else "—"
def _fmt_num(x): return f"{x:.3f}" if x is not None else "—"


async def _index_kline_async(symbol: str, days: int):
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


def render_report(result, universe, close=None, bench_series=None, market: str = "cn",
                  gate_symbol: str = "", pool: str = "amount") -> str:
    cfg = result.config
    m = result.metrics
    bench = {}
    if bench_series is not None:
        seg = bench_series.loc[(bench_series.index >= result.equity_curve.index[0])
                               & (bench_series.index <= result.equity_curve.index[-1])]
        if len(seg) >= 2:
            bench = _metrics(seg.sort_index())

    # 同池等权 buy&hold：池子筛选出的组合，其**可比基准**是同池等权，而非市场指数
    ew_ret = None
    if close is not None and len(close):
        _ew = (1 + close.pct_change().mean(axis=1).fillna(0.0)).cumprod()
        _seg = _ew.reindex(result.equity_curve.index).dropna()
        if len(_seg) > 1:
            ew_ret = float(_seg.iloc[-1] / _seg.iloc[0] - 1)

    cash_days = (result.holdings.sum(axis=1) == 0).sum()
    n_days = len(result.equity_curve)
    timing_cnt = sum(1 for t in result.trades if t.get("action") == "timing_close")
    reb_cnt = sum(1 for t in result.trades if t.get("action") == "rebalance")

    L = []
    market_label = "CN" if market == "cn" else "HK"
    gate_name = "个股自身 MA" if cfg.gate_mode == "stock" else \
        ({"sh000300": "沪深300 MA", "hkHSI": "恒生指数 MA"}.get(gate_symbol) or f"{gate_symbol} MA")
    L.append(f"# 闸门动量回测（TrendGate：rotation × {gate_name}{cfg.gate_ma} 闸门）| {market_label} | {result.equity_curve.index[0].date()} → {result.equity_curve.index[-1].date()}")
    L.append("")
    L.append("## 参数")
    L.append("")
    L.append("| 参数 | 值 |")
    L.append("|:--|:--|")
    pool_label = "恒生指数成分（维基快照，2026-09 生效）" if pool == "hsi" \
        else f"港股成交额 Top{len(universe)}"
    pool_name = ("沪深A股全市场（含ST/退市整理/次新，未过滤）" if pool == "all"
                 else ("中证500成分股 (000905.SH)" if market == "cn" else pool_label))
    L.append(f"| 股票池 | {pool_name}，{len(universe)} 只 |")
    L.append(f"| 选股 | rotation 双动量：0.5×rank(20日)+0.5×rank(60日)，≥{cfg.min_score} 取前{cfg.top_n} |")
    L.append(f"| 调仓 | 每 {cfg.rebalance_days} 交易日，等权，{cfg.lot_size} 股整数倍 |")
    L.append(f"| 择时开关 | {gate_name}{cfg.gate_ma} 收盘≥均线才持仓（连续{cfg.gate_confirm_days}日确认再入场） |" if cfg.use_ma20_timing
             else "| 择时开关 | 关闭（退化为 rotation） |")
    L.append(f"| 总敞口上限 | {cfg.max_exposure:.0%}（余下现金） |")
    L.append(f"| 个股风控 | {'8%止损+15%浮盈回撤5%止盈' if cfg.use_stock_risk else '关闭（实测开启会恶化回撤，见 CHANGELOG）'} |")
    L.append(f"| 预热 | {cfg.warmup_days} 交易日 |")
    L.append(f"| 初始资金 | {cfg.initial_cash:,.0f} |")
    L.append(f"| 交易成本 | {cfg.commission_rate*100:.2f}% / 边 + 滑点 {cfg.slippage*100:.2f}% / 边 |")
    L.append(f"| 可成交性约束 | 涨跌停 {'开' if cfg.enforce_price_limits else '关'}（涨停买不进/跌停卖不出，按板块）、"
             f"停牌 {'开' if cfg.enforce_halts else '关'}（无量不可成交） |")
    L.append("")
    L.append("> 无前瞻：t-1 收盘决策 → t 开盘成交 → t 收盘计市值。")
    L.append(f"> {_exec_line(cfg, result.execution)}")
    L.append("> ⚠️ 参数（确认日数/敞口）在 2023-10~2026-10 同一窗口内选定，存在样本内挑选风险；")
    L.append("> gate 额外滞后 1 天会使回撤从 -21.6% 恶化至 -36.2%，保护效果对信号时效敏感。")
    L.append("")
    L.append("## 绩效（策略 vs 基准）")
    L.append("")
    L.append("| 指标 | 闸门动量 | 市场指数基准 | 同池等权基准(可比) |")
    L.append("|:--|:--|:--|:--|")
    L.append(f"| 累计收益 | {_fmt_pct(m.get('total_return'))} | {_fmt_pct(bench.get('total_return'))} | {_fmt_pct(ew_ret)} |")
    L.append(f"| 年化收益 | {_fmt_pct(m.get('annual_return'))} | {_fmt_pct(bench.get('annual_return'))} | — |")
    L.append(f"| 最大回撤 | {_fmt_pct(m.get('max_drawdown'))} | {_fmt_pct(bench.get('max_drawdown'))} | — |")
    L.append(f"| 夏普比率 | {_fmt_num(m.get('sharpe'))} | {_fmt_num(bench.get('sharpe'))} | — |")
    L.append(f"| 年化波动 | {_fmt_pct(m.get('annual_vol'))} | {_fmt_pct(bench.get('annual_vol'))} | — |")
    L.append("")
    L.append(f"> 市场指数基准：{'中证500指数 (000905.SH)' if market == 'cn' else '恒生指数 (HSI)'}")
    L.append("> ⚠️ **可比基准是同池等权**（池子筛选出的组合应与同池等权比较）；市场指数仅供参考，")
    L.append("> 且港股池为「当前成交额快照」，同池等权本身含前视/幸存者偏差 → 绝对收益应视为上界。")
    L.append("")
    L.append("## 持仓统计")
    L.append("")
    L.append("| 统计 | 值 |")
    L.append("|:--|:--|")
    L.append(f"| 回测交易日数 | {n_days} |")
    L.append(f"| 调仓次数 | {reb_cnt} |")
    L.append(f"| 择时清仓次数 | {timing_cnt} |")
    L.append(f"| 空仓天数占比 | {cash_days / n_days * 100:.1f}% |")
    L.append("")

    L.append("## 最近调仓记录")
    L.append("")
    L.append("| 调仓日 | 决策日 | 持仓代码 |")
    L.append("|:--|:--|:--|")
    name_map = {u["code"]: u.get("name", "") for u in universe}
    reb = [t for t in result.trades if t.get("action") == "rebalance"]
    for tr in reb[-8:]:
        pos = "、".join(f"{c} {name_map.get(c,'')}" for c in tr.get("positions", {})) or "空仓"
        L.append(f"| {tr['date']} | {tr['decision_date']} | {pos} |")
    L.append("")

    total_ret = m.get("total_return", 0.0)
    bench_ret = bench.get("total_return")
    if bench_ret is not None:
        verdict = f"跑赢基准 {total_ret - bench_ret:+.2%}" if total_ret > bench_ret else f"跑输基准 {total_ret - bench_ret:+.2%}"
        L.append(f"**小结**：闸门动量累计 {_fmt_pct(total_ret)}，{verdict}（基准 {_fmt_pct(bench_ret)}）。")
    L.append("")
    _lim = "已含涨跌停不可成交" if cfg.enforce_price_limits else "未含涨跌停约束"
    _halt = "已含停牌不可成交" if (cfg.enforce_halts and result.execution.get("has_volume")) else "未含停牌约束"
    L.append(f"> ⚠️ 声明：免费公开数据源（腾讯/东财）回测，{_lim}、{_halt}、"
             f"滑点 {cfg.slippage*100:.2f}%/边；未模拟涨跌停打开后的盘中成交与冲击成本，不构成投资建议。")
    return "\n".join(L)


def _exec_line(cfg, execution: dict) -> str:
    """执行摩擦口径披露（滑点/涨跌停/停牌 + 受阻次数）。"""
    e = execution or {}
    vol_note = "" if e.get("has_volume", True) else "；⚠️ 无 volume 矩阵 → 停牌检查未生效"
    return (f"执行口径：滑点 {cfg.slippage:.2%}/边、涨跌停检查 "
            f"{'开' if cfg.enforce_price_limits else '关'}（A股 开盘涨停买不进 / 跌停卖不出；"
            f"ST 5% / 创业科创 20% / 北交所 30% / 主板 {cfg.limit_pct:.0%}）、停牌检查 "
            f"{'开' if cfg.enforce_halts else '关'}（成交量 0 或缺失当日不可成交）→ 受阻成交："
            f"涨停 {e.get('limit_up_blocked', 0)} 次 / 跌停 {e.get('limit_down_blocked', 0)} 次 / "
            f"停牌 {e.get('halt_blocked', 0)} 次；期末未成交卖单 {e.get('pending_sells', 0)} 笔{vol_note}")


def render_comparison(close, open_df, gate_index, cfg, universe, volume=None):
    import pandas as pd
    rows, results = [], {}
    for fee in sorted({0.0, cfg.commission_rate, 0.002}):
        for mode in ("index", "stock"):
            r = run_trendgate_backtest(close, open_df, gate_index,
                                      replace(cfg, gate_mode=mode, commission_rate=fee), universe,
                                      volume_df=volume)
            if fee == cfg.commission_rate:
                results[mode] = r
            m = r.metrics
            flat = float(r.holdings.sum(axis=1).eq(0).mean())
            rows.append(f"| {fee:.2%} | {'指数统一' if mode == 'index' else '个股独立'} | "
                        f"{m['total_return']:.2%} | {m['annual_return']:.2%} | "
                        f"{m['max_drawdown']:.2%} | {m['sharpe']:.3f} | "
                        f"{m['average_exposure']:.1%} | {flat:.1%} | {len(r.fills)} | "
                        f"{m['turnover']:.2f} | {m['fees']:,.0f} |")
    ref = results['index']
    lines = ["# 指数闸门 vs 个股闸门：同口径回测", "",
             f"区间：{ref.equity_curve.index[0].date()} → {ref.equity_curve.index[-1].date()}；"
             f"{len(ref.equity_curve)}交易日；实际行情{len(close.columns)}只 / 池{len(universe)}只。", "",
             f"共同参数：MA{cfg.gate_ma}、连续{cfg.gate_confirm_days}日、敞口{cfg.max_exposure:.0%}、"
             f"双动量前{cfg.top_n}、每{cfg.rebalance_days}日调仓、初始资金{cfg.initial_cash:,.0f}。", "",
             _exec_line(cfg, results["index"].execution), "",
             "个股版：先按原排名选前N，再逐只开关；关闸份额留现金，不替补、不集中到剩余股票；"
             "名单在调仓间隔内固定，闸门重开可按原预算再入场，受现金限制。指数版保留统一进退。", "",
             "| 单边费用 | 闸门 | 累计收益 | 年化收益 | 最大回撤 | 夏普 | 平均仓位 | 空仓日 | 成交笔数 | 双边成交额/平均权益 | 费用 |",
             "|:--|:--|--:|--:|--:|--:|--:|--:|--:|--:|--:|", *rows, "",
             f"## 分年与前后半段（单边费用{cfg.commission_rate:.2%}，固定参数、不重新选优）", "",
             "| 期间 | 指数收益 | 个股收益 | 指数回撤 | 个股回撤 |", "|:--|--:|--:|--:|--:|"]
    dates = ref.equity_curve.index
    periods = [(str(y), dates[dates.year == y]) for y in sorted(set(dates.year))]
    periods += [("前半段", dates[:len(dates)//2]), ("后半段", dates[len(dates)//2:])]
    for label, segment in periods:
        mm = []
        for mode in ('index', 'stock'):
            eq = results[mode].equity_curve
            start = eq.index.get_loc(segment[0])
            base = cfg.initial_cash if start == 0 else eq.iloc[start-1]
            curve = pd.concat([pd.Series([base]), eq.loc[segment].reset_index(drop=True)], ignore_index=True)
            mm.append(_metrics(curve))
        lines.append(f"| {label} | {mm[0]['total_return']:.2%} | {mm[1]['total_return']:.2%} | "
                     f"{mm[0]['max_drawdown']:.2%} | {mm[1]['max_drawdown']:.2%} |")
    lines += ["", "## 数据与验证边界", "",
              "- 同一份缓存行情与同一指数快照，t-1收盘决策、t开盘成交；缺失开盘价不成交、不用当日收盘替代。",
              "- 两版共同修正：指数数据缺失fail-closed，无法卖出的持仓保留；初始费用纳入绩效，买入预算含费用。历史旧版数字不可直接拼接比较。",
              "- 当前中证500成分快照仍有幸存者/成分前视偏差；未模拟涨跌停、真实停牌、滑点和税费差异。",
              "- 分段是同一历史路径的稳定性检查，不是真正独立样本外；没有据此调优参数。",
              "- 个股版仍是横截面组合策略，不是把全部资金独立投入任意单股；70%预算不保证跳空后实时敞口始终不超过70%。"]
    return '\n'.join(lines)


def render_rebalance_comparison(close, open_df, gate_index, cfg, universe, volume=None):
    """定期换仓(periodic) vs 事件驱动(event)：同池、同闸门、同费用口径。

    event 口径：不强制换仓（掉出双动量排名不卖）；每日只认卖出信号（闸门关闭）；
    调仓日评估买入信号——新信号在持仓数 < N 时入场，已有持仓低于目标权重才补足加仓。
    """
    import pandas as pd
    modes = ("periodic", "event")
    labels = {"periodic": f"定期换仓（每{cfg.rebalance_days}日）",
              "event": "事件驱动（卖出信号才离场）"}
    rows, results = [], {}
    for fee in sorted({0.0, cfg.commission_rate, 0.002}):
        for mode in modes:
            r = run_trendgate_backtest(close, open_df, gate_index,
                                       replace(cfg, rebalance_mode=mode, commission_rate=fee), universe,
                                       volume_df=volume)
            if fee == cfg.commission_rate:
                results[mode] = r
            m = r.metrics
            flat = float(r.holdings.sum(axis=1).eq(0).mean())
            rows.append(f"| {fee:.2%} | {labels[mode]} | "
                        f"{m['total_return']:.2%} | {m['annual_return']:.2%} | "
                        f"{m['max_drawdown']:.2%} | {m['sharpe']:.3f} | "
                        f"{m['average_exposure']:.1%} | {flat:.1%} | {len(r.fills)} | "
                        f"{m['turnover']:.2f} | {m['fees']:,.0f} |")
    ref = results['periodic']
    gate_txt = "个股自身 MA" if cfg.gate_mode == "stock" else "市场指数"
    lines = ["# 定期换仓 vs 事件驱动：同口径回测", "",
             f"区间：{ref.equity_curve.index[0].date()} → {ref.equity_curve.index[-1].date()}；"
             f"{len(ref.equity_curve)}交易日；实际行情{len(close.columns)}只 / 池{len(universe)}只。", "",
             f"共同参数：闸门={gate_txt} MA{cfg.gate_ma}、连续{cfg.gate_confirm_days}日、"
             f"敞口{cfg.max_exposure:.0%}、双动量前{cfg.top_n}、初始资金{cfg.initial_cash:,.0f}。", "",
             _exec_line(cfg, ref.execution), "",
             f"**事件驱动口径**：不强制换仓——掉出双动量前{cfg.top_n}**不卖**（`exit_on_rank_drop="
             f"{'on' if cfg.exit_on_rank_drop else 'off'}`）；每日只认卖出信号（闸门关闭即离场）；"
             f"调仓日评估买入信号：持仓数 < {cfg.top_n} 时新信号入场，已有持仓低于目标权重 "
             f"{(1 - cfg.add_tolerance):.0%} 才补足加仓，总敞口受 {cfg.max_exposure:.0%} 约束。", "",
             "| 单边费用 | 换仓机制 | 累计收益 | 年化收益 | 最大回撤 | 夏普 | 平均仓位 | 空仓日 | 成交笔数 | 双边成交额/平均权益 | 费用 |",
             "|:--|:--|--:|--:|--:|--:|--:|--:|--:|--:|--:|", *rows, "",
             f"## 分年与前后半段（单边费用{cfg.commission_rate:.2%}，固定参数、不重新选优）", "",
             "| 期间 | 定期换仓收益 | 事件驱动收益 | 定期回撤 | 事件回撤 |", "|:--|--:|--:|--:|--:|"]
    dates = ref.equity_curve.index
    periods = [(str(y), dates[dates.year == y]) for y in sorted(set(dates.year))]
    periods += [("前半段", dates[:len(dates)//2]), ("后半段", dates[len(dates)//2:])]
    for label, segment in periods:
        mm = []
        for mode in modes:
            eq = results[mode].equity_curve
            start = eq.index.get_loc(segment[0])
            base = cfg.initial_cash if start == 0 else eq.iloc[start-1]
            curve = pd.concat([pd.Series([base]), eq.loc[segment].reset_index(drop=True)], ignore_index=True)
            mm.append(_metrics(curve))
        lines.append(f"| {label} | {mm[0]['total_return']:.2%} | {mm[1]['total_return']:.2%} | "
                     f"{mm[0]['max_drawdown']:.2%} | {mm[1]['max_drawdown']:.2%} |")
    lines += ["", "## 数据与验证边界", "",
              "- 同一份缓存行情、同一闸门与同一指数快照，t-1收盘决策、t开盘成交；缺失开盘价不成交。",
              "- 事件驱动版的调仓日只做「买入/加仓评估」，不做卖出（卖出只由闸门信号触发）→ 持仓可持续保留数月。",
              "- 事件驱动版持仓上限 = 双动量前N；若旧仓长期不触发卖出信号，新信号可能无法入场（这是机制特性不是 bug）。",
              "- 当前成分池快照仍有幸存者/成分前视偏差；未模拟涨跌停、真实停牌、滑点和税费差异。",
              "- 分段是同一历史路径的稳定性检查，不是真正独立样本外；没有据此调优参数。"]
    if cfg.gate_mode == "index":
        lines += ["- 指数闸门下事件驱动仍保留整体避险（指数跌破 MA 即全清仓），与个股闸门版语义不同。"]
    return '\n'.join(lines)



async def main_async(args) -> int:
    cfg = TrendGateConfig(
        gate_mode='stock' if args.gate == 'stock' else 'index',
        rebalance_mode=args.rebalance_mode,
        exit_on_rank_drop=args.exit_on_rank_drop,
        add_tolerance=args.add_tolerance,
        top_n=args.top_n, rebalance_days=args.rebalance_days,
        commission_rate=args.commission, use_ma20_timing=not args.no_timing,
        gate_ma=args.gate_ma, gate_confirm_days=args.confirm,
        max_exposure=args.exposure, use_stock_risk=args.stock_risk,
        market=args.market, slippage=args.slippage,
        enforce_price_limits=not args.no_limit_check,
        enforce_halts=not args.no_halt_check,
    )

    use_hsi = args.market == "hk" and args.pool == "hsi"
    use_all = args.market == "cn" and args.pool == "all"
    uni_key = "hk_hsi" if use_hsi else ("all" if use_all else args.market)
    cache_key = f"{uni_key}_d{args.days}"
    hit = None
    volume = None
    if not args.no_cache:
        hit = rotation.cache_matrix(cache_key)
        uni = rotation.load_universe_cache(uni_key)
        if not (hit and uni):
            hit = None
        if hit and uni:
            universe, close, open_df = uni, hit[0], hit[1]
            volume = hit[2] if len(hit) > 2 else None
            print(f"缓存命中: 池 {len(universe)} 只, 行情 {len(close)} 日"
                  f"{'' if volume is not None else '（无 volume：停牌检查不可用，重新生成缓存可补齐）'}")

    if hit is None:
        if args.market == "cn" and args.pool == "all":
            universe = await rotation.fetch_all_a_constituents()
            print(f"A股全市场: {len(universe)} 只（含ST/北交所/次新，未过滤）")
        elif args.market == "cn":
            universe = await rotation.fetch_zz500_constituents()
            print(f"中证500成分: {len(universe)} 只")
        elif use_hsi:
            universe = await rotation.fetch_hsi_constituents()
            print(f"恒生指数成分: {len(universe)} 只")
        else:
            universe = await rotation.fetch_hk_top_amount()
            print(f"港股成交额Top{len(universe)}: {len(universe)} 只")
        close, open_df, volume = await rotation.load_close_open_volume(
            universe, args.market, args.days)
        if not args.no_cache:
            rotation.save_cache(cache_key, close, open_df, volume)
            rotation.save_universe_cache(uni_key, universe)

    # ── 闸门指数 ──
    #   index: A股=沪深300 / 港股=恒生指数（默认）
    #   ew   : 池内等权指数（用交易量 Top N 股票自造市场基准，贴合池子）
    if args.gate == "ew":
        _ret = close.pct_change().mean(axis=1).fillna(0.0)
        gate_index = (1 + _ret).cumprod()
        gate_index.index = close.index
        gate_symbol = f"池内等权指数(Top{len(universe)})"
        print(f"闸门：{gate_symbol}  MA{cfg.gate_ma}")
    elif args.gate == 'stock' and not (args.compare or args.compare_rebalance):
        gate_index = None
        gate_symbol = '个股自身'
        print(f'闸门：逐只 MA{cfg.gate_ma}')
    else:
        gate_symbol = HS300_SYMBOL if args.market == "cn" else HSI_SYMBOL
        gate_index = await _index_kline_async(gate_symbol, len(close))
        if gate_index is None:
            print(f"❌ 闸门指数 {gate_symbol} 获取失败，回测中止（fail-closed）", file=sys.stderr)
            return 1
        print(f"闸门：{gate_symbol}  MA{cfg.gate_ma}")

    # 基准指数（报告对比用）
    bench_series = None if args.gate == 'stock' else await _index_kline_async(
        "sh000905" if args.market == "cn" else HSI_SYMBOL, len(close))

    result = run_trendgate_backtest(close, open_df, gate_index, cfg, universe,
                                    volume_df=volume)
    if args.compare_rebalance:
        report = render_rebalance_comparison(close, open_df, gate_index, cfg, universe, volume)
    elif args.compare:
        report = render_comparison(close, open_df, gate_index, cfg, universe, volume)
    else:
        report = render_report(result, universe, close, bench_series, args.market, gate_symbol, pool=args.pool)

    out_dir = Path(__file__).resolve().parent.parent / "report"
    out_dir.mkdir(parents=True, exist_ok=True)
    label = (f'compare_rebalance_{args.gate}' if args.compare_rebalance
             else ('compare' if args.compare else args.gate))
    out_file = out_dir / f"trendgate_{args.market}_{label}_{datetime.now():%Y%m%d}.md"
    out_file.write_text(report, encoding="utf-8")
    print(report)
    print(f"\n📄 报告已保存: {out_file}")

    from quantrisk import data
    await data.close_async_session()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="闸门动量回测（TrendGate：rotation × 沪深300 MA20 择时闸门）")
    ap.add_argument("--market", choices=["cn", "hk"], default="cn")
    ap.add_argument("--pool", choices=["amount", "hsi", "all"], default="amount",
                    help="港股池来源（仅 --market hk）：amount=成交额Top100(legacy, 2026-10-09 否决) / "
                         "hsi=恒生指数成分（2026-10-13 推荐：gma30 累计+42.4pct 回撤-8.8pct 夏普0.99）")
    ap.add_argument("--days", type=int, default=800)
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--no-timing", action="store_true", help="关闭择时（退化为纯 rotation）")
    ap.add_argument("--top-n", type=int, default=10)
    ap.add_argument("--rebalance-days", type=int, default=20)
    ap.add_argument("--commission", type=float, default=0.0)
    ap.add_argument("--slippage", type=float, default=0.0,
                    help="单边滑点（买价×(1+s)、卖价×(1-s)）；建议 A股 0.001、港股 0.001~0.002")
    ap.add_argument("--no-limit-check", action="store_true",
                    help="关闭涨跌停不可成交约束（A股：开盘涨停买不进/跌停卖不出）")
    ap.add_argument("--no-halt-check", action="store_true",
                    help="关闭停牌不可成交约束（需 volume 矩阵；港股/A股 均适用）")
    ap.add_argument("--gate-ma", type=int, default=20, help="择时均线周期（沪深300）")
    ap.add_argument("--confirm", type=int, default=3, help="入场确认连续站上均线天数")
    ap.add_argument("--exposure", type=float, default=0.7, help="总敞口上限（0-1）")
    ap.add_argument("--stock-risk", action="store_true", help="启用个股8%%止损/15%%止盈（实测恶化回撤）")
    ap.add_argument('--compare', action='store_true', help='同一行情比较指数与个股闸门及费用敏感性')
    ap.add_argument("--compare-rebalance", action="store_true",
                    help="同一行情比较定期换仓 vs 事件驱动（同闸门、同费用口径）")
    ap.add_argument("--rebalance-mode", choices=["periodic", "event"], default="periodic",
                    help="换仓机制：periodic=每 N 日强制换仓（默认，现有行为）；"
                         "event=不强制换仓，只按卖出信号离场、买入信号加仓")
    ap.add_argument("--exit-on-rank-drop", action="store_true",
                    help="event 模式：掉出双动量前 N 也算卖出信号（默认 off=不卖）")
    ap.add_argument("--add-tolerance", type=float, default=0.05,
                    help="event 模式：持仓低于目标权重 (1-该比例) 才补足加仓（默认 0.05）")
    ap.add_argument("--gate", choices=["index", "ew", "stock"], default="index",
                    help="闸门类型：index=市场指数（A股沪深300/港股恒指，默认）；ew=池内等权指数")
    args = ap.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())