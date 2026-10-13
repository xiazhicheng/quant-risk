"""市场轮动选股策略（A股中证500 / 港股成交额Top100 双市场）。

策略规格（2026-09-28 用户确认）:
1. 股票池
   - A股: 中证500成分股（000905.SH, 东财板块 BK0701, 全量 500 只）
   - 港股: 东财港股按成交额(f6)降序 Top100（过滤 ETF/基金等 f100="-" 标的，
     类比中证500的"中盘流动性好"定位）
2. 综合得分（每交易日收盘后横截面排名）:
   - 近20日涨跌幅 pct_change(20) 全池横向排名归一化 0~1
   - 近60日涨跌幅 pct_change(60) 全池横向排名归一化 0~1
   - 综合得分 = 0.5×近20日排名分 + 0.5×近60日排名分
3. 选股规则:
   - 只取综合得分 >= min_score(0.65) 的股票
   - 合格股票按综合得分降序取前 top_n(10) 只
   - 无前瞻性: 选股所用涨跌幅只用到"上一已收盘交易日"的行情，调仓日当天不偷看收盘价
4. 调仓与仓位:
   - 每 rebalance_days(20) 个交易日调仓一次
   - 目标持仓等权: 每只 = 账户总资产 / 持仓数
   - 买入数量取整为 100 股倍数，调仓日调整到目标组合
   - 当日无合格标的则保持空仓
5. 数据预热:
   - 回测前预加载 warmup_days(120) 个交易日收盘价，首个调仓日即可算 60 日涨跌幅排名
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from . import data

# ─────────────────────────────────────────────────────────────
# 配置
# ─────────────────────────────────────────────────────────────
ZZ500_EASTMONEY_BK = "BK0701"      # 东财板块代码：中证500
CN_INDEX_CODE = "000905.SH"         # 中证500指数
REBALANCE_DAYS = 20                 # 调仓间隔（交易日）
MIN_SCORE = 0.65                    # 综合得分门槛
TOP_N = 10                          # 最大持仓数量
WARMUP_DAYS = 120                   # 数据预热天数
LOT_SIZE = 100                      # A股 100 股整数倍
HK_LOT_SIZE = 100                   # 港股每手 100 股（多数标的，简化假设）
HK_TOP_N = 100                      # 港股池规模（类比中证500）
CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "rotation_cache"

# ─────────────────────────────────────────────────────────────
# 池构建
# ─────────────────────────────────────────────────────────────
async def fetch_zz500_constituents() -> list[dict]:
    """中证500成分股全量（东财 clist BK0701，分页拉全，去重）。"""
    codes_seen: dict[str, dict] = {}
    for pn in range(1, 8):
        d = await data.retry_async(max_attempts=4, delay=1.0)(data._get_json)(
            "https://push2.eastmoney.com/api/qt/clist/get", params={
                "fs": f"b:{ZZ500_EASTMONEY_BK}", "fields": "f12,f14,f13",
                "pn": pn, "pz": 100, "fid": "f12", "po": 0, "np": 1, "fltt": 2, "invt": 2})
        diff = (d.get("data") or {}).get("diff")
        rows = list(diff.values()) if isinstance(diff, dict) else (diff or [])
        if not rows:
            break
        for r in rows:
            code = str(r.get("f12", ""))
            if code:
                codes_seen[code] = {"code": code, "name": r.get("f14", ""),
                                    "market": _mkt_code(r.get("f13"))}
        total = (d.get("data") or {}).get("total")
        if total and len(codes_seen) >= int(total):
            break
    return list(codes_seen.values())


def _mkt_code(f13: Any) -> str:
    """东财 f13 市场码 → 'sh'/'sz'/'bj'（1=上证, 0=深证, 2=北证）"""
    try:
        v = int(f13)
    except (TypeError, ValueError):
        return "sz"
    return {1: "sh", 0: "sz", 2: "bj"}.get(v, "sz")


_SINA_HK_URL = ("https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
                "Market_Center.getHKStockData")
_HK_EXCLUDE_NAME = ("基金", "国债", "债券", "恒生指数", "恒生中国企业", "恒生科技", "杠杆", "反向", "两倍")
_HK_EXCLUDE_ENG = ("ETF", "ISHARES", "CSOP", "XTRACKERS", "GLOBAL X", "FUND", "LEVERAGED",
                   "INVERSE", "HANG SENG INDEX", "HANG SENG CHINA", "BOND", "TREASURY")


async def fetch_hk_top_amount_sina(top_n: int = HK_TOP_N) -> list[dict]:
    """港股成交额 Top N 兜底源（新浪 Market_Center.getHKStockData，node=qbgg_hk）。

    东财 push2 限流时启用。新浪该节点返回的榜单以个股为主（已再叠一层关键词过滤
    排除基金/ETF/债券），按 page 分页，每页 60 条。
    """
    stocks: list[dict] = []
    seen: set[str] = set()
    for page in range(1, 8):
        txt = await data.retry_async(max_attempts=3, delay=1.0)(data._get)(
            _SINA_HK_URL,
            params={"page": page, "num": 60, "sort": "amount", "asc": 0, "node": "qbgg_hk"},
            headers={"Referer": "https://finance.sina.com.cn/"})
        try:
            rows = json.loads(txt) if txt else []
        except (json.JSONDecodeError, ValueError):
            rows = []
        if not isinstance(rows, list) or not rows:
            break
        for r in rows:
            code = str(r.get("symbol", "")).strip()
            name = (r.get("name") or "").strip()
            eng = (r.get("engname") or "").upper()
            if not code or code in seen:
                continue
            if any(k in name for k in _HK_EXCLUDE_NAME) or any(k in eng for k in _HK_EXCLUDE_ENG):
                continue
            seen.add(code)
            stocks.append({"code": code, "name": name, "amount": r.get("amount"), "industry": ""})
            if len(stocks) >= top_n:
                return stocks
    return stocks


_HSI_WIKI_API = "https://zh.wikipedia.org/w/api.php"
_HSI_PAGE = "恒生指數"
_HSI_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/120 Safari/537.36"}


async def fetch_hsi_constituents() -> list[dict]:
    """恒生指数成分股（维基百科「恒生指數成份股」章节解析，2026-10-13 上线）。

    数据源背景：免费公开接口均无港股指数成分（东财 BK 体系仅 A股、datacenter 报表 A股专属、
    腾讯 ranklist 404、新浪 node 为空），维基 API parse 章节 wikitext 表格是免费源最优解。
    维基返回成分随季度检讨更新（当前 2026-09-07 生效 93 只）；解析失败时读本地缓存
    universe_hk_hsi.json 兜底。⚠️ 成分含 2024-2025 新入指标的上市前数据 → 前视偏差，无法 PIT。
    """
    import re
    universe: list[dict] = []
    try:
        r1 = await data.retry_async(max_attempts=3, delay=1.0)(data._get)(
            _HSI_WIKI_API,
            params={"action": "parse", "page": _HSI_PAGE, "prop": "sections",
                    "format": "json", "formatversion": "2"},
            headers=_HSI_UA)
        sec = None
        try:
            for s in json.loads(r1).get("parse", {}).get("sections", []):
                if "成份股" in s.get("line", ""):
                    sec = s
                    break
        except (ValueError, TypeError):
            sec = None
        if sec is None:
            raise RuntimeError("维基未找到成份股章节")
        r2 = await data.retry_async(max_attempts=3, delay=1.0)(data._get)(
            _HSI_WIKI_API,
            params={"action": "parse", "page": _HSI_PAGE, "section": sec["index"],
                    "prop": "wikitext", "format": "json", "formatversion": "2"},
            headers=_HSI_UA)
        wt = json.loads(r2)["parse"]["wikitext"]
        seen: set[str] = set()
        for code, name in re.findall(r"^\|([0-9]{5})\n\|\[\[([^\]]+)\]\]", wt, re.M):
            if code in seen:
                continue
            seen.add(code)
            name = re.sub(r"[（(].*?[）)]$", "", name)   # 去掉 （W）/（SW） 等后缀
            name = re.sub(r"\|.*", "", name).strip()    # 管道别名取前
            universe.append({"code": code, "name": name, "market": "hk"})
    except Exception as exc:
        print(f"[WARN] 维基恒指成分解析失败({str(exc)[:70]})，读本地缓存 universe_hk_hsi.json")
    if universe:
        save_universe_cache("hk_hsi", universe)
        return universe
    cached = load_universe_cache("hk_hsi")
    if cached:
        return cached
    raise RuntimeError("恒指成分获取失败（维基解析 + 本地缓存均无）")


async def fetch_hk_top_amount(top_n: int = HK_TOP_N) -> list[dict]:
    """港股成交额 Top N（东财 clist m:116 为主源，新浪榜单兜底），过滤 ETF/基金/债券。

    东财 f100（行业）为 '-' 或空 → 基金/ETF 类标的剔除；**必须翻页**——东财单页上限
    100 条，而成交额前 100 名里约 30 只是 ETF/基金，不翻页池子会打七折。
    东财限流（push2 偶发 ServerDisconnected/空响应）时自动降级新浪。
    """
    stocks: list[dict] = []
    try:
        stocks = await _fetch_hk_top_amount_eastmoney(top_n)
    except Exception as exc:
        print(f"[WARN] 港股池东财源失败({str(exc)[:60]})，降级新浪")
        stocks = []
    if len(stocks) < top_n:
        try:
            sina = await fetch_hk_top_amount_sina(top_n)
        except Exception as exc:
            print(f"[WARN] 港股池新浪源失败({str(exc)[:60]})")
            sina = []
        if len(sina) > len(stocks):
            print(f"[INFO] 港股池改用新浪源: {len(sina)} 只")
            return sina
    return stocks


async def _fetch_hk_top_amount_eastmoney(top_n: int = HK_TOP_N) -> list[dict]:
    """东财源：clist m:116 按 f6 成交额降序 + f100 行业字段过滤非个股，翻页补足。"""
    stocks: list[dict] = []
    seen: set[str] = set()
    for pn in range(1, 8):                       # 最多翻 7 页（覆盖前 700 名）
        d = await data.retry_async(max_attempts=3, delay=1.0)(data._get_json)(
            "https://push2.eastmoney.com/api/qt/clist/get", params={
                "fs": "m:116", "fields": "f12,f14,f6,f100,f13",
                "pn": pn, "pz": 100, "fid": "f6", "po": 1, "np": 1, "fltt": 2, "invt": 2})
        diff = (d.get("data") or {}).get("diff")
        rows = list(diff.values()) if isinstance(diff, dict) else (diff or [])
        if not rows:
            break
        for r in rows:
            industry = r.get("f100") or "-"
            if industry in ("-", "", None):      # 基金/ETF/债券：无行业分类
                continue
            code = str(r.get("f12", ""))
            if not code or code in seen:
                continue
            seen.add(code)
            stocks.append({"code": code, "name": r.get("f14", ""),
                           "amount": r.get("f6"), "industry": industry})
            if len(stocks) >= top_n:
                return stocks
    return stocks


# ─────────────────────────────────────────────────────────────
# 行情矩阵 (close / open)
# ─────────────────────────────────────────────────────────────
async def load_close_open(universe: list[dict], market: str, days: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """并发拉取全池日K，构建 close/open 矩阵（index=日期, columns=代码, 升序）。

    market: 'cn' / 'hk'。days: 请求根数，需 >= warmup + 回测窗口。
    """
    return await _load_matrices(universe, market, days, with_volume=False)


async def load_close_open_volume(universe: list[dict], market: str, days: int) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """load_close_open 的扩展版，额外返回 volume 矩阵（用于成交额因子/过滤）。

    A股腾讯日K volume 单位为"手"（×100=股）；港股为"股"。多因子策略
    用 `amount ≈ volume × lot × close` 近似成交额做横截面排名与流动性过滤。
    """
    return await _load_matrices(universe, market, days, with_volume=True)


async def _load_matrices(universe: list[dict], market: str, days: int,
                         with_volume: bool) -> tuple[pd.DataFrame, pd.DataFrame] | tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    async def one(item: dict) -> tuple[str, pd.DataFrame]:
        code = item["code"]
        if market == "hk":
            rows = await data.hk_kline_async(code, "day", count=days)
        else:
            rows = await data.cn_stock_kline_tencent_async(code, days=days)
        return code, pd.DataFrame.from_records(rows)

    results = await data.parallel_map([lambda it=it: one(it) for it in universe], max_concurrency=25)
    closes: dict[str, pd.Series] = {}
    opens: dict[str, pd.Series] = {}
    vols: dict[str, pd.Series] = {}
    for item in results:
        # parallel_map 对异常返回 Exception 对象（return_exceptions=True），需过滤
        if not isinstance(item, tuple) or len(item) != 2:
            continue
        code, df = item
        if df is None or df.empty or "close" not in df:  # type: ignore[union-attr]
            continue
        df["date"] = pd.to_datetime(df["date"])
        df = df.drop_duplicates("date").set_index("date").sort_index()
        closes[code] = df["close"].astype(float)
        opens[code] = df["open"].astype(float) if "open" in df else df["close"].astype(float)
        if with_volume and "volume" in df:
            vols[code] = df["volume"].astype(float)
    close_df = pd.DataFrame(closes)
    open_df = pd.DataFrame(opens)
    if with_volume:
        return close_df, open_df, pd.DataFrame(vols)
    return close_df, open_df


# ─────────────────────────────────────────────────────────────
# 得分与选股（核心逻辑，无未来函数）
# ─────────────────────────────────────────────────────────────
def cross_section_scores(close_df: pd.DataFrame, windows: tuple[int, int] = (20, 60)) -> pd.DataFrame:
    """对每只股票/每交易日计算 0.5×rank(pct20) + 0.5×rank(pct60)。

    - pct_change(w) 用当日收盘对照 w 日前的收盘 → 当日即"上一已收盘交易日"的信息：
      调仓日在 t 决策时取 t-1 行即可，绝不使用 t 日当天的数据。
    - rank(axis=1, pct=True) 逐行（每交易日）横截面排名，结果天然 0~1，NaN 保持 NaN。
    - 得分 = 0.5*(rank20+rank60)，两者皆有效才计入（任一 NaN → 该股当日不参与）。
    返回 DataFrame(index=日期, columns=代码)，值为综合得分 0~1。
    """
    closes = close_df.astype(float).sort_index()
    ret20 = closes.pct_change(windows[0])
    ret60 = closes.pct_change(windows[1])
    rank20 = ret20.rank(axis=1, pct=True)
    rank60 = ret60.rank(axis=1, pct=True)
    score = 0.5 * rank20 + 0.5 * rank60
    score = score.where(rank20.notna() & rank60.notna())
    return score


def select_on_date(score_df: pd.DataFrame, decision_date, min_score: float = MIN_SCORE,
                   top_n: int = TOP_N) -> pd.Series:
    """在 decision_date（一个"上一已收盘交易日"）选出目标组合。

    返回 pd.Series(代码→综合得分)，已按得分降序截断 top_n。
    """
    row = score_df.loc[decision_date].dropna()
    if row.empty:
        return pd.Series(dtype=float)
    row = row[row >= min_score]
    if row.empty:
        return pd.Series(dtype=float)
    return row.sort_values(ascending=False).head(top_n)


# ─────────────────────────────────────────────────────────────
# 回测引擎
# ─────────────────────────────────────────────────────────────
@dataclass
class RotationBacktestConfig:
    """回测参数（策略规格 1~5 的落地配置）。"""
    rebalance_days: int = REBALANCE_DAYS
    min_score: float = MIN_SCORE
    top_n: int = TOP_N
    warmup_days: int = WARMUP_DAYS
    lot_size: int = LOT_SIZE
    initial_cash: float = 1_000_000.0
    commission_rate: float = 0.0         # 双边费率合计（默认 0 忽略交易成本）
    name: str = "rotation"


@dataclass
class RotationBacktestResult:
    config: RotationBacktestConfig
    equity_curve: pd.Series                       # index=日期, 净值（含现金）
    holdings: pd.DataFrame                        # index=日期, columns=代码, 股数
    trades: list[dict]                            # 调仓记录
    rebalance_dates: list                          # 实际调仓日
    universe: list[dict]                          # 池
    metrics: dict[str, float] = field(default_factory=dict)


def _max_drawdown(curve: "pd.Series") -> float:
    return float((curve / curve.cummax() - 1.0).min())


def _metrics(curve: "pd.Series") -> dict[str, float]:
    """收益/年化/回撤/夏普/波动（在回测期做年化，roll 到 252 交易日）。"""
    if len(curve) < 2:
        return {}
    total_ret = float(curve.iloc[-1] / curve.iloc[0] - 1.0)
    n_days = len(curve)
    years = n_days / 252.0
    ann_ret = float((curve.iloc[-1] / curve.iloc[0]) ** (1 / years) - 1.0) if years > 0 else 0.0
    rets = curve.pct_change().dropna()
    vol = float(rets.std(ddof=0) * np.sqrt(252)) if len(rets) > 1 else 0.0
    sharpe = float(rets.mean() / rets.std(ddof=0) * np.sqrt(252)) if len(rets) > 1 and rets.std(ddof=0) > 0 else 0.0
    return {
        "total_return": total_ret,
        "annual_return": ann_ret,
        "max_drawdown": _max_drawdown(curve),
        "sharpe": sharpe,
        "annual_vol": vol,
    }


def run_backtest(close_df: pd.DataFrame, open_df: pd.DataFrame,
                 config: RotationBacktestConfig | None = None,
                 universe: list[dict] | None = None) -> RotationBacktestResult:
    """回测主循环。

    时序（严格无未来函数）:
      调仓日 t（第 k 个 rebalance_days 交易日）:
        - 决策: 取 cross_section_scores 中 **上一交易日 t_prev 的行**（只含 ≤t_prev 的信息）
                选出目标组合 target（score >= min_score, 降序 top_n）
        - 执行: 以 t 日开盘价成交（t 开盘价在 t 日开盘时已知，t_prev 收盘后即可挂单）
        - 等权: 每只目标市值 = 总市值 / len(target)
        - 100 股整数倍向下取整；不足 1 手（或除零）丢弃该股
        - 无合格标的 → 空仓（现金 100%）
    非调仓日: 持仓不动，按当日收盘价计市值。

    需要 close 与 open 同为升序、same 日期索引。
    """
    if config is None:
        config = RotationBacktestConfig()
    close_df = close_df.astype(float).sort_index()
    open_df = open_df.astype(float).sort_index()
    scores = cross_section_scores(close_df, (20, 60))

    dates = list(close_df.index)
    if len(dates) <= config.warmup_days + 1:
        raise ValueError(f"数据不足: 需要 > warmup({config.warmup_days})，实际 {len(dates)}")

    # 调仓日 = 预热期之后（첫调仓日即可计算 60 日涨跌幅），每隔 rebalance_days 个交易日
    rebalance_set = set(dates[config.warmup_days:: config.rebalance_days])

    cash = config.initial_cash
    positions: dict[str, int] = {}          # code -> shares
    equity_curve: dict = {}
    holdings_rows: dict = {}
    trades: list[dict] = []

    for i in range(config.warmup_days, len(dates)):
        t = dates[i]

        # ── 调仓日：决策用 t 的上一交易日（t-1）收盘数据，成交用 t 日开盘价 ──
        if t in rebalance_set:
            t_prev = dates[i - 1] if i > 0 else t
            target = select_on_date(scores, t_prev, config.min_score, config.top_n)
            open_row = open_df.loc[t] if t in open_df.index else close_df.loc[t]

            # 平旧仓（t 日开盘价）
            for code, shares in positions.items():
                if code in open_row.index and not pd.isna(open_row[code]):
                    cash += shares * float(open_row[code]) * (1 - config.commission_rate)
            positions = {}

            # 等权建新仓（t 日开盘价，100 股整数倍）
            if not target.empty:
                per = cash / len(target)
                for code in target.index:
                    px = open_row.get(code, np.nan)
                    if pd.isna(px) or float(px) <= 0:
                        continue
                    shares = int(per / float(px) // config.lot_size) * config.lot_size
                    if shares <= 0:
                        continue
                    cost = shares * float(px) * (1 + config.commission_rate)
                    if cost > cash:                        # 尾仓金额不足兜底（ponytail: 忽略零股残值）
                        shares = int(cash / (float(px) * (1 + config.commission_rate)) // config.lot_size) * config.lot_size
                        if shares <= 0:
                            continue
                        cost = shares * float(px) * (1 + config.commission_rate)
                    cash -= cost
                    positions[code] = shares
                trades.append({
                    "date": str(t.date()), "decision_date": str(t_prev.date()),
                    "target": [c for c in target.index], "positions": dict(positions),
                    "cash": round(cash, 2),
                })

        # ── 每个交易日：按 t 收盘价计市值，落权益曲线（保证指标按日频计算）──
        close_row = close_df.loc[t]
        mv = cash + sum(shares * float(close_row[code])
                        for code, shares in positions.items()
                        if code in close_row.index and not pd.isna(close_row[code]))
        equity_curve[t] = mv
        holdings_rows[t] = {"_cash_": cash, **positions}

    eq = pd.Series(equity_curve).sort_index()
    rebalance_dates = sorted(rebalance_set.intersection(eq.index))
    holdings = pd.DataFrame.from_dict(holdings_rows, orient="index")
    # 把现金列剔除出持仓矩阵
    if "_cash_" in holdings.columns:
        holdings = holdings.drop(columns=["_cash_"])
    holdings = holdings.fillna(0).astype(int)

    result = RotationBacktestResult(
        config=config, equity_curve=eq, holdings=holdings,
        trades=trades, rebalance_dates=rebalance_dates, universe=universe or [],
    )
    result.metrics = _metrics(eq)
    return result


def backtest_benchmark(index_close: pd.Series, start, end) -> dict[str, float]:
    """基准（指数）同期收益指标：取回测区间内与策略同网格的曲线。"""
    seg = index_close.loc[(index_close.index >= start) & (index_close.index <= end)]
    if len(seg) < 2:
        return {}
    return _metrics(seg.sort_index())


# ─────────────────────────────────────────────────────────────
# 缓存
# ─────────────────────────────────────────────────────────────
def cache_matrix(key: str):
    """读缓存（close.csv / open.csv / volume.csv 可选）。有 volume.csv 时返回三元组。"""
    try:
        d = CACHE_DIR / key
        if not (d / "close.csv").exists():
            return None
        close = pd.read_csv(d / "close.csv", index_col=0, parse_dates=True)
        open_f = pd.read_csv(d / "open.csv", index_col=0, parse_dates=True) \
            if (d / "open.csv").exists() else close
        vol_f = None
        if (d / "volume.csv").exists():
            vol_f = pd.read_csv(d / "volume.csv", index_col=0, parse_dates=True)
        return (close, open_f) if vol_f is None else (close, open_f, vol_f)
    except Exception:
        return None


def save_cache(key: str, close: pd.DataFrame, open_df: pd.DataFrame,
               volume: pd.DataFrame | None = None) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    d = CACHE_DIR / key
    d.mkdir(parents=True, exist_ok=True)
    close.to_csv(d / "close.csv")
    open_df.to_csv(d / "open.csv")
    if volume is not None:
        volume.to_csv(d / "volume.csv")


def load_universe_cache(market: str) -> list[dict] | None:
    """池缓存（universe.json）。"""
    try:
        f = CACHE_DIR / f"universe_{market}.json"
        if not f.exists():
            return None
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_universe_cache(market: str, universe: list[dict]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (CACHE_DIR / f"universe_{market}.json").write_text(
        json.dumps(universe, ensure_ascii=False, indent=1), encoding="utf-8")