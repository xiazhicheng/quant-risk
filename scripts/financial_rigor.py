#!/usr/bin/env python3
"""Financial Rigor Toolkit — 金融数据精度验证工具。

借鉴 ai-berkshire 的 financial_rigor.py 设计思路，零外部依赖。

功能:
  - verify_market_cap: 市值验算（股价×总股本 vs 报告市值）
  - verify_valuation: 估值指标精确验算
  - cross_validate: 多源交叉验证
  - exact_calc: 精确计算器

用法:
    python3 scripts/financial_rigor.py verify-market-cap --price 37.6 --shares 9.0e9 --reported 338.4 --currency HKD
    python3 scripts/financial_rigor.py verify-valuation --price 37.6 --eps 3.5 --bvps 10.0
    python3 scripts/financial_rigor.py cross-validate --field PE --values '{"Tencent": 10.71, "Sina": 10.5}'
"""

import argparse
import json
import math
import sys
from decimal import Decimal, Context, ROUND_HALF_EVEN, InvalidOperation

# ── 精确 Decimal 引擎 ──────────────────────────────────────────

_CTX = Context(prec=28, rounding=ROUND_HALF_EVEN)


def exact(value) -> Decimal:
    """安全转换为 Decimal，避免 float 陷阱"""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(str(value))
    return Decimal(str(value))


def fmt_number(d: Decimal, unit: str = "") -> str:
    """格式化大数字为可读形式（亿/B/T）"""
    v = float(d)
    abs_v = abs(v)
    if unit in ("亿", "亿元", "亿港元", "亿美元"):
        if abs_v >= 10000:
            return f"{v/10000:.2f}万亿{unit[1:] if len(unit) > 1 else ''}"
        return f"{v:.2f}{unit}"
    if abs_v >= 1e12:
        return f"{v/1e12:.2f}T"
    if abs_v >= 1e9:
        return f"{v/1e9:.2f}B"
    if abs_v >= 1e6:
        return f"{v/1e6:.2f}M"
    return f"{v:,.2f}"


# ── 1. 市值验算 ────────────────────────────────────────────────

def verify_market_cap(price, shares, reported_cap, currency=""):
    """市值验算：股价×总股本 vs 报告市值。

    Args:
        price: 股价
        shares: 总股本（股，不是亿股）
        reported_cap: 报告市值（与价格币种相同）
        currency: 币种

    Returns:
        (passed: bool, deviation_pct: float, calculated: float, detail: str)
    """
    p = exact(price)
    s = exact(shares)
    r = exact(reported_cap)

    calculated = _CTX.multiply(p, s)
    r_float = float(r)
    if r_float == 0:
        return False, 0, float(calculated), "报告市值为0，无法验证"

    deviation = abs(float(calculated) - r_float) / r_float * 100

    if deviation > 5:
        status = "❌"
        passed = False
        detail = f"偏差{deviation:.1f}% > 5%, 请检查: 股本是否为最新? 单位是否一致?"
    elif deviation > 1:
        status = "⚠️"
        passed = True
        detail = f"偏差{deviation:.1f}% 在可接受范围, 可能因股价波动/股本变化"
    else:
        status = "✅"
        passed = True
        detail = f"偏差仅{deviation:.2f}%"

    return passed, deviation, float(calculated), detail


# ── 2. 估值验算 ────────────────────────────────────────────────

def verify_valuation(price, eps=None, bvps=None, fcf_per_share=None, dividend=None):
    """估值指标精确验算。

    Returns:
        dict: {pe, pb, roe, fcf_yield, dividend_yield, ...} 或 None
    """
    p = exact(price)
    results = {}

    if eps is not None:
        e = exact(eps)
        if e != 0:
            pe = _CTX.divide(p, e)
            results["PE"] = float(pe)
            ey = _CTX.divide(e, p) * 100
            results["Earnings_Yield"] = float(ey)

    if bvps is not None:
        b = exact(bvps)
        if b != 0:
            pb = _CTX.divide(p, b)
            results["PB"] = float(pb)
            if eps is not None and float(exact(eps)) != 0:
                roe = _CTX.divide(exact(eps), b) * 100
                results["ROE"] = float(roe)

    if fcf_per_share is not None:
        f = exact(fcf_per_share)
        if f != 0:
            pfcf = _CTX.divide(p, f)
            fcf_yield = _CTX.divide(f, p) * 100
            results["P_FCF"] = float(pfcf)
            results["FCF_Yield"] = float(fcf_yield)

    if dividend is not None:
        d = exact(dividend)
        if p != 0:
            div_yield = _CTX.divide(d, p) * 100
            results["Dividend_Yield"] = float(div_yield)

    return results if results else None


