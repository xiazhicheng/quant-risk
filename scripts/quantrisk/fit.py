"""策略适配性诊断（Strategy Fit，V1.18.0）——判断一只标的适合「网格」还是「趋势」。

**为什么需要它**

四套策略的市场假设是分裂的：TrendGate/rotation/multifactor 靠**趋势延续**赚钱，
grid 靠**价格回归**赚钱。同一只股票不可能两者都适合——选错策略比选错股票更容易亏钱。

**判别框架（震荡 ←→ 趋势 是一根轴）**

核心指标是**效率比 ER（Kaufman Efficiency Ratio）**：

    ER = |收盘[-1] - 收盘[-N]| / Σ|收盘[i] - 收盘[i-1]|

- ER → 1：价格走的是一条直线（每次波动都贡献到净位移）→ **趋势型 → 适合趋势策略**
- ER → 0：价格来回震荡、净位移接近 0 → **震荡型 → 适合网格**

配合三个辅助维度：
- **年化波动**：网格的"燃料"（波动越大，网格来回赚的次数越多）
- **ADX(14)**：经典趋势强度（>25 趋势市 / <20 震荡市），与 ER 交叉验证
- **流动性**（日均成交额）：网格高频成交，流动性不足会吃价差

**双轨验证**：特征打分之外，**直接跑网格回测**对比同仓位 buy&hold——
回测超额是最硬的证据，特征分只是解释它为什么。

**重要前提**：TrendGate 是**组合策略**（需 500 只池子横截面排名选前 10），
**不能对单股使用**。本工具对单股只判断"它的走势类型适合哪类策略"，
以及"若它被选入时，趋势跟踪是否吃得开"。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import grid


@dataclass
class FitResult:
    code: str
    name: str
    market: str
    features: dict = field(default_factory=dict)
    grid_runs: list[dict] = field(default_factory=list)
    scores: dict = field(default_factory=dict)
    verdict_grid: str = ""
    verdict_trend: str = ""
    reasons: list[str] = field(default_factory=list)


def efficiency_ratio(close: pd.Series, window: int = 60) -> float:
    """Kaufman 效率比（近 window 日的滚动均值）。ER∈(0,1]，越低越震荡。"""
    c = close.dropna()
    if len(c) < window + 1:
        return float("nan")
    net = (c - c.shift(window)).abs()
    path = c.diff().abs().rolling(window).sum()
    er = (net / path).replace([np.inf, -np.inf], np.nan).dropna()
    return float(er.tail(max(window, 120)).mean()) if len(er) else float("nan")


def calc_adx_series(high: pd.Series, low: pd.Series, close: pd.Series,
                    period: int = 14) -> pd.Series:
    """ADX 序列（Wilder 平滑）。>25 趋势市，<20 震荡市。"""
    h, l, c = high.astype(float), low.astype(float), close.astype(float)
    up = h.diff()
    dn = -l.diff()
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / period, adjust=False).mean()
    pdi = 100 * pd.Series(plus_dm, index=h.index).ewm(alpha=1 / period, adjust=False).mean() / atr
    mdi = 100 * pd.Series(minus_dm, index=h.index).ewm(alpha=1 / period, adjust=False).mean() / atr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return dx.ewm(alpha=1 / period, adjust=False).mean()


def _score_span(x: float, lo: float, hi: float, full: float) -> float:
    """把 x 从 [lo, hi] 线性映射到 [0, full]（超出则截断）。"""
    if not np.isfinite(x):
        return 0.0
    return float(np.clip((x - lo) / (hi - lo), 0, 1) * full)


def analyze_fit(klines: pd.DataFrame, code: str, name: str, market: str,
                spacings: tuple[float, ...] = (0.02, 0.025),
                lower: float = 0.20, upper: float = 0.20,
                commission: float = 0.001,
                lot_size: int = 100, init_position: float = 0.5,
                initial_cash: float = 1_000_000.0) -> FitResult:
    """诊断一只标的的策略适配性。klines 需含 open/high/low/close/volume。"""
    df = klines.sort_index()
    close = df["close"].astype(float)
    n = len(close)
    if n < 130:
        raise ValueError(f"K 线不足（{n} 根，至少需 130 根）")

    # ── 特征 ──
    ret = close.pct_change().dropna()
    ann_vol = float(ret.std() * np.sqrt(252))
    er = efficiency_ratio(close, 60)
    adx_s = calc_adx_series(df["high"], df["low"], df["close"]).dropna()
    # ER 是长周期均值 → ADX 也取同尺度（近 250 日均值）才可比；另留当下值做择时参考
    adx = float(adx_s.tail(250).mean()) if len(adx_s) else float("nan")
    adx_now = float(adx_s.iloc[-1]) if len(adx_s) else float("nan")
    if "volume" in df.columns:
        # A股 volume 单位=手（×100 股）；港股=股。漏乘 100 会把成交额算小两个数量级
        vol_mult = 100.0 if market.startswith("A") else 1.0
        amount = (df["volume"].astype(float) * vol_mult * close).tail(60).mean()
    else:
        amount = float("nan")
    period_ret = float(close.iloc[-1] / close.iloc[0] - 1)
    # 趋势强度 IR = 年化收益 / 年化波动。**网格真正怕的是净位移**，而非路径曲折度：
    # ER 会被高波动压低（旭创年化波动 71%、区间 +608% 却 ER 仅 0.213），
    # 故主判据用 IR，ER 仅作"路径曲折度"的解释性指标。
    ann_ret = (1 + period_ret) ** (252 / max(n, 1)) - 1
    ir = ann_ret / ann_vol if ann_vol > 0 else float("nan")
    px = float(close.iloc[-1])
    win = close.tail(250)
    pos = float((px - win.min()) / (win.max() - win.min())) if win.max() > win.min() else float("nan")
    mdd = float(((close / close.cummax()) - 1).min())

    # ── 网格回测（跨间距，取平均超额作为硬证据）──
    runs = []
    for sp in spacings:
        cfg = grid.GridConfig(spacing=sp, lower=lower, upper=upper, commission_rate=commission)
        r = grid.run_grid_backtest(df, cfg)
        m = r.metrics
        bm = grid._metrics(grid.buy_hold(df, cfg))
        # 同仓位基准（公平口径）
        frac = float(m.get("avg_exposure", 0.5))
        p0 = float(df["open"].iloc[0])
        sh = int(cfg.initial_cash * frac / (p0 * (1 + commission)) // cfg.lot_size) * cfg.lot_size
        bench = (cfg.initial_cash - sh * p0 * (1 + commission)) + sh * close
        bm2 = grid._metrics(bench)
        runs.append({
            "spacing": sp,
            "grid_return": float(m.get("total_return", 0.0)),
            "bh_return": float(bm.get("total_return", 0.0)),
            "bh_same_return": float(bm2.get("total_return", 0.0)),
            "excess_same": float(m.get("total_return", 0.0) - bm2.get("total_return", 0.0)),
            "grid_mdd": float(m.get("max_drawdown", 0.0)),
            "avg_exposure": frac,
            "n_trades": int(m.get("n_trades", 0)),
        })
    avg_excess = float(np.mean([r["excess_same"] for r in runs]))

    # ── 最小交易单位门槛：每格预算必须买得起 1 手，否则网格根本转不起来 ──
    lot_cost = px * lot_size
    n_down_est = max(int(round(np.log(1 + upper) / np.log(1 + spacings[0]))), 1)
    per_grid_est = initial_cash * (1 - init_position) / n_down_est
    min_cash_needed = lot_cost * n_down_est / max(1 - init_position, 1e-9)
    lot_ok = per_grid_est >= lot_cost

    # ── 打分（网格适配度）──
    s_vol = _score_span(ann_vol, 0.15, 0.35, 25.0)              # 波动燃料
    # 震荡属性：|IR| 越小越震荡（网格的主场）；|IR|≥0.8 为强方向，网格必然踏空/套牢
    s_regime = _score_span(-abs(ir), -0.80, -0.30, 35.0)
    s_excess = _score_span(avg_excess, 0.0, 0.08, 25.0)         # 实测超额
    s_liq = _score_span(np.log10(amount) if np.isfinite(amount) and amount > 0 else np.nan,
                        np.log10(5e7), np.log10(5e8), 15.0)     # 流动性
    total = s_vol + s_regime + s_excess + s_liq
    if not lot_ok:
        total *= 0.5          # 门槛不满足 → 网格实盘不可执行，适配度腰斩

    verdict = ("🟢 适合网格" if total >= 70 else "🟡 中性" if total >= 45 else "🔴 不适合网格")
    if not lot_ok:
        verdict += "（主因：资金门槛不满足，非走势问题）"

    # ── 趋势适配视角（ER 高 + ADX 高 = 趋势型）──
    if abs(ir) >= 0.5 and adx >= 25:
        trend_v = "🟢 趋势型（适合趋势策略；但 TrendGate 需池内排名选入）"
    elif abs(ir) >= 0.3:
        trend_v = "🟡 偏趋势（若被 TrendGate 选中可跟随）"
    else:
        trend_v = "🔴 非趋势型（趋势策略会被反复打脸）"

    reasons = []
    if not lot_ok:
        reasons.append(f"⛔ **资金门槛不满足（决定性）**：一手 {lot_cost:,.0f} 元 > 每格预算 "
                       f"{per_grid_est:,.0f} 元（10 万本金口径）→ 网格会「一格都买不起」，"
                       f"回测成交必然为 0。**该标的走势本身可能适合网格，但资金量不够就无法执行**；"
                       f"建议本金 ≥ {min_cash_needed:,.0f} 元")
    if abs(ir) <= 0.30:
        reasons.append(f"趋势强度 |IR|={abs(ir):.2f}（年化收益 {ann_ret*100:+.1f}% ÷ 年化波动 "
                       f"{ann_vol*100:.1f}%）→ **无明确方向**，价格回归为主，是网格的菜")
    elif abs(ir) >= 0.80:
        reasons.append(f"趋势强度 |IR|={abs(ir):.2f}（年化收益 {ann_ret*100:+.1f}% ÷ 年化波动 "
                       f"{ann_vol*100:.1f}%）→ **强单边方向**，网格必然踏空或套牢")
    else:
        reasons.append(f"趋势强度 |IR|={abs(ir):.2f}（年化收益 {ann_ret*100:+.1f}% ÷ 年化波动 "
                       f"{ann_vol*100:.1f}%）→ 方向偏弱：震荡成分仍在，但需缩仓位做")
    reasons.append(f"路径曲折度 ER={er:.3f}（辅助指标：越低说明『进三退二』越频繁，"
                   f"网格可赚的来回越多；高波动会压低 ER，故不作为主判据）")
    reasons.append(f"年化波动 {ann_vol*100:.1f}%（网格燃料{'充足' if ann_vol>0.25 else '一般'}）")
    reasons.append(f"ADX 长期均值 {adx:.1f}（当下 {adx_now:.1f}）→ "
                   f"{'趋势市' if adx>25 else '震荡市' if adx<20 else '过渡'}，"
                   f"与 ER {'一致 ✓' if (er < 0.25) == (adx < 25) else '不一致（注意）'}")
    reasons.append(f"跨 {len(spacings)} 个间距平均超额 {avg_excess*100:+.2f}pp（对比同仓位 buy&hold）")
    if lot_ok:
        reasons.append(f"资金门槛 ✓：现价 {px:.2f} × {lot_size} 股 = 一手 {lot_cost:,.0f} 元，"
                       f"每格预算约 {per_grid_est:,.0f} 元（10 万本金口径）→ 买得起")

    return FitResult(
        code=code, name=name, market=market,
        features={"ann_vol": ann_vol, "er": er, "ir": ir, "ann_ret": ann_ret,
                  "adx": adx, "adx_now": adx_now, "amount_60d": amount,
                  "lot_cost": lot_cost, "per_grid_est": per_grid_est, "min_cash_needed": min_cash_needed,
                  "lot_ok": lot_ok, "lot_size": lot_size, "initial_cash": initial_cash,
                  "period_return": period_ret, "max_drawdown": mdd, "px": px,
                  "range_pos_250d": pos, "bars": n,
                  "start": str(df.index[0].date()), "end": str(df.index[-1].date())},
        grid_runs=runs,
        scores={"vol": s_vol, "regime": s_regime, "excess": s_excess, "liquidity": s_liq, "total": total},
        verdict_grid=verdict, verdict_trend=trend_v, reasons=reasons,
    )


def render_fit(res: FitResult) -> str:
    f, sc = res.features, res.scores
    amt = f["amount_60d"]
    amt_txt = f"{amt / 1e8:.2f} 亿" if np.isfinite(amt) else "数据缺失"
    er = f["er"]
    regime_txt = "震荡" if er < 0.20 else "趋势" if er > 0.35 else "混合"
    adx_txt = "趋势市" if f["adx"] > 25 else "震荡市" if f["adx"] < 20 else "过渡"
    L = [f"# 策略适配性诊断 | {res.name} {res.code}（{res.market}） | {f['start']} → {f['end']}", "",
         "## 标的特征", "", "| 特征 | 值 | 含义 |", "|:--|:--|:--|",
         f"| **趋势强度 \\|IR\\|** | **{abs(f['ir']):.2f}** | 年化收益 {f['ann_ret']*100:+.1f}% ÷ 年化波动 "
         f"{f['ann_vol']*100:.1f}% → **{'无方向（震荡）' if abs(f['ir'])<=0.3 else '偏方向' if abs(f['ir'])<0.8 else '强方向（趋势）'}** |",
         f"| 效率比 ER(60) | {er:.3f} | 路径曲折度（辅助）：越低『进三退二』越频繁 → {regime_txt} |",
         f"| ADX(14) 近250日均值 | {f['adx']:.1f} | {adx_txt}（与 ER 同尺度的长期特征） |",
         f"| ADX(14) 当前值 | {f['adx_now']:.1f} | 当下状态（择时参考） |",
         f"| 年化波动 | {f['ann_vol']*100:.1f}% | 网格燃料 |",
         f"| 日均成交额(60日) | {amt_txt} | 网格高频成交的容量 |",
         f"| 区间涨跌 | {f['period_return']*100:+.2f}% | {f['bars']} 交易日 |",
         f"| 最大回撤 | {f['max_drawdown']*100:.2f}% | 全程 |",
         f"| 250日区间位置 | {f['range_pos_250d']*100:.1f}% | 0%=区间底部 100%=顶部 |",
         f"| **一手金额** | **{f['lot_cost']:,.0f} 元** | 现价 × {f['lot_size']} 股 |",
         f"| **每格预算** | **{f['per_grid_est']:,.0f} 元** | 10 万本金口径（5 万 / 下方档数） |",
         f"| **门槛判定** | **{'✓ 可执行' if f['lot_ok'] else '⛔ 不可执行（每格买不起一手）'}** | "
         f"建议最低本金 {'—' if f['lot_ok'] else format(f['min_cash_needed'], ',.0f') + ' 元'} |", "",
         "## 网格回测（硬证据：对比同仓位 buy&hold）", "",
         "| 间距 | 网格收益 | 满仓买持 | **同仓位买持** | 超额 | 网格回撤 | 成交 | 平均仓位 |",
         "|:--|:--|:--|:--|:--|:--|:--|:--|"]
    for r in res.grid_runs:
        L.append(f"| {r['spacing']:.1%} | {r['grid_return']*100:.2f}% | {r['bh_return']*100:.2f}% | "
                 f"{r['bh_same_return']*100:.2f}% | **{r['excess_same']*100:+.2f}pp** | "
                 f"{r['grid_mdd']*100:.2f}% | {r['n_trades']} | {r['avg_exposure']*100:.1f}% |")
    L += ["", "## 适配度打分（网格视角，满分 100）", "", "| 维度 | 得分 | 满分 | 判据 |", "|:--|:--|:--|:--|",
          f"| 波动燃料 | {sc['vol']:.1f} | 25 | 年化波动 15%→35% 线性 |",
          f"| 震荡属性 | {sc['regime']:.1f} | 35 | \\|IR\\| 0.80→0.30 线性（越小越震荡） |",
          f"| 实测超额 | {sc['excess']:.1f} | 25 | 跨间距平均超额 0→+8pp |",
          f"| 流动性 | {sc['liquidity']:.1f} | 15 | 日均成交额 0.5亿→5亿 |",
          f"| **合计** | **{sc['total']:.1f}** | 100 | ≥70 适合 / 45-69 中性 / <45 不适合 |", "",
          "## 裁决", "",
          f"- **网格视角**：{res.verdict_grid}（适配度 {sc['total']:.1f}/100）",
          f"- **趋势视角**：{res.verdict_trend}", ""]
    L += ["**判据解读**"] + [f"- {r}" for r in res.reasons]
    L += ["",
          "> ⚠️ **TrendGate 是组合策略**（需 500 只池子横截面排名选前 10），**不能对单股使用**；",
          "> 本报告对单股只判断走势类型适合哪类策略。",
          "> ⚠️ 网格参数（间距）敏感性呈锯齿状（路径依赖），跨间距平均比单一间距更可信；",
          "> ⚠️ 声明：基于公开数据回测，不构成投资建议。"]
    return "\n".join(L)

def summarize(res: FitResult, spacings: tuple[float, ...] = (0.02, 0.025)) -> dict:
    """把 FitResult 压成一行摘要（供批量筛查排序/制表）。"""
    f, sc = res.features, res.scores
    runs = res.grid_runs or []
    avg_excess = float(np.mean([r["excess_same"] for r in runs])) if runs else float("nan")
    # 网格可操作参数：以下界/上界 + 首个间距给出
    sp = runs[0]["spacing"] if runs else (spacings[0] if spacings else 0.02)
    grid_ret = float(np.mean([r["grid_return"] for r in runs])) if runs else float("nan")
    bh_ret = float(np.mean([r["bh_return"] for r in runs])) if runs else float("nan")
    px = f["px"]
    return {
        "code": res.code, "name": res.name, "market": res.market,
        "px": px,
        "ir": abs(f["ir"]), "er": f["er"], "ann_vol": f["ann_vol"],
        "amount": f["amount_60d"], "period_return": f["period_return"],
        "lot_cost": f["lot_cost"], "lot_ok": f["lot_ok"],
        "min_cash_needed": f["min_cash_needed"],
        "score": sc["total"], "verdict_grid": res.verdict_grid, "verdict_trend": res.verdict_trend,
        "avg_excess": avg_excess, "spacing": sp,
        "grid_ret": grid_ret, "bh_ret": bh_ret,
        "grid_lower": px * 0.80, "grid_upper": px * 1.20,
        "kind": ("震荡" if abs(f["ir"]) <= 0.30 else "趋势" if abs(f["ir"]) >= 0.80 else "混合"),
    }


def render_screen(rows: list[dict], market: str, pool_desc: str, min_score: float = 70.0,
                  top: int = 20, skipped: list[tuple[str, str]] | None = None) -> str:
    """批量筛查报告：按适配度排序，分类列出网格候选 / 不适合及原因。"""
    skipped = skipped or []
    n = len(rows)
    # 候选：适配度达标 + 门槛满足 + **网格绝对收益为正**（否则"超额为正但亏钱"也会混进来）
    cand = [r for r in rows if r["score"] >= min_score and r["lot_ok"]
            and (not np.isfinite(r.get("grid_ret", np.nan)) or r["grid_ret"] > 0)]
    mid = [r for r in rows if 45 <= r["score"] < min_score and r["lot_ok"]]
    bad_trend = [r for r in rows if r["kind"] == "趋势" and r not in cand]
    bad_lot = [r for r in rows if not r["lot_ok"]]
    bad_liq = [r for r in rows if r["lot_ok"] and np.isfinite(r["amount"]) and r["amount"] < 5e7
               and r not in cand]
    cand.sort(key=lambda r: -r["score"])

    L = [f"# 批量策略适配性筛查 | {market} | {pool_desc}", "",
         "## 统计", "", "| 项 | 数量 |", "|:--|:--|",
         f"| 扫描标的 | {n + len(skipped)} |",
         f"| 有效诊断 | {n} |",
         f"| 数据不足跳过 | {len(skipped)} |",
         f"| **🟢 网格候选（适配≥{min_score:.0f} 且门槛满足）** | **{len(cand)}** |",
         f"| 🟡 中性（45~{min_score:.0f}） | {len(mid)} |",
         f"| 🔴 趋势型（不适合网格） | {len(bad_trend)} |",
         f"| 🔴 资金门槛不足 | {len(bad_lot)} |",
         f"| 🔴 流动性不足（日均<0.5亿） | {len(bad_liq)} |",
         f"| ⚪ 适配达标但网格绝对亏损（已剔除出候选） | "
         f"{len([r for r in rows if r['score'] >= min_score and r['lot_ok'] and np.isfinite(r.get('grid_ret', np.nan)) and r['grid_ret'] <= 0])} |", "",
         f"## 🟢 网格候选池（按适配度排序，前 {top}）", "",
         "| # | 标的 | 代码 | 现价 | \\|IR\\| | 年化波动 | 日均成交额 | 适配分 | 网格收益 | 网格区间(±20%) | 一手金额 | 跨间距超额 |",
         "|:--|:--|:--|:--|:--|:--|:--|:--|:--|:--|:--|"]
    for i, r in enumerate(cand[:top], 1):
        amt = f"{r['amount']/1e8:.2f}亿" if np.isfinite(r["amount"]) else "数据缺失"
        L.append(f"| {i} | {r['name']} | {r['code']} | {r['px']:.3f} | {r['ir']:.2f} | "
                 f"{r['ann_vol']*100:.0f}% | {amt} | **{r['score']:.1f}** | "
                 f"{r['grid_ret']*100:+.1f}% | "
                 f"{r['grid_lower']:.3f} ~ {r['grid_upper']:.3f} | {r['lot_cost']:,.0f} | "
                 f"{r['avg_excess']*100:+.2f}pp |")
    if cand:
        r0 = cand[0]
        L += ["", f"**首选**：{r0['name']}（{r0['code']}）现价 {r0['px']:.3f}，"
                  f"网格区间 {r0['grid_lower']:.3f} ~ {r0['grid_upper']:.3f}（±20%），"
                  f"间距建议 2%~2.5%，一手 {r0['lot_cost']:,.0f} 元；"
                  f"跨间距平均超额 {r0['avg_excess']*100:+.2f}pp（对比同仓位 buy&hold）"]

    # 趋势型（含正确解读）
    L += ["", "## 🔴 趋势型标的（**不适合网格，但不是「推荐用 TrendGate 交易它」**）", ""]
    if bad_trend:
        L += ["| 标的 | 代码 | \\|IR\\| | 区间涨跌 | 说明 |", "|:--|:--|:--|:--|:--|"]
        for r in sorted(bad_trend, key=lambda x: -x["ir"])[:top]:
            L.append(f"| {r['name']} | {r['code']} | {r['ir']:.2f} | {r['period_return']*100:+.1f}% | "
                     f"单边方向为主，网格会踏空/套牢 |")
    else:
        L.append("- （无）")
    L += ["", "> ⚠️ **重要**：TrendGate 是**组合策略**（需 500 只池子横截面排名选前 10），",
          "> **不能对单股使用**。趋势型标签的正确含义是「**它不适合做网格**」；",
          "> 若它恰在中证500池内且被双动量选中，TrendGate 会自行持有——这不需要你单独操作。", ""]
    L += ["## 🔴 资金门槛不足（每格买不起一手）", ""]
    if bad_lot:
        L += ["| 标的 | 代码 | 现价 | 一手金额 | 建议最低本金 |", "|:--|:--|:--|:--|:--|"]
        for r in sorted(bad_lot, key=lambda x: -x["lot_cost"])[:top]:
            L.append(f"| {r['name']} | {r['code']} | {r['px']:.2f} | {r['lot_cost']:,.0f} | "
                     f"{r['min_cash_needed']:,.0f} |")
    else:
        L.append("- （无）")

    if skipped:
        L += ["", "## ⚠️ 数据不足跳过", "",
              "| 代码 | 原因 |", "|:--|:--|"]
        for code, why in skipped[:top]:
            L.append(f"| {code} | {why} |")

    L += ["", "## 使用说明（务必先读）", "",
          "1. **这是「历史特征筛选」，不是「走势预测」**：|IR|/ER 由过去 N 日算出，",
          "   已实测**没有预测未来走势类型的能力**（见 `backtest_adaptive.py`）→",
          "   **不要**据此做「这只票以后会震荡/趋势」的判断，只用它筛掉明显不适合网格的标的。",
          "2. **事前可知的三件事才是硬约束**：年化波动（网格燃料）、流动性（成交容量）、",
          "   一手金额（资金门槛）——这三项不会因为你看不看它而改变。",
          "3. **正确用法**：把 🟢 候选池作为网格的**备选标的池**，再按自己的资金规模、",
          "   分散需求从中挑几只长期做；趋势型标的交给 TrendGate 的池内选股，不必手动干预。",
          "4. 网格间距**不要用回测最优值**（敏感性呈锯齿状＝路径拟合），用 2%~2.5%。", "",
          "> ⚠️ 声明：基于公开数据回测筛选，不构成投资建议。"]
    return "\n".join(L)
