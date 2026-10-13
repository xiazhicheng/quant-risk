#!/usr/bin/env python
"""网格交易回测 CLI（宽基 ETF 等比网格）。

用法:
  uv run scripts/backtest_grid.py --code 510500 --days 800
  uv run scripts/backtest_grid.py --code 510300 --spacing 0.01 --init-position 0.3
  uv run scripts/backtest_grid.py --code 510500 --lower 0.20 --upper 0.20 --breakout stop

关键参数:
  --spacing  每格间距（等比，核心参数，默认 1.5%）
  --lower/--upper  网格下/上界（相对首日开盘价）
  --init-position  初始仓位（默认 0.5）
  --commission  单边费率（ETF 免印花税，默认 0.02%）
  --optimistic  同日先涨后跌（乐观）；默认先跌后涨（保守）
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from quantrisk import data, grid
from quantrisk.rotation import _metrics

ETF_PRESETS = {
    "510500": "中证500ETF（上交所）", "510300": "沪深300ETF（上交所）",
    "159915": "创业板ETF（深交所）", "512100": "中证1000ETF（上交所）",
    "518880": "黄金ETF（上交所）", "513100": "纳指ETF（上交所）",
    # 港股（5 位代码，走港股接口）
    "02800": "盈富基金（恒指ETF）", "02828": "恒生中国企业ETF",
    "03033": "南方恒生科技ETF", "03067": "安硕恒生科技ETF",
}


def _bh_fraction(df: pd.DataFrame, frac: float, cfg: grid.GridConfig) -> pd.Series:
    """按指定仓位比例买入持有（用于公平基准：与网格平均仓位对齐）。"""
    p0 = float(df["open"].iloc[0])
    shares = int(cfg.initial_cash * frac / (p0 * (1 + cfg.commission_rate)) // cfg.lot_size) * cfg.lot_size
    cash = cfg.initial_cash - shares * p0 * (1 + cfg.commission_rate)
    return cash + shares * df["close"]


def _fmt_pct(x) -> str:
    return f"{x * 100:.2f}%" if x is not None and not pd.isna(x) else "—"


def render(code: str, name: str, df: pd.DataFrame, res: grid.GridResult,
           bh_full: pd.Series, bh_same: pd.Series) -> str:
    cfg = res.config
    m = res.metrics
    mb, mbs = _metrics(bh_full), _metrics(bh_same)
    p0, c1 = float(df["open"].iloc[0]), float(df["close"].iloc[-1])
    n = len(df)

    L = [f"# 网格交易回测 | {name} {code} | {df.index[0].date()} → {df.index[-1].date()}", "",
         "## 参数", "", "| 参数 | 值 |", "|:--|:--|",
         f"| 标的 | {name}（{code}） |",
         f"| 区间 | {df.index[0].date()} → {df.index[-1].date()}（{n} 交易日） |",
         f"| 首日开盘 → 末日收盘 | {p0:.3f} → {c1:.3f}（{c1/p0-1:+.2%}） |",
         f"| 网格类型 | 等比网格，间距 {cfg.spacing:.2%} |",
         f"| 区间 | 下界 -{cfg.lower:.0%} / 上界 +{cfg.upper:.0%}（相对 P0={p0:.3f}） |",
         f"| 档位数 | {len(grid.grid_levels(p0, cfg))} 档（由间距派生） |",
         f"| 初始仓位 | {cfg.init_position:.0%} |",
         f"| 每格资金 | 现金池 ÷ 下方档数（等额） |",
         f"| 跌破下界 | {'清仓止损' if cfg.breakout_action == 'stop' else '满仓持有'} |",
         f"| 同日撮合顺序 | {'先涨后跌（乐观）' if cfg.optimistic else '先跌后涨（保守）'} |",
         f"| 交易成本 | {cfg.commission_rate*100:.3f}% / 边（ETF 免印花税） |", "",
         "## 绩效（网格 vs 两种基准）", "",
         "| 指标 | 网格 | 满仓 buy&hold | **同仓位 buy&hold** |", "|:--|:--|:--|:--|",
         f"| 累计收益 | {_fmt_pct(m.get('total_return'))} | {_fmt_pct(mb.get('total_return'))} | {_fmt_pct(mbs.get('total_return'))} |",
         f"| 年化收益 | {_fmt_pct(m.get('annual_return'))} | {_fmt_pct(mb.get('annual_return'))} | {_fmt_pct(mbs.get('annual_return'))} |",
         f"| 最大回撤 | {_fmt_pct(m.get('max_drawdown'))} | {_fmt_pct(mb.get('max_drawdown'))} | {_fmt_pct(mbs.get('max_drawdown'))} |",
         f"| 夏普比率 | {m.get('sharpe', 0):.3f} | {mb.get('sharpe', 0):.3f} | {mbs.get('sharpe', 0):.3f} |",
         f"| 年化波动 | {_fmt_pct(m.get('annual_vol'))} | {_fmt_pct(mb.get('annual_vol'))} | {_fmt_pct(mbs.get('annual_vol'))} |", "",
         f"> 网格平均仓位 {m.get('avg_exposure', 0)*100:.1f}%；**同仓位基准**按该比例买入持有（公平基准：",
         "> 网格平均只用了部分资金，拿满仓 buy&hold 比会低估它的选时贡献）。", "",
         "## 网格专属统计", "", "| 统计 | 值 |", "|:--|:--|",
         f"| 成交次数 | {int(m.get('n_trades', 0))}（买 {res.n_buy} / 卖 {res.n_sell}） |",
         f"| 平均仓位 | {m.get('avg_exposure', 0)*100:.1f}% |",
         f"| 满仓天数 | {res.full_days}（{m.get('full_days_ratio', 0)*100:.1f}%，跌穿下界后满仓挨打） |",
         f"| 空仓天数 | {res.empty_days}（{m.get('empty_days_ratio', 0)*100:.1f}%，涨穿上界后卖光踏空） |", "",
         "## 关键对照", "",
         f"- 网格 vs **同仓位** buy&hold：{(m.get('total_return', 0) - mbs.get('total_return', 0))*100:+.2f}pp"
         " ← 网格「低买高卖」是否创造价值的判据",
         f"- 网格 vs **满仓** buy&hold：{(m.get('total_return', 0) - mb.get('total_return', 0))*100:+.2f}pp"
         " ← 与满仓比是另一种口径（网格天生仓位更低）",
         f"- 回撤对比（网格 vs 同仓位）：{_fmt_pct(m.get('max_drawdown'))} vs {_fmt_pct(mbs.get('max_drawdown'))}"
         " ← 网格越跌越买，下行暴露反而更大", ""]

    # 分年
    L += ["## 分年表现（网格 vs 标的）", "", "| 年份 | 网格 | 标的 | 超额 | 占优方 |", "|:--|:--|:--|:--|:--|"]
    g, cl = res.equity_curve, df["close"]
    for y in sorted(set(g.index.year)):
        gs, bs = g[g.index.year == y], cl[cl.index.year == y]
        if len(gs) < 2 or len(bs) < 2:
            continue
        gr, br = gs.iloc[-1] / gs.iloc[0] - 1, bs.iloc[-1] / bs.iloc[0] - 1
        who = "网格" if gr > br else "标的（趋势）"
        L.append(f"| {y} | {gr*100:.2f}% | {br*100:.2f}% | {(gr-br)*100:+.2f}pp | {who} |")
    L += ["", "> 网格的主场是**震荡/下跌年**，单边大涨年必然跑输（半仓 + 不断止盈）。", ""]

    # 费用敏感性
    L += ["## 费用敏感性", "", "| 单边费率 | 累计收益 | 最大回撤 | 成交次数 |", "|:--|:--|:--|:--|"]
    for comm in (0.0, 0.0002, 0.0005, 0.001):
        c = grid.GridConfig(**{**cfg.__dict__, "commission_rate": comm})
        r = grid.run_grid_backtest(df, c)
        L.append(f"| {comm*100:.3f}% | {r.metrics['total_return']*100:.2f}% | "
                 f"{r.metrics['max_drawdown']*100:.2f}% | {int(r.metrics['n_trades'])} |")
    L += ["", "> ⚠️ 网格是**高频交易**策略，费率敏感；ETF 免印花税是其适合网格的重要原因。", "",
          "> ⚠️ 声明：免费公开数据源（腾讯）回测，日线 low/high 撮合无法还原盘中顺序（"
          "同日多档触发按保守顺序处理），未含滑点。不构成投资建议。"]
    return "\n".join(L)


async def main_async(args) -> int:
    # 港股 5 位数字代码 → 港股接口（ETF 如 02800 盈富基金）；其余走 A股接口
    is_hk = len(args.code) == 5
    if is_hk:
        rows = await data.hk_kline_async(args.code, "day", count=args.days)
    else:
        rows = await data.cn_stock_kline_tencent_async(args.code, days=args.days)
    if not rows:
        print(f"❌ {args.code} 无 K 线数据", file=sys.stderr)
        return 1
    df = pd.DataFrame.from_records(rows)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()

    cfg = grid.GridConfig(
        spacing=args.spacing, lower=args.lower, upper=args.upper,
        init_position=args.init_position, n_grids=args.max_grids,
        commission_rate=args.commission, breakout_action=args.breakout,
        optimistic=args.optimistic,
    )
    res = grid.run_grid_backtest(df, cfg)
    bh_full = grid.buy_hold(df, cfg)
    bh_same = _bh_fraction(df, res.metrics.get("avg_exposure", 0.5), cfg)

    name = ETF_PRESETS.get(args.code, "ETF")
    if is_hk:
        name += "（港股）"
    report = render(args.code, name, df, res, bh_full, bh_same)

    out_dir = Path(__file__).resolve().parent.parent / "report"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"grid_{args.code}_{datetime.now():%Y%m%d}.md"
    out_file.write_text(report, encoding="utf-8")
    print(report)
    print(f"\n📄 报告已保存: {out_file}")

    await data.close_async_session()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="网格交易回测（宽基 ETF 等比网格）")
    ap.add_argument("--code", default="510500",
                    help="ETF 代码：A股 6 位（510500 中证500ETF）或港股 5 位（02800 盈富基金 / 03033 南方恒生科技）")
    ap.add_argument("--days", type=int, default=800)
    ap.add_argument("--spacing", type=float, default=0.015, help="每格间距（等比）")
    ap.add_argument("--lower", type=float, default=0.15, help="网格下界（相对 P0）")
    ap.add_argument("--upper", type=float, default=0.15, help="网格上界（相对 P0）")
    ap.add_argument("--init-position", type=float, default=0.5, help="初始仓位")
    ap.add_argument("--max-grids", type=int, default=20, help="档数上限保护")
    ap.add_argument("--commission", type=float, default=0.0002, help="单边费率")
    ap.add_argument("--breakout", choices=["hold", "stop"], default="hold", help="跌破下界处置")
    ap.add_argument("--optimistic", action="store_true", help="同日先涨后跌（乐观）")
    args = ap.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())