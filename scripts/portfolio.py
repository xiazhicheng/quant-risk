#!/usr/bin/env python3
"""
组合持仓管理工具 — 诊断模式

用法:
  uv run scripts/portfolio.py diagnose-stdin    从 stdin 读取持仓 JSON，输出诊断
  uv run scripts/portfolio.py list              查看持仓（从 portfolio.json）
  uv run scripts/portfolio.py add ...           添加持仓到 portfolio.json
  uv run scripts/portfolio.py remove ...        移除持仓
  uv run scripts/portfolio.py update ...        更新持仓

stdin 格式 (JSON):
  [{"code":"00020","name":"商汤-W","shares":4000,"avg_cost":1.288}, ...]
"""
import json, sys, os
from datetime import datetime
from pathlib import Path

from scripts.quantrisk.data import (hk_stock_quote_tencent_async, hk_kline_tencent_async,
                                     stock_kline_yahoo_async, kline_tickflow_async,
                                     parallel_map, key_indicators_eastmoney_async,
                                     close_async_session, close_tickflow)
from scripts.quantrisk.indicators import calc_ma, calc_macd, chan_risk_assessment, calc_stop_loss_take_profit

PORTFOLIO_FILE = Path(__file__).parent.parent / "portfolio.json"


def load_portfolio() -> dict:
    if not PORTFOLIO_FILE.exists():
        return {"holdings": [], "last_updated": datetime.now().strftime("%Y-%m-%d")}
    return json.loads(PORTFOLIO_FILE.read_text())


def save_portfolio(data: dict):
    data["last_updated"] = datetime.now().strftime("%Y-%m-%d")
    PORTFOLIO_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"  ✅ 持仓已保存 ({len(data['holdings'])} 只)")


def cmd_list():
    data = load_portfolio()
    if not data["holdings"]:
        print("  持仓为空")
        return
    print(f"\n  {'代码':<8} {'名称':<12} {'数量':<8} {'成本':<8} {'现价':<8} {'盈亏%':<8} {'市值':<10} {'备注'}")
    print(f"  {'-'*72}")
    total_cost, total_value = 0, 0
    for h in data["holdings"]:
        print(f"  {h['code']:<8} {h['name']:<12} {h['shares']:<8} {h['avg_cost']:<8.2f} "
              f"{'--':<8} {'--':<8} {'--':<10} {h.get('notes','')}")
        total_cost += h["shares"] * h["avg_cost"]
    print(f"\n  总成本: {total_cost:.2f} HKD")
    print(f"  更新于: {data['last_updated']}")


def cmd_add(code: str, shares: int, cost: float, market: str = "hk", name: str = "", notes: str = ""):
    data = load_portfolio()
    for h in data["holdings"]:
        if h["code"] == code and h["market"] == market:
            print(f"  ⚠️ {code} 已在持仓中，用 update 更新")
            return
    data["holdings"].append({
        "code": code, "market": market, "name": name or code,
        "shares": shares, "avg_cost": cost, "currency": "HKD",
        "added_date": datetime.now().strftime("%Y-%m-%d"), "notes": notes,
    })
    save_portfolio(data)


def cmd_remove(code: str, market: str = "hk"):
    data = load_portfolio()
    before = len(data["holdings"])
    data["holdings"] = [h for h in data["holdings"] if not (h["code"] == code and h["market"] == market)]
    if len(data["holdings"]) == before:
        print(f"  ⚠️ 未找到 {code}")
        return
    save_portfolio(data)
    print(f"  ✅ 已移除 {code}")


def cmd_update(code: str, shares: int = None, cost: float = None, notes: str = None):
    data = load_portfolio()
    for h in data["holdings"]:
        if h["code"] == code:
            if shares is not None: h["shares"] = shares
            if cost is not None: h["avg_cost"] = cost
            if notes is not None: h["notes"] = notes
            save_portfolio(data)
            return
    print(f"  ⚠️ 未找到 {code}")


# ── 诊断 ──

