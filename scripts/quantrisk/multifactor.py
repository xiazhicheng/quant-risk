"""多因子选股策略（A股中证500 / 港股成交额Top100）——V1.14.0 新增。

策略规格（2026-10-09 用户确认，与 rotation 轮动策略并列的第二套策略）:
1. 股票池: A股=中证500成分（复用 rotation.fetch_zz500_constituents）；港股=成交额Top100（复用 rotation.fetch_hk_top_amount）
2. 硬过滤（每调仓日，用 t-1 数据）: 停牌 / ST·退 / 亏损 / 20日均成交额 < 1000万
   - 亏损: A股用东财业绩报表 RPT_LICO_FN_CPD 最新可用报告期归母净利润 < 0 剔除；
     报告期 + 120 天披露滞后防未来函数；港股财务接口脏（只有2008旧数据）→ **fail-open 不过滤，诚实标注**
3. 因子合成排名（权重 55/25/20，全池横截面 rank 归一化 0~1）:
   - 20日趋势 55%: 近20日动量（rank 正向，动量越高分越高）
   - 20日波动率 25%: 近20日日收益标准差（rank **负向**，低波动加分，与三档仓位同向）
   - 20日日均成交额 20%: rank 正向（流动性好加分）
   - 得分 = 0.55×rank20 + 0.25×(1-rank波动) + 0.20×rank成交额
4. 选股: 得分降序取前 top_n=10
5. 仓位: 按入选股 20日波动率三等分档位——低波动档权重系数 1.0（标准）/ 中 0.7 / 高 0.4；
   w_i = (1/N)×系数，买入金额 = 总资产×w_i，100股整数倍，剩余现金留存
6. 调仓: 每 rebalance_days=20 交易日
7. 择时: 沪深300 收盘 < MA20 → 空仓（t-1 评估，t 开盘清仓，fail-closed 缺失则空仓）
8. 个股风控（t-1 收盘评估 → t 开盘执行）:
   - 止损: 现价 ≤ 成本×0.92（-8%）→ 卖出
   - 止盈: 持仓期最高收盘价 ≥ 成本×1.15 且 从该峰值回撤 ≥5% → 卖出
9. 预热: warmup_days=120；无前瞻: 所有决策用 t-1 已收盘数据，t 开盘成交，t 收盘计市值
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from . import data
from .rotation import (
    WARMUP_DAYS, REBALANCE_DAYS, TOP_N, LOT_SIZE,
    fetch_hk_top_amount, fetch_zz500_constituents, load_close_open_volume,
    cache_matrix, save_cache, _metrics,
)

# ─────────────────────────────────────────────────────────────
# 配置
# ─────────────────────────────────────────────────────────────
MIN_AMOUNT_20D = 10_000_000        # 20日均成交额过滤阈值（元）
FACTOR_W = {"trend": 0.55, "vol": 0.25, "amount": 0.20}
TIER_WEIGHT = {0: 1.0, 1: 0.7, 2: 0.4}     # 波动率低/中/高档位权重系数
STOP_LOSS = 0.08                    # 8% 止损
TAKE_PROFIT = 0.15                  # 15% 浮盈启动保护
TAKE_PROFIT_DRAWDOWN = 0.05         # 峰值回撤 5% 止盈
DISCLOSURE_LAG_DAYS = 120           # 财报披露滞后（覆盖年报/一季报 4月底 最迟披露）
HS300_SYMBOL = "sh000300"           # 沪深300 指数（腾讯）

# ─────────────────────────────────────────────────────────────
# 财务：净利润表（A股）
# ─────────────────────────────────────────────────────────────
async def fetch_net_profit_table(report_dates: list[str]) -> pd.DataFrame:
    """拉取 A股各报告期归母净利润（东财 RPT_LICO_FN_CPD，各期翻页全市场）。

    返回 DataFrame(index=报告期 'YYYY-MM-DD'，columns=股票代码，值=归母净利润/元)。
    某期失败返回空帧（fail-open，不拦截）。
    """
    frames: dict[str, dict[str, float]] = {}
    for rd in report_dates:
        code2np: dict[str, float] = {}
        pn = 1
        while True:
            d = await data.retry_async(max_attempts=3, delay=1.0)(data._get_json)(
                data.DATACENTER_URL, params={
                    "reportName": "RPT_LICO_FN_CPD",
                    "columns": "SECURITY_CODE,PARENT_NETPROFIT",
                    "filter": f"(REPORTDATE='{rd}')",
                    "pageNumber": str(pn), "pageSize": "500",
                    "sortColumns": "SECURITY_CODE", "sortTypes": "1",
                    "source": "WEB", "client": "WEB"})
            rows = ((d or {}).get("result") or {}).get("data") or []
            if not rows:
                break
            for r in rows:
                code = str(r.get("SECURITY_CODE", ""))
                np_val = r.get("PARENT_NETPROFIT")
                if code and np_val not in (None, "-", ""):
                    try:
                        code2np[code] = float(np_val)
                    except (TypeError, ValueError):
                        pass
            if len(rows) < 500:
                break
            pn += 1
            if pn > 40:
                break
        if code2np:
            frames[rd] = code2np
            print(f"[业绩表] {rd}: {len(code2np)} 只")
        else:
            print(f"[业绩表] {rd}: 无数据（fail-open）")
    if not frames:
        return pd.DataFrame()
    return pd.DataFrame(frames).T  # index=报告期, columns=代码


def latest_net_profit_on(profit_df: pd.DataFrame, decision_date, universe_codes) -> pd.Series:
    """调仓决策日可用的最新净利润（防未来函数：报告期+披露滞后 ≤ 决策日）。

    返回 Series(代码→净利润)，无可用报告的股票返回 NaN（fail-open 不过滤）。
    """
    if profit_df is None or profit_df.empty:
        return pd.Series(np.nan, index=universe_codes)
    idx = pd.to_datetime(profit_df.index)
    available = idx[idx + pd.Timedelta(days=DISCLOSURE_LAG_DAYS) <= pd.Timestamp(decision_date)]
    if len(available) == 0:
        return pd.Series(np.nan, index=universe_codes)
    latest = profit_df.loc[str(available[-1].date())]
    return latest.reindex(universe_codes)


# ─────────────────────────────────────────────────────────────
# 因子
# ─────────────────────────────────────────────────────────────
def _amount_matrix(close: pd.DataFrame, volume: pd.DataFrame, lot: int) -> pd.DataFrame:
    """成交额近似矩阵: amount ≈ volume × lot × close。

    A股腾讯 volume 单位=手（lot=100）；港股 volume=股（lot=1）。
    """
    vol = volume.reindex_like(close).astype(float)
    return vol * lot * close


def multifactor_scores(close: pd.DataFrame, amount: pd.DataFrame,
                       window: int = 20,
                       weights: dict[str, float] | None = None) -> pd.DataFrame:
    """三因子合成得分矩阵（index=日期, columns=代码, 0~1）。

    - trend: 近 window 日动量（正）; vol: 近 window 日收益波动（负→1-rank）;
      amount: 近 window 日均成交额（正）
    - 每个因子逐行横截面 rank(pct=True) 归一化 0~1；三者皆有效才给分。
    """
    w = weights or FACTOR_W
    closes = close.astype(float).sort_index()
    amt = amount.astype(float).sort_index()
    daily_ret = closes.pct_change()
    mom = closes.pct_change(window)                    # 20日趋势/动量
    vol = daily_ret.rolling(window).std()              # 20日波动率
    amt_w = amt.rolling(window).mean()                 # 20日均成交额

    rank_mom = mom.rank(axis=1, pct=True)
    rank_vol_neg = (1 - vol.rank(axis=1, pct=True))    # 低波动加分
    rank_amt = amt_w.rank(axis=1, pct=True)

    score = w["trend"] * rank_mom + w["vol"] * rank_vol_neg + w["amount"] * rank_amt
    score = score.where(mom.notna() & vol.notna() & amt_w.notna())
    return score


def liquidity_ok(close: pd.DataFrame, amount: pd.DataFrame, decision_date, min_amount: float = MIN_AMOUNT_20D) -> pd.Series:
    """决策日流动性过滤: 20日均成交额 ≥ 阈值（布尔 Series，代码→bool）。"""
    amt = amount.astype(float).sort_index()
    amt20 = amt.rolling(20).mean()
    if decision_date not in amt20.index:
        return pd.Series(False, index=close.columns)
    row = amt20.loc[decision_date]
    ok = (row >= min_amount) & row.notna()
    return ok.fillna(False)


def not_suspended(close: pd.DataFrame, volume: pd.DataFrame, decision_date) -> pd.Series:
    """决策日停牌过滤: 当日有成交（volume>0 且 close 非 NaN）。"""
    if decision_date not in close.index or decision_date not in volume.index:
        return pd.Series(False, index=close.columns)
    c = close.loc[decision_date]
    v = volume.loc[decision_date]
    return (c.notna() & (v.fillna(0) > 0))


def not_st(close: pd.DataFrame, universe: list[dict]) -> pd.Series:
    """ST/*ST/退 过滤（用东财当前名称近似——历史 ST 状态不可得，见 ponytail 注释）。"""
    name_map = {u["code"]: u.get("name", "") for u in universe}
    out = {}
    for code in close.columns:
        name = name_map.get(code, "")
        bad = ("ST" in name) or ("退" in name) or ("*" in name)
        out[code] = not bad
    return pd.Series(out, index=close.columns)


def select_portfolio(score_row: pd.Series, close: pd.DataFrame, amount: pd.DataFrame,
                     volume: pd.DataFrame, universe: list[dict], net_profit: pd.Series | None,
                     decision_date, top_n: int = TOP_N) -> pd.Series:
    """调仓决策：硬过滤 → 得分降序取前 top_n。返回 Series(代码→得分)。"""
    liq = liquidity_ok(close, amount, decision_date)
    sus = not_suspended(close, volume, decision_date)
    st = not_st(close, universe)

    keep = liq & sus & st
    if net_profit is not None and net_profit.notna().any():
        keep &= (net_profit.reindex(close.columns) > 0).fillna(True)   # 净利润缺失 fail-open
    row = score_row.dropna()
    eligible = row[keep.reindex(row.index).fillna(False)]
    return eligible.sort_values(ascending=False).head(top_n)


def volatility_tier(close: pd.DataFrame, codes: list[str], decision_date, n_tiers: int = 3) -> dict[str, int]:
    """按决策日可见的 20日实现波动率把入选股票三等分档位（0=低波动...2=高波动）。"""
    if not codes:
        return {}
    daily_ret = close.astype(float).pct_change()
    vol = daily_ret.rolling(20).std()
    if decision_date not in vol.index:
        return {c: 0 for c in codes}
    row = vol.loc[decision_date].reindex(codes)
    ranked = row.rank(method="first")          # 1..N（NaN 排名 NaN）
    n = len(codes)
    tier = {}
    for c in codes:
        r = ranked.get(c, np.nan)
        if pd.isna(r):
            tier[c] = 0
        else:
            frac = (r - 1) / max(n, 1)         # 0..1
            tier[c] = min(int(frac * n_tiers), n_tiers - 1) if n_tiers > 1 else 0
    return tier


# ─────────────────────────────────────────────────────────────
# 回测
# ─────────────────────────────────────────────────────────────
@dataclass
class MultiFactorConfig:
    rebalance_days: int = REBALANCE_DAYS
    top_n: int = TOP_N
    warmup_days: int = WARMUP_DAYS
    lot_size: int = LOT_SIZE
    initial_cash: float = 1_000_000.0
    commission_rate: float = 0.0
    stop_loss: float = STOP_LOSS
    take_profit: float = TAKE_PROFIT
    take_profit_drawdown: float = TAKE_PROFIT_DRAWDOWN
    use_ma20_timing: bool = True
    name: str = "multifactor"


@dataclass
class MultiFactorResult:
    config: MultiFactorConfig
    equity_curve: pd.Series
    holdings: pd.DataFrame
    trades: list[dict]
    rebalance_dates: list
    universe: list[dict]
    metrics: dict[str, float] = field(default_factory=dict)


def run_multifactor_backtest(
    close: pd.DataFrame, open_df: pd.DataFrame, volume: pd.DataFrame,
    hs300: pd.Series | None, net_profit: pd.DataFrame | None,
    config: MultiFactorConfig | None = None, universe: list[dict] | None = None,
) -> MultiFactorResult:
    """主回测循环。无前瞻时序：
      调仓日 t: t-1 收盘数据过滤+因子选股 → t 开盘价成交
      每日 t:  t-1 收盘评估择时/止损/止盈 → t 开盘执行；t 收盘计市值
    """
    if config is None:
        config = MultiFactorConfig()
    close = close.astype(float).sort_index()
    open_df = open_df.astype(float).sort_index()
    volume = volume.astype(float).sort_index()
    amount = _amount_matrix(close, volume, config.lot_size)

    scores = multifactor_scores(close, amount)
    dates = list(close.index)
    if len(dates) <= config.warmup_days + 1:
        raise ValueError(f"数据不足: 需要 > warmup({config.warmup_days})，实际 {len(dates)}")

    # 沪深300 MA20（对齐回测日期索引）
    hs300_ma20: pd.Series | None = None
    if config.use_ma20_timing and hs300 is not None and len(hs300) > 20:
        hs300 = hs300.sort_index()
        hs300_ma20 = hs300.rolling(20).mean()

    cash = config.initial_cash
    positions: dict[str, dict] = {}        # code -> {"shares": int, "cost": float, "peak": float}
    equity_curve: dict = {}
    holdings_rows: dict = {}
    trades: list[dict] = []

    code_cols = list(close.columns)
    rebalance_set = set(dates[config.warmup_days:: config.rebalance_days])

    def market_ok(t_prev) -> bool:
        if not config.use_ma20_timing or hs300_ma20 is None:
            return True
        if t_prev not in hs300.index or t_prev not in hs300_ma20.index:
            return False                        # fail-closed: 数据缺失 → 空仓
        c, m = hs300.loc[t_prev], hs300_ma20.loc[t_prev]
        if pd.isna(c) or pd.isna(m):
            return False
        return float(c) >= float(m)

    for i in range(config.warmup_days, len(dates)):
        t = dates[i]
        t_prev = dates[i - 1] if i > 0 else t
        open_row = open_df.loc[t]

        # ── 1) 择时 + 风控：t-1 收盘评估 → t 开盘卖出 ──
        ok = market_ok(t_prev)
        if positions and not ok:
            for code, pos in positions.items():
                if code in open_row.index and not pd.isna(open_row[code]):
                    cash += pos["shares"] * float(open_row[code]) * (1 - config.commission_rate)
            positions = {}
            trades.append({"date": str(t.date()), "action": "timing_close", "note": "沪深300 < MA20 清仓"})
        elif positions:
            close_prev = close.loc[t_prev]
            to_sell = []
            for code, pos in positions.items():
                if code not in close_prev.index or pd.isna(close_prev[code]):
                    continue
                px = float(close_prev[code])
                pnl = px / pos["cost"] - 1.0
                if pnl <= -config.stop_loss:
                    to_sell.append((code, f"止损 {pnl*100:.1f}%"))
                elif pos["peak"] >= pos["cost"] * (1 + config.take_profit) \
                        and px <= pos["peak"] * (1 - config.take_profit_drawdown):
                    to_sell.append((code, f"止盈回撤 {pnl*100:.1f}%"))
            for code, note in to_sell:
                if code in open_row.index and not pd.isna(open_row[code]):
                    cash += positions[code]["shares"] * float(open_row[code]) * (1 - config.commission_rate)
                    positions.pop(code)
                    trades.append({"date": str(t.date()), "action": "sell", "code": code, "note": note})

        # ── 2) 调仓日：t-1 选股 → t 开盘建仓（旧仓先在开盘全平）──
        if t in rebalance_set and ok:
            t_prev_ser = pd.Timestamp(t_prev)
            np_ser = latest_net_profit_on(net_profit, t_prev_ser, code_cols) if net_profit is not None else None
            score_row = scores.loc[t_prev]
            target = select_portfolio(score_row, close, amount, volume, universe or [],
                                      np_ser, t_prev, config.top_n)
            # 平旧仓
            for code, pos in positions.items():
                if code in open_row.index and not pd.isna(open_row[code]):
                    cash += pos["shares"] * float(open_row[code]) * (1 - config.commission_rate)
            positions = {}
            if not target.empty:
                tier = volatility_tier(close, list(target.index), t_prev)
                N = len(target)
                assets = cash
                for code in target.index:
                    w = TIER_WEIGHT.get(tier.get(code, 0), 1.0) / N
                    budget = assets * w
                    px = open_row.get(code, np.nan)
                    if pd.isna(px) or float(px) <= 0:
                        continue
                    shares = int(budget / float(px) // config.lot_size) * config.lot_size
                    if shares <= 0:
                        continue
                    cost = shares * float(px) * (1 + config.commission_rate)
                    if cost > cash:
                        shares = int(cash / (float(px) * (1 + config.commission_rate)) // config.lot_size) * config.lot_size
                        if shares <= 0:
                            continue
                        cost = shares * float(px) * (1 + config.commission_rate)
                    cash -= cost
                    positions[code] = {"shares": shares, "cost": float(px), "peak": float(px)}
                trades.append({
                    "date": str(t.date()), "decision_date": str(t_prev.date()),
                    "action": "rebalance",
                    "target": [(c, tier.get(c, 0)) for c in target.index],
                    "positions": {c: p["shares"] for c, p in positions.items()},
                    "cash": round(cash, 2),
                })

        # ── 3) 每日记账：t 收盘价计市值 + 更新峰值 ──
        close_row = close.loc[t]
        mv = cash
        for code, pos in positions.items():
            if code in close_row.index and not pd.isna(close_row[code]):
                px = float(close_row[code])
                mv += pos["shares"] * px
                pos["peak"] = max(pos["peak"], px)
        equity_curve[t] = mv
        holdings_rows[t] = {"_cash_": cash, **{c: p["shares"] for c, p in positions.items()}}

    eq = pd.Series(equity_curve).sort_index()
    holdings = pd.DataFrame.from_dict(holdings_rows, orient="index")
    if "_cash_" in holdings.columns:
        holdings = holdings.drop(columns=["_cash_"])
    holdings = holdings.fillna(0).astype(int)
    result = MultiFactorResult(
        config=config, equity_curve=eq, holdings=holdings,
        trades=trades,
        rebalance_dates=sorted(rebalance_set.intersection(eq.index)),
        universe=universe or [],
    )
    result.metrics = _metrics(eq)
    return result