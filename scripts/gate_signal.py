#!/usr/bin/env python3
"""门控策略（TrendGate）当日信号 —— 推荐默认口径（2026-10-22 用户确认「门控优先」）。

为什么单独一个脚本：`daily_run.py` 的闸门信号复用 rotation 回测缓存，缓存最后交易日
停在回测那次运行的日子（实测 2026-10-13），直接读会拿 6 个交易日前的闸门状态推荐今天
的票。本脚本先增量把缓存补到最新交易日（只回填非 NaN 值，失败率 >20% 拒绝落盘），
再算闸门 + 双动量，输出当日建议。

用法:
    uv run scripts/gate_signal.py                        # A股+港股，N=3，闸门按市场配置
    uv run scripts/gate_signal.py --markets hk            # 只看港股
    uv run scripts/gate_signal.py --top-n 10              # 港股回撤保护档
    uv run scripts/gate_signal.py --gate-modes cn=stock   # 覆盖闸门类型
    uv run scripts/gate_signal.py --no-extend             # 不补缓存，直接用现有矩阵
    uv run scripts/gate_signal.py --no-save               # 补缓存但不写回磁盘

产物: report/gate-signal-YYYYMMDD.md（同时打印到 stdout）
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from scripts.quantrisk import data
from scripts.quantrisk import rotation as rot
from scripts.quantrisk.daily import _trendgate_index_kline
from scripts.quantrisk.trendgate import HS300_SYMBOL, HSI_SYMBOL

FETCH_DAYS = 40          # 增量抓取的自然日窗口（覆盖 20 日动量的重算需求）
MIN_SCORE = 0.65         # 双动量入选阈值（与 rotation/trendgate 一致）
MAX_FAIL_RATIO = 0.20    # 增量抓取失败率上限，超过则不落盘


# ─────────────────────────────────────────────────────────────
# 缓存增量
# ─────────────────────────────────────────────────────────────
async def fetch_recent(universe: list[dict], market: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, int]:
    """抓最近 FETCH_DAYS 自然日 K 线，返回 (close, open, volume, 失败数)。"""

    async def one(item: dict):
        code = item["code"]
        rows = []
        for attempt in range(2):
            try:
                if market == "hk":
                    rows = await data.hk_kline_async(code, "day", count=FETCH_DAYS)
                else:
                    # 走腾讯→新浪→百度 fallback 链（腾讯单源在 500 只批量后极易返回空）
                    rows = await data.cn_stock_kline_fallback(code, days=FETCH_DAYS)
            except Exception:
                rows = []
            if rows:
                break
            await asyncio.sleep(0.2 + 0.2 * attempt)
        df = pd.DataFrame.from_records(rows) if rows else None
        if df is None or df.empty or "close" not in df:
            return None
        df["date"] = pd.to_datetime(df["date"])
        df = df.drop_duplicates("date").set_index("date").sort_index()
        opens = df["open"].astype(float) if "open" in df else df["close"].astype(float)
        vols = df["volume"].astype(float) if "volume" in df else None
        return code, df["close"].astype(float), opens, vols

    res = await data.parallel_map([lambda it=it: one(it) for it in universe], max_concurrency=15)
    closes, opens, vols, failed = {}, {}, {}, 0
    for r in res:
        if isinstance(r, tuple) and len(r) == 4:
            code, c, o, v = r
            closes[code] = c
            opens[code] = o
            if v is not None:
                vols[code] = v
        else:
            failed += 1
    return pd.DataFrame(closes), pd.DataFrame(opens), pd.DataFrame(vols), failed


def merge_extend(cached: pd.DataFrame, ext: pd.DataFrame) -> pd.DataFrame:
    """把增量矩阵并入缓存：重叠日期用新值覆盖（NaN 不覆盖），新日期追加。"""
    if ext.empty:
        return cached
    cols = ext.columns.intersection(cached.columns)
    if len(cols) == 0:
        return cached
    out = cached.copy()
    out.update(ext[cols])
    new_rows = ext.index.difference(out.index)
    if len(new_rows):
        out = pd.concat([out, ext.loc[new_rows, cols]], axis=0).sort_index()
    return out


async def load_market(uni_key: str, market: str, days: int, extend: bool, save: bool) -> dict:
    universe = rot.load_universe_cache(uni_key)
    hit = rot.cache_matrix(f"{uni_key}_d{days}")
    if not universe or not hit:
        return {"error": f"缺池/矩阵缓存（universe_{uni_key}.json、{uni_key}_d{days}），"
                         f"先跑 backtest_trendgate --market {market}"
                         f"{' --pool hsi' if uni_key == 'hk_hsi' else ''} 生成"}
    close, open_df = hit[0], hit[1]
    volume = hit[2] if len(hit) > 2 else None
    info = {"extended": False, "failed": 0, "total": len(universe)}
    if extend:
        ext_c, ext_o, ext_v, failed = await fetch_recent(universe, market)
        info["failed"] = failed
        if not ext_c.empty:
            ratio = failed / max(len(universe), 1)
            if ratio > MAX_FAIL_RATIO:
                info["extended"] = False
                info["skipped"] = f"失败率 {ratio:.0%} > {MAX_FAIL_RATIO:.0%}，放弃落盘"
            else:
                close = merge_extend(close, ext_c)
                open_df = merge_extend(open_df, ext_o)
                # volume 同步延长，避免 close/volume 索引错位（回测停牌检查依赖对齐）
                if volume is not None and not ext_v.empty:
                    volume = merge_extend(volume, ext_v)
                info["extended"] = True
                if save:
                    rot.save_cache(f"{uni_key}_d{days}", close, open_df, volume)
    return {"universe": universe, "close": close, "open": open_df, **info}


# ─────────────────────────────────────────────────────────────
# 闸门 + 双动量
# ─────────────────────────────────────────────────────────────
def stock_gate(close: pd.DataFrame, asof) -> pd.DataFrame:
    """个股闸门：close vs 自身 MA30 + 连续 3 日确认（截面截止 asof）。"""
    s = close.loc[:asof]
    ma = s.rolling(GATE_MA).mean()
    above = s.ge(ma) & s.gt(0)
    conf = above.rolling(CONFIRM).sum().eq(CONFIRM)
    return pd.DataFrame({"close": s.iloc[-1], "ma": ma.iloc[-1],
                         "above": above.iloc[-1], "confirmed": conf.iloc[-1]})


INDEX_CACHE = Path(__file__).resolve().parent.parent / "data" / "gate_index_cache.json"


async def load_index_gate(symbol: str):
    """闸门指数日K：腾讯 → 新浪 → Yahoo，全败则回退最后一次成功的本地缓存。

    返回 (Series|None, 告警文本)。指数源在批量抓取后常被限流，
    因此成功时落盘，失败时用缓存并明确标注滞后日期（不假装新鲜）。
    """
    import json

    cands = [(symbol, lambda s=symbol: _trendgate_index_kline(900, s))]
    if symbol.startswith("sh") or symbol.startswith("sz"):
        cands.append((f"{symbol}-sina", lambda s=symbol: data.cn_stock_kline_sina_async(s)))
        cands.append((f"{symbol}-yahoo", lambda s=symbol: data.stock_kline_yahoo_async("000300.SS", "day")))
        # 最后兜底：用沪深300ETF 代理指数（价格水平不同，但 MA30 穿越时点几乎一致）
        cands.append(("sh510300-ETF代理",
                      lambda: data.cn_stock_kline_fallback("510300", days=900)))
    else:
        cands.append(("hk02800-ETF代理",
                      lambda: data.hk_kline_async("02800", "day", count=900)))
    for label, fn in cands:
        try:
            rows = await fn()
        except Exception:
            rows = None
        s = _to_series(rows)
        if s is not None and len(s) > GATE_MA + 5:
            proxy_note = ""
            if "ETF代理" in label:
                etf = label.split("-")[0]
                proxy_note = (f"⚠️ 指数源全部限流，闸门改用 {etf} 代理（价格水平不同、"
                              f"MA{GATE_MA} 穿越时点与指数高度一致，但**不是指数本身**）")
            try:
                cache = json.loads(INDEX_CACHE.read_text(encoding="utf-8")) if INDEX_CACHE.exists() else {}
            except Exception:
                cache = {}
            cache[symbol] = {str(k.date()): float(v) for k, v in s.items()}
            try:
                INDEX_CACHE.parent.mkdir(parents=True, exist_ok=True)
                INDEX_CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
            except Exception:
                pass
            return s, proxy_note
    # 全源失败 → 用缓存
    try:
        cache = json.loads(INDEX_CACHE.read_text(encoding="utf-8"))
        rows = cache.get(symbol) or {}
        if rows:
            s = pd.Series({pd.Timestamp(k): float(v) for k, v in rows.items()}).sort_index()
            return s, (f"指数源全部限流，回退本地缓存（最后交易日 {s.index[-1].date()}）；"
                       f"闸门状态基于该日收盘，非实时")
    except Exception:
        pass
    return None, ""


def _to_series(rows) -> pd.Series | None:
    """把各种 K 线返回（list[dict] / Series）统一成 date→close。"""
    if rows is None:
        return None
    if isinstance(rows, pd.Series):
        return rows.sort_index()
    if isinstance(rows, list) and rows:
        try:
            df = pd.DataFrame.from_records(rows)
            df["date"] = pd.to_datetime(df["date"])
            return df.drop_duplicates("date").set_index("date")["close"].astype(float).sort_index()
        except Exception:
            return None
    return None


def index_gate(gi: pd.Series, asof) -> dict:
    s = gi.loc[:asof]
    ma = s.rolling(GATE_MA).mean()
    above = s > ma
    n = 0
    for v in above.iloc[::-1]:
        if bool(v):
            n += 1
        else:
            break
    return {"close": float(s.iloc[-1]), "ma": float(ma.iloc[-1]), "above": bool(above.iloc[-1]),
            "confirm": n, "need": float(ma.iloc[-1] / s.iloc[-1] - 1) * 100}


def momentum(px: pd.Series) -> tuple[float, float]:
    px = px.dropna()
    p20 = (px.iloc[-1] / px.iloc[-21] - 1) * 100 if len(px) > 21 else float("nan")
    p60 = (px.iloc[-1] / px.iloc[-61] - 1) * 100 if len(px) > 61 else float("nan")
    return p20, p60


def render_index_market(market_label: str, tag: str, close: pd.DataFrame, uni: list[dict],
                        gi: pd.Series, names: dict, top_n: int,
                        gate_label: str = "沪深300（sh000300）") -> list[str]:
    dates = close.index
    d_prev = dates[-2] if len(dates) > 1 else dates[-1]
    d_last = dates[-1]
    g_prev, g_now = index_gate(gi, d_prev), index_gate(gi, d_last)

    L = [f"### {market_label}（池：{tag} {len(uni)} 只，指数闸门 MA{GATE_MA}）", ""]
    L += ["| 闸门指标 | 值 |", "|:----|:----|",
          f"| 闸门指数 | {gate_label} |",
          f"| 信号日收盘 | {g_prev['close']:.2f}（{d_prev.date()}） |",
          f"| MA{GATE_MA} | {g_prev['ma']:.2f} |",
          f"| 距 MA{GATE_MA} | {g_prev['need']:+.2f}%"
          f"（{'站上' if g_prev['above'] else '跌破，需上涨该幅度才回补'}） |",
          f"| 连续站上 | {g_prev['confirm']} 日（需 {CONFIRM} 日） |"]
    if g_prev["above"] and g_prev["confirm"] >= CONFIRM:
        stance = "🟢 开闸（可持仓）"
    elif g_prev["above"]:
        stance = f"🟡 确认中（已站上 {g_prev['confirm']} 日）"
    else:
        stance = "🔴 关闸 → 空仓等待"
    L += [f"| 裁决 | **{stance}** |", ""]

    score = rot.cross_section_scores(close)
    try:
        sel = rot.select_on_date(score, d_prev, min_score=MIN_SCORE, top_n=max(top_n, 10))
    except Exception:
        sel = pd.Series(dtype=float)

    gate_on = g_prev["above"] and g_prev["confirm"] >= CONFIRM
    if gate_on:
        L += [f"**建议买入（闸门开 + 双动量前 {top_n}，{d_prev.date()} 收盘信号）**", ""]
        L += ["| 标的 | 得分 | 现价 | 20日动量 | 60日动量 |", "|:----|:---:|:---:|:---:|:---:|"]
        for code, sc in list(sel.items())[:top_n]:
            p20, p60 = momentum(close[code].loc[:d_last])
            L.append(f"| {names.get(code,'')}（{code}） | {sc:.3f} | {close[code].loc[:d_last].dropna().iloc[-1]:.2f} "
                     f"| {p20:+.2f}% | {p60:+.2f}% |")
    else:
        L.append(f"**A股结论**：闸门关闭 → 门控策略仓位 = 0，无买入标的。"
                 f"指数需再涨 {g_prev['need']:+.2f}% 才重新站上 MA{GATE_MA}，且需连续 {CONFIRM} 日确认。")
    L.append("")
    if len(sel):
        L += [f"**双动量候选（{d_prev.date()} 收盘，得分≥{MIN_SCORE}）** —— "
              f"{'已按前 ' + str(top_n) + ' 建仓' if gate_on else '仅观察，闸门关不建仓'}：", "",
              "| 排名 | 标的 | 得分 | 最新价 | 20日动量 | 60日动量 |",
              "|:---:|:----|:---:|:---:|:---:|:---:|"]
        for i, (code, sc) in enumerate(sel.items(), 1):
            p20, p60 = momentum(close[code].loc[:d_last])
            L.append(f"| {i} | {names.get(code,'')}（{code}） | {sc:.3f} | "
                     f"{close[code].loc[:d_last].dropna().iloc[-1]:.2f} | {p20:+.2f}% | {p60:+.2f}% |")
        L.append("")
    L.append(f"盘中跟踪（{d_last.date()}）：指数 {g_now['close']:.2f} vs MA{GATE_MA} {g_now['ma']:.2f} → "
             f"{'站上' if g_now['above'] else '跌破'}，连续 {g_now['confirm']} 日。")
    L.append("")
    return L


def render_stock_market(market_label: str, tag: str, close: pd.DataFrame, uni: list[dict],
                        names: dict, top_n: int) -> list[str]:
    dates = close.index
    d_prev = dates[-2] if len(dates) > 1 else dates[-1]
    d_last = dates[-1]
    gp = stock_gate(close, d_prev)
    on_prev = int(gp["confirmed"].sum())
    total = int(gp["close"].notna().sum())

    price_now = close.loc[d_last]
    ma_prev = close.loc[:d_prev].rolling(GATE_MA).mean().iloc[-1]
    on_now = int(((price_now >= ma_prev) & price_now.notna() & ma_prev.notna()).sum())

    L = [f"### {market_label}（池：{tag} {total} 只，个股自身 MA{GATE_MA} 闸门）", "",
         f"- {d_prev.date()} 收盘：池内 **{on_prev}/{total}（{on_prev/max(total,1):.0%}）** 站上自身 "
         f"MA{GATE_MA} 且连续 {CONFIRM} 日 → 多数{'在场' if on_prev/max(total,1) > .5 else '离场'}",
         f"- {d_last.date()} 盘中：**{on_now}/{total}（{on_now/max(total,1):.0%}）** 站上（待收盘确认）", ""]

    score = rot.cross_section_scores(close).loc[d_prev]
    cand = []
    for code in close.columns:
        if code not in score.index or pd.isna(score.get(code)):
            continue
        if code not in gp.index:
            continue
        row = gp.loc[code]
        if pd.isna(row["close"]) or pd.isna(row["ma"]):
            continue
        cand.append({"code": code, "name": names.get(code, ""), "score": float(score[code]),
                     "close": float(row["close"]), "ma": float(row["ma"]),
                     "confirmed": bool(row["confirmed"]), "above": bool(row["above"]),
                     "now": float(price_now.get(code, float("nan"))) if code in price_now.index else float("nan"),
                     "ma_prev": float(ma_prev.get(code, float("nan"))) if code in ma_prev.index else float("nan")})
    cand.sort(key=lambda x: -x["score"])
    buy = [c for c in cand if c["confirmed"]][:top_n]

    L += [f"**建议买入（闸门开 + 双动量前 {top_n}，{d_prev.date()} 收盘信号）**", ""]
    if not buy:
        L.append("⛔ 无标的通过（闸门开的股票双动量得分不足）。")
    else:
        L += [f"| 标的 | 得分 | {d_prev.date()} 收盘 | MA{GATE_MA}（止损线） | 止损空间 | 20日动量 | 60日动量 | 盘中核对 |",
              "|:----|:---:|:---:|:---:|:---:|:---:|:---:|:---:|"]
        for c in buy:
            p20, p60 = momentum(close[c["code"]].loc[:d_last])
            stop = (c["ma"] / c["close"] - 1) * 100
            live = ("🟢站上" if c["now"] >= c["ma_prev"] else "🔴跌破") \
                if pd.notna(c["now"]) and pd.notna(c["ma_prev"]) else "❓"
            L.append(f"| {c['name']}（{c['code']}） | {c['score']:.3f} | {c['close']:.2f} | {c['ma']:.2f} | "
                     f"{stop:+.2f}% | {p20:+.2f}% | {p60:+.2f}% | {live} |")
    L.append("")

    near = [c for c in cand if not c["confirmed"] and c["score"] >= MIN_SCORE][:8]
    if near:
        L += [f"**观察名单（得分≥{MIN_SCORE}，闸门未确认 → 不买）**", "",
              "| 标的 | 得分 | 收盘 | MA30 | 状态 |", "|:----|:---:|:---:|:---:|:----|"]
        for c in near:
            st = "站上但未满3日" if c["above"] else "跌破"
            L.append(f"| {c['name']}（{c['code']}） | {c['score']:.3f} | {c['close']:.2f} | {c['ma']:.2f} | 🔴{st} |")
        L.append("")

    L += ["**池内已开闸持仓（按得分降序，前 15）**", "",
          "| 标的 | 得分 | 收盘 | MA30 | 距止损 | 盘中核对 |", "|:----|:---:|:---:|:---:|:---:|:---:|"]
    for c in [x for x in cand if x["confirmed"]][:15]:
        stop = (c["ma"] / c["close"] - 1) * 100
        live = ("🟢站上" if c["now"] >= c["ma_prev"] else "🔴跌破") \
            if pd.notna(c["now"]) and pd.notna(c["ma_prev"]) else "❓"
        L.append(f"| {c['name']}（{c['code']}） | {c['score']:.3f} | {c['close']:.2f} | {c['ma']:.2f} | "
                 f"{stop:+.2f}% | {live} |")
    L.append("")
    return L


# ─────────────────────────────────────────────────────────────
# 主流程
# ─────────────────────────────────────────────────────────────
GATE_MA = 30
CONFIRM = 3


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="门控策略（TrendGate）当日信号")
    ap.add_argument("--markets", default="cn,hk", help="市场，逗号分隔（cn/hk），默认 cn,hk")
    ap.add_argument("--top-n", type=int, default=3, help="持仓数 N（默认 3；港股求回撤保护用 10）")
    ap.add_argument("--gate-modes", default="cn=index,hk=stock",
                    help="闸门类型，默认 cn=index,hk=stock")
    ap.add_argument("--gate-ma", type=int, default=30, help="闸门均线周期（默认 30）")
    ap.add_argument("--days", type=int, default=800, help="缓存矩阵窗口（默认 800）")
    ap.add_argument("--no-extend", action="store_true", help="不增量补缓存")
    ap.add_argument("--no-save", action="store_true", help="补缓存但不写回磁盘")
    return ap.parse_args()


async def main() -> int:
    global GATE_MA
    args = parse_args()
    GATE_MA = args.gate_ma
    modes = {}
    for pair in args.gate_modes.split(","):
        if "=" in pair:
            k, v = pair.split("=", 1)
            modes[k.strip()] = v.strip()

    L: list[str] = ["## 门控策略（TrendGate）当日信号", "",
                    f"> 参数：N={args.top_n} 只｜20 交易日调仓｜闸门 MA{GATE_MA}｜入场需连续 {CONFIRM} 日站上"
                    f"｜敞口上限 70%｜单边费 0.1%+滑点 0.1%",
                    f"> 逻辑：双动量（0.5×20日动量 + 0.5×60日动量，横截面排名）≥{MIN_SCORE} 取前 N；"
                    f"闸门关 → 该标的（或整个市场）不入场。", ""]

    todo = [m.strip() for m in args.markets.split(",") if m.strip()]
    for market in todo:
        uni_key = "hk_hsi" if market == "hk" else "cn"
        loaded = await load_market(uni_key, market, args.days,
                                   extend=not args.no_extend, save=not args.no_save)
        if "error" in loaded:
            L += [f"### {market}：⛔ {loaded['error']}", ""]
            continue
        close, uni = loaded["close"], loaded["universe"]
        names = {u["code"]: u.get("name", "") for u in uni}
        notes = []
        if loaded.get("extended"):
            notes.append(f"缓存已增量补至 {close.index[-1].date()}")
        else:
            notes.append(f"⚠️ 缓存未更新，信号截至 {close.index[-1].date()}（非最新交易日）")
        if loaded.get("skipped"):
            notes.append(loaded["skipped"])
        if loaded["failed"]:
            notes.append(f"抓取失败 {loaded['failed']}/{loaded['total']}")
        if notes:
            L += [f"> ⚠️ {'；'.join(notes)}", ""]
        gate_mode = modes.get(market, "index")
        if gate_mode == "stock":
            L += render_stock_market("港股" if market == "hk" else "A股",
                                     "恒生指数成分" if market == "hk" else "中证500 成分",
                                     close, uni, names, args.top_n)
        else:
            sym = HSI_SYMBOL if market == "hk" else HS300_SYMBOL
            gi, src_note = await load_index_gate(sym)
            if gi is None:
                L += [f"### {market}：⛔ 闸门指数获取失败（腾讯/新浪/Yahoo 均无数据且无历史缓存）", ""]
                continue
            if src_note:
                L += [f"> {src_note}", ""]
            base = ("沪深300（sh000300）" if market == "cn" else "恒生指数（hkHSI）")
            gate_label = f"{base} ⚠️ 代理（源限流）" if "代理" in (src_note or "") else base
            L += render_index_market("A股" if market == "cn" else "港股",
                                     "中证500 成分" if market == "cn" else "恒生指数成分",
                                     close, uni, gi, names, args.top_n, gate_label)

    L += ["---", "", "### 执行规则（两市场统一）", "",
          f"- **入场**：闸门开（个股闸门需连续 {CONFIRM} 日站上 MA{GATE_MA}）→ 次日开盘等权买入，"
          f"单只 ≤1/{args.top_n} 目标权重×70% 敞口",
          f"- **卖出**：任一只收盘跌破自身 MA{GATE_MA} → 次日开盘清掉该只（不设个股止损/止盈）",
          f"- **调仓**：每 20 个交易日按双动量重排；周期内掉出前 {args.top_n} 不强制卖",
          "- **风险**：指数闸门关时空仓（可能连续数周 0 仓位）；个股闸门在指数急跌日会同时触发多只卖出",
          "", "> ⚠️ 声明：基于公开行情数据自动计算，不构成投资建议。"]

    report = "\n".join(L)
    out = Path("report") / f"gate-signal-{date.today():%Y%m%d}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(report)
    print(f"\n📄 已保存: {out}")
    await data.close_async_session()
    await data.close_tickflow()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