async def diagnose_holdings(holdings: list[dict]) -> list[dict]:
    """诊断持仓数据，返回评分结果"""
    codes = [h["code"] for h in holdings]
    secucodes = [f"{c}.HK" for c in codes]
    print(f"  🔍 诊断 {len(codes)} 只持仓...\n")

    qf = [lambda c=c: hk_stock_quote_tencent_async(c) for c in codes]
    inf = [lambda s=s: key_indicators_eastmoney_async(s) for s in secucodes]
    kf = [lambda c=c: _fetch_kline(c) for c in codes]
    quotes, indicators, klines = await asyncio.gather(
        parallel_map(qf), parallel_map(inf), parallel_map(kf))

    results = []
    for i, h in enumerate(holdings):
        q = quotes[i] if isinstance(quotes[i], dict) else {}
        ind = indicators[i][0] if isinstance(indicators[i], list) and indicators[i] else {}
        kl = klines[i] if isinstance(klines[i], list) else []
        current_price = q.get("price", 0)
        cost = h["avg_cost"]
        pnl_pct = (current_price / cost - 1) * 100 if cost and current_price else 0
        sell_score = await _calc_sell_score(h, q, ind, kl, current_price, cost, pnl_pct)
        results.append({**h, "q": q, "ind": ind, "kl": kl,
                        "current_price": current_price, "pnl_pct": pnl_pct,
                        "sell_score": sell_score})
    results.sort(key=lambda x: x["sell_score"], reverse=True)
    await close_async_session()
    await close_tickflow()
    return results


def print_diagnosis(results: list[dict]):
    """打印诊断结果"""
    print(f"  {'状态':<8} {'代码':<8} {'名称':<12} {'盈亏%':<8} {'现价':<8} {'成本':<8} "
          f"{'建议':<16} {'卖出评分'}")
    print(f"  {'-'*90}")
    for r in results:
        ss = r["sell_score"]
        if ss >= 35:
            status, advice = "🔴", "强烈建议卖出 ⚠️"
        elif ss >= 28:
            status, advice = "🟡", "建议减仓"
        elif ss >= 22:
            status, advice = "🟢", "可继续持有"
        else:
            status, advice = "✅", "安心持有"
        pnl_s = f"{r['pnl_pct']:+.2f}%"
        print(f"  {status:<8} {r['code']:<8} {r['name']:<12} {pnl_s:<8} "
              f"{r['current_price']:<8.2f} {r['avg_cost']:<8.2f} {advice:<16} {ss}")
    print()

    # 详细分析（只显示需要操作的）
    for r in results:
        ss = r["sell_score"]
        if ss < 22:
            continue
        pnl = r["pnl_pct"]
        q = r["q"]
        ind = r["ind"]
        kl = r["kl"]
        print(f"  {'='*60}")
        print(f"  {r['code']} {r['name']} — {'🔴 建议卖出' if ss>=35 else '🟡 建议减仓'}")
        print(f"  {'='*60}")
        print(f"  盈亏: {pnl:+.2f}% | 现价: {r['current_price']:.2f} | 成本: {r['avg_cost']:.2f}")
        pe = q.get("pe", 0)
        mc = q.get("market_cap_100m", 0)
        print(f"  PE: {pe} | 市值: {mc}亿")
        if kl and len(kl) >= 20:
            sltp = calc_stop_loss_take_profit(entry_price=r["avg_cost"], klines=kl[-60:])
            sl = sltp.get("stop_loss")
            if sl and r["current_price"] <= sl:
                print(f"  ⛔ 现价已跌破止损位 ({sl:.2f})！")
        print()


async def cmd_diagnose():
    """从 portfolio.json 读取持仓并诊断"""
    data = load_portfolio()
    if not data["holdings"]:
        print("  持仓为空，无法诊断")
        return
    results = await diagnose_holdings(data["holdings"])
    print_diagnosis(results)
    print()

    # 详细分析
    for r in results:
        ss = r["sell_score"]
        if ss < 22:
            continue  # 只显示需要操作的
        pnl = r["pnl_pct"]
        q = r["q"]
        ind = r["ind"]
        kl = r["kl"]
        print(f"  {'='*60}")
        print(f"  {r['code']} {r['name']} — {'🔴 建议卖出' if ss>=35 else '🟡 建议减仓'}")
        print(f"  {'='*60}")
        print(f"  盈亏: {pnl:+.2f}% | 现价: {r['current_price']:.2f} | 成本: {r['avg_cost']:.2f}")
        pe = q.get("pe", 0)
        mc = q.get("market_cap_100m", 0)
        print(f"  PE: {pe} | 市值: {mc}亿")

        # ATR 止损
        if kl and len(kl) >= 20:
            sltp = calc_stop_loss_take_profit(entry_price=r["avg_cost"], klines=kl[-60:])
            sl = sltp.get("stop_loss")
            tp = sltp.get("take_profit")
            print(f"  技术止损: {sl:.2f}" if sl else "")
            print(f"  技术止盈: {tp:.2f}" if tp else "")
            # 现价是否跌破止损
            if sl and r["current_price"] <= sl:
                print(f"  ⛔ 现价已跌破止损位！")
        print()

    await close_async_session()
    await close_tickflow()


async def _fetch_kline(code: str):
    try:
        kl = await hk_kline_tencent_async(code, "day", 365)
        if kl and len(kl) >= 20:
            return kl
        kl = await stock_kline_yahoo_async(f"{int(code)}.HK", "1d", "1y")
        if kl and len(kl) >= 20:
            return kl
        kl = await kline_tickflow_async(f"{code}.HK", "1d", 365)
        return kl or []
    except:
        return []


async def _calc_sell_score(h, q, ind, kl, price, cost, pnl_pct) -> int:
    """计算卖出 urgency 评分（越高越该卖）"""
    s = 15  # 基准分15，越高越危险

    # 1. 浮亏幅度（5分）
    if pnl_pct < -15:
        s += 5  # 深套，但已破位需止损
    elif pnl_pct < -8:
        s += 3
    elif pnl_pct < -3:
        s += 1
    # 浮盈过大也可能该止盈
    if pnl_pct > 30:
        s += 4  # 大幅浮盈，考虑止盈
    elif pnl_pct > 15:
        s += 2

    # 2. 估值恶化（5分）
    pe = q.get("pe", 0) or 0
    if pe > 50:
        s += 3
    elif pe > 30:
        s += 1
    if pe < 0:
        s += 2  # 亏损股

    # 3. 基本面恶化（10分）
    ny = ind.get("HOLDER_PROFIT_YOY") or 0
    rev = ind.get("OPERATE_INCOME_YOY") or 0
    if ny < -50:
        s += 5
    elif ny < -20:
        s += 3
    elif ny < 0:
        s += 1
    if rev < -20:
        s += 3
    elif rev < -10:
        s += 2
    elif rev < 0:
        s += 1

    # 4. 技术面破位（10分）
    if kl and len(kl) >= 60:
        try:
            ma = calc_ma(kl, [20, 60])
            close = price
            if ma and len(ma) > 0:
                m20 = ma[-1].get("ma20")
                m60 = ma[-1].get("ma60")
                if m20 and m60:
                    if close < m60:
                        s += 5  # 跌破MA60，中期破位
                    elif close < m20:
                        s += 2  # 跌破MA20
                    # MA20 < MA60 = 死叉
                    if m20 < m60:
                        s += 3
            # MACD
            md = calc_macd(kl)
            if md and len(md) >= 2:
                cur_h = md[-1].get("macd_hist") or (md[-1]["dif"] - md[-1]["dea"]) * 2
                prev_h = md[-2].get("macd_hist") or (md[-2]["dif"] - md[-2]["dea"]) * 2
                if prev_h > 0 > cur_h:
                    s += 4  # MACD死叉
                elif cur_h < 0:
                    s += 2  # MACD为负
        except:
            pass

    # 5. 缠论卖出信号
    if kl and len(kl) >= 60:
        try:
            cv = chan_risk_assessment(kl)
            if isinstance(cv, dict):
                sig = cv.get("signal", "")
                if "卖" in sig or "sell" in sig.lower():
                    s += 5
        except:
            pass

    return min(50, max(1, s))


if __name__ == "__main__":
    import asyncio

    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(0)

    cmd = args[0]
    if cmd == "list":
        cmd_list()
    elif cmd == "add":
        if len(args) < 4:
            print("用法: portfolio.py add <code> <shares> <cost> [market] [name]")
            sys.exit(1)
        cmd_add(args[1], int(args[2]), float(args[3]),
                market=args[4] if len(args) > 4 else "hk",
                name=args[5] if len(args) > 5 else args[1])
    elif cmd == "remove":
        if len(args) < 2:
            print("用法: portfolio.py remove <code>")
            sys.exit(1)
        cmd_remove(args[1])
    elif cmd == "update":
        if len(args) < 2:
            print("用法: portfolio.py update <code> [shares] [cost]")
            sys.exit(1)
        shares = int(args[2]) if len(args) > 2 else None
        cost = float(args[3]) if len(args) > 3 else None
        notes = args[4] if len(args) > 4 else None
        cmd_update(args[1], shares, cost, notes)
    elif cmd == "diagnose":
        asyncio.run(cmd_diagnose())
    elif cmd == "diagnose-stdin":
        # 从 stdin 读取持仓 JSON
        try:
            stdin_data = sys.stdin.read()
            holdings = json.loads(stdin_data)
            if isinstance(holdings, dict) and "holdings" in holdings:
                holdings = holdings["holdings"]
        except Exception as e:
            print(f"❌ 解析 stdin 失败: {e}")
            print("格式: [{\"code\":\"00020\",\"name\":\"商汤-W\",\"shares\":4000,\"avg_cost\":1.288}, ...]")
            sys.exit(1)
        results = asyncio.run(diagnose_holdings(holdings))
        print_diagnosis(results)
    else:
        print(f"未知命令: {cmd}")
        print(__doc__)