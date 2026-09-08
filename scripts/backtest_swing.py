#!/usr/bin/env python3
"""波段推荐回测闭环（2026-09-08 新增，Q5）。

用途：记录每次推荐的 TOP10，T+5/T+10 事后统计胜率与平均收益，1-2 个月后
回头验证 30/25/20/25 评分体系和"可布局/谨慎/观望"三档是否有效，
避免无数据支撑的调参。

用法：
  uv run scripts/backtest_swing.py --record report/recommend-cn-20260908.md   # 记录一份报告的 TOP10
  uv run scripts/backtest_swing.py --report                                   # 对已记录标的统计 T+5/T+10 收益
  uv run scripts/backtest_swing.py --report --days 5,10,20                     # 自定义观察窗口

记录文件：report/swing_backtest.jsonl（每行一个标的）
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from datetime import date, datetime, timedelta

# 项目根目录加入 sys.path（与其他 scripts/*.py 一致，保证 scripts.quantrisk 可导入）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BACKTEST_FILE = os.path.join(os.path.dirname(__file__), "..", "report", "swing_backtest.jsonl")


def _record_from_report(path: str) -> list[dict]:
    """从 recommend 报告 markdown 提取 TOP10：解析 '#### N. 名称（代码）— 状态' 和总分。"""
    records = []
    lines = open(path, encoding="utf-8").read().splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"####\s+\d+\.\s+(.+?)（(\d{5,6})）—\s*(.+)$", line.strip())
        if not m:
            continue
        name, code, status = m.group(1), m.group(2), m.group(3)
        total = 0.0
        # 下一行是 **现价**：X | **总分**：89.0/100 | ...
        if i + 1 < len(lines):
            tm = re.search(r"\*\*总分\*\*：([\d.]+)", lines[i + 1])
            if tm:
                total = float(tm.group(1))
        records.append({"date": date.today().isoformat(), "code": code, "name": name,
                        "status": status, "total": total, "file": os.path.basename(path)})
    return records


async def _fetch_close(code: str, market: str) -> list[float]:
    """拉取日K收盘价序列（复用数据层源链）。"""
    from scripts.quantrisk.data import cn_stock_kline_tencent_async, hk_kline_tencent_async, close_async_session
    if market == "cn":
        rows = await cn_stock_kline_tencent_async(code, days=300, period="day")
    else:
        rows = await hk_kline_tencent_async(code, period="day", count=300)
    pairs = []
    for r in rows:
        try:
            pairs.append((str(r.get("date", ""))[:10], float(r.get("close"))))
        except (TypeError, ValueError):
            continue
    # 按日期升序
    pairs.sort(key=lambda x: x[0])
    return pairs


def _returns(pairs: list[tuple[str, float]], record_date: str, days: int) -> float | None:
    """前瞻收益：以记录日 close 为基准，计算其后第 days 天的涨跌幅（%）。
    记录日或其后第 N 天缺失（数据不足/停牌）返回 None。"""
    idx = None
    for i, (d, _) in enumerate(pairs):
        if d >= record_date:
            idx = i
            break
    if idx is None or idx + days >= len(pairs):
        return None
    base = pairs[idx][1]
    later = pairs[idx + days][1]
    if base <= 0:
        return None
    return round((later - base) / base * 100, 2)


async def _report(days_list: list[int]) -> None:
    if not os.path.exists(BACKTEST_FILE):
        print(f"无记录文件：{BACKTEST_FILE}（先跑 --record）")
        return
    records = [json.loads(l) for l in open(BACKTEST_FILE, encoding="utf-8") if l.strip()]
    if not records:
        print("记录为空")
        return
    # 按市场分组（A股6位/港股5位）
    groups = {"cn": [], "hk": []}
    for r in records:
        groups["cn" if len(r["code"]) == 6 else "hk"].append(r)
    for market, items in groups.items():
        if not items:
            continue
        print(f"\n=== {market} 波段推荐回测（{len(items)} 条记录）===")
        print(f"{'日期':<12}{'代码':<8}{'名称':<12}{'状态':<14}" + "".join(f"{'T+'+str(d):>8}" for d in days_list))
        wins = {d: [0, 0] for d in days_list}
        for r in items:
            pairs = await _fetch_close(r["code"], market)
            rets = {d: _returns(pairs, r["date"], d) for d in days_list}
            row = f"{r['date']:<12}{r['code']:<8}{r['name']:<12}{r['status'][:12]:<14}"
            for d in days_list:
                v = rets[d]
                row += f"{v if v is not None else '—':>8}"
                if v is not None:
                    wins[d][0] += 1
                    wins[d][1] += int(v > 0)
            print(row)
        print("\n胜率统计：")
        for d in days_list:
            n, w = wins[d]
            if n:
                print(f"  T+{d}: 胜率 {w}/{n} = {w/n*100:.0f}%（注：仅统计有数据的记录）")
            else:
                print(f"  T+{d}: 数据不足")
        # Q6: 按分数段分组胜率（验证高分是否真高胜率）
        bands = {"≥85": (85, 1000), "80-84": (80, 85), "<80": (0, 80)}
        print("\n按总分分段（T+最短窗口）：")
        d0 = days_list[0]
        for label, (lo, hi) in bands.items():
            grp = [r for r in items if lo <= r.get("total", 0) < hi]
            if not grp:
                print(f"  {label}: 无样本")
                continue
            n = w = 0
            for r in grp:
                pairs = await _fetch_close(r["code"], market)
                v = _returns(pairs, r["date"], d0)
                if v is not None:
                    n += 1
                    w += int(v > 0)
            print(f"  {label}: {len(grp)}条, 有数据{n}条, 胜率 {w}/{n} = {w/n*100:.0f}%" if n else f"  {label}: {len(grp)}条, 数据不足")
        # Q7: 按状态分组胜率（验证三档区分度）
        print("\n按状态分组（T+最短窗口）：")
        for st_label in ("当前可布局", "谨慎布局", "观望"):
            grp = [r for r in items if r.get("status", "").startswith(st_label)]
            if not grp:
                continue
            n = w = 0
            for r in grp:
                pairs = await _fetch_close(r["code"], market)
                v = _returns(pairs, r["date"], d0)
                if v is not None:
                    n += 1
                    w += int(v > 0)
            print(f"  {st_label}: {len(grp)}条, 有数据{n}条, 胜率 {w}/{n} = {w/n*100:.0f}%" if n else f"  {st_label}: {len(grp)}条, 数据不足")
    from scripts.quantrisk.data import close_async_session
    await close_async_session()


async def _record(path: str) -> None:
    if not os.path.exists(path):
        print(f"报告不存在：{path}")
        return
    records = _record_from_report(path)
    os.makedirs(os.path.dirname(os.path.abspath(BACKTEST_FILE)), exist_ok=True)
    with open(BACKTEST_FILE, "a", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"已记录 {len(records)} 只标的 → {BACKTEST_FILE}")


def main() -> None:
    ap = argparse.ArgumentParser(description="波段推荐回测闭环")
    ap.add_argument("--record", metavar="REPORT", help="记录一份推荐报告的 TOP10")
    ap.add_argument("--report", action="store_true", help="统计已记录标的的 T+N 收益")
    ap.add_argument("--days", default="5,10,20", help="观察窗口，逗号分隔")
    args = ap.parse_args()
    if args.record:
        asyncio.run(_record(args.record))
    elif args.report:
        days = [int(x) for x in args.days.split(",") if x.strip().isdigit()]
        asyncio.run(_report(days))
    else:
        ap.print_help()


if __name__ == "__main__":
    main()