# ── 3. 多源交叉验证 ────────────────────────────────────────────

def cross_validate(field_name, source_values: dict, unit="", tolerance_pct=2.0):
    """多源数据交叉验证，中位数参考，偏差标记。

    Args:
        field_name: 字段名（如 "PE", "营收"）
        source_values: {"来源名": 数值, ...}
        unit: 单位
        tolerance_pct: 容差百分比

    Returns:
        (consensus, all_consistent, details)
        consensus: 共识值（中位数）
        all_consistent: 是否所有来源偏差 <= tolerance_pct
        details: [(source, value, deviation, status), ...]
    """
    values = {k: float(exact(v)) for k, v in source_values.items()}
    sources = list(values.keys())
    nums = list(values.values())

    # 中位数作为参考
    sorted_vals = sorted(nums)
    n = len(sorted_vals)
    median = sorted_vals[n // 2] if n % 2 == 1 else (sorted_vals[n//2-1] + sorted_vals[n//2]) / 2
    if median == 0:
        return 0, False, [(s, v, 0, "⚠️") for s, v in values.items()]

    details = []
    all_ok = True
    for src, val in values.items():
        dev = abs(val - median) / median * 100
        if dev > tolerance_pct:
            status = "❌"
            all_ok = False
        elif dev > 1.0:
            status = "⚠️"
        else:
            status = "✅"
        details.append((src, val, dev, status))

    return median, all_ok, details


# ── CLI ────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Financial Rigor Toolkit")
    sub = parser.add_subparsers(dest="command")

    # verify-market-cap
    p1 = sub.add_parser("verify-market-cap", help="市值验算")
    p1.add_argument("--price", type=float, required=True)
    p1.add_argument("--shares", type=float, required=True)
    p1.add_argument("--reported", type=float, required=True)
    p1.add_argument("--currency", default="")

    # verify-valuation
    p2 = sub.add_parser("verify-valuation", help="估值验算")
    p2.add_argument("--price", type=float, required=True)
    p2.add_argument("--eps", type=float)
    p2.add_argument("--bvps", type=float)
    p2.add_argument("--fcf-per-share", type=float)
    p2.add_argument("--dividend", type=float)

    # cross-validate
    p3 = sub.add_parser("cross-validate", help="多源交叉验证")
    p3.add_argument("--field", required=True)
    p3.add_argument("--values", required=True, help='JSON: {"src1": val, "src2": val}')
    p3.add_argument("--unit", default="")
    p3.add_argument("--tolerance", type=float, default=2.0)

    args = parser.parse_args()

    if args.command == "verify-market-cap":
        passed, dev, calc, detail = verify_market_cap(
            args.price, args.shares, args.reported, args.currency
        )
        print(f"市值验算: 股价{args.price}×总股本{args.shares:.2e}")
        print(f"  计算市值: {fmt_number(exact(calc))} {args.currency}")
        print(f"  报告市值: {fmt_number(exact(args.reported))} {args.currency}")
        print(f"  偏差: {dev:.2f}% | {detail}")
        sys.exit(0 if passed else 1)

    elif args.command == "verify-valuation":
        results = verify_valuation(
            args.price, args.eps, args.bvps,
            getattr(args, "fcf_per_share", None), args.dividend
        )
        if not results:
            print("估值验算: 数据不足")
            sys.exit(1)
        print(f"估值验算 (股价={args.price})")
        for k, v in results.items():
            print(f"  {k}: {v:.2f}")
        sys.exit(0)

    elif args.command == "cross-validate":
        values = json.loads(args.values)
        consensus, all_ok, details = cross_validate(
            args.field, values, args.unit, args.tolerance
        )
        print(f"交叉验证: {args.field}")
        print(f"  共识值(中位数): {consensus:.2f} {args.unit}")
        for src, val, dev, status in details:
            print(f"  {status} {src}: {val:.2f} (偏差{dev:.2f}%)")
        print(f"  结果: {'✅ 一致' if all_ok else '⚠️ 存在差异'}")
        sys.exit(0 if all_ok else 1)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()