"""
quantrisk — 缠论（Chan Theory）+ 技术指标计算模块

参考 czsc (https://github.com/waditu/czsc) 核心算法改进：
  - 分型识别改为严格 4 条件判断（顶分型需 high 和 low 同时最高，底分型需同时最低）
  - 笔构建使用极端值选取（向上笔选最高顶，向下笔选最低底）
  - 笔断裂后处理（最后笔被突破时回退合并）
  - 中枢直接在笔上识别（ZG=max(低), ZD=min(高)）
  - 背驰基于笔的 MACD 面积对比

用法:
    from scripts.quantrisk.chan import chan_risk_assessment, chan_theory_full
    assessment = chan_risk_assessment(klines)
"""


# ═══════════════════════════════════════════════
# Layer 3: 技术指标层（不改动）
# ═══════════════════════════════════════════════

def _ema(values: list[float], period: int) -> list[float]:
    result = [values[0]]
    k = 2 / (period + 1)
    for v in values[1:]:
        result.append(v * k + result[-1] * (1 - k))
    return result


def calc_ma(klines: list[dict], periods: list[int] = None) -> list[dict]:
    if periods is None:
        periods = [5, 10, 20, 60]
    closes = [k["close"] for k in klines]
    ema12, ema26 = _ema(closes, 12), _ema(closes, 26)
    result = []
    for i, k in enumerate(klines):
        row = {"date": k["date"], "close": k["close"]}
        for p in periods:
            row[f"ma{p}"] = round(sum(closes[i-p+1:i+1]) / p, 4) if i >= p-1 else None
        row["ema12"], row["ema26"] = round(ema12[i], 4), round(ema26[i], 4)
        result.append(row)
    return result


def calc_macd(klines: list[dict], fast: int = 12, slow: int = 26, signal: int = 9) -> list[dict]:
    closes = [k["close"] for k in klines]
    dif = [round(f - s, 4) for f, s in zip(_ema(closes, fast), _ema(closes, slow))]
    dea = _ema(dif, signal)
    return [{"date": k["date"], "close": k["close"],
             "dif": round(dif[i], 4), "dea": round(dea[i], 4),
             "macd_hist": round((dif[i] - dea[i]) * 2, 4)}
            for i, k in enumerate(klines)]


def calc_rsi(klines: list[dict], periods: list[int] = None) -> list[dict]:
    if periods is None:
        periods = [6, 12, 24]
    closes = [k["close"] for k in klines]
    changes = [0.0] + [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains, losses = [max(c, 0) for c in changes], [max(-c, 0) for c in changes]
    result = []
    for i, k in enumerate(klines):
        row = {"date": k["date"], "close": k["close"]}
        for p in periods:
            if i < p:
                row[f"rsi{p}"] = None; continue
            ag, al = sum(gains[i-p+1:i+1])/p, sum(losses[i-p+1:i+1])/p
            row[f"rsi{p}"] = 100.0 if al == 0 else round(100 - 100/(1+ag/al), 2)
        result.append(row)
    return result


def calc_kdj(klines: list[dict], n: int = 9, m1: int = 3, m2: int = 3) -> list[dict]:
    k_val, d_val = 50.0, 50.0
    result = []
    for i, kline in enumerate(klines):
        if i < n - 1:
            result.append({"date": kline["date"], "close": kline["close"],
                           "k": None, "d": None, "j": None}); continue
        w = klines[i-n+1:i+1]
        hn, ln = max(i["high"] for i in w), min(i["low"] for i in w)
        rsv = (kline["close"]-ln)/(hn-ln)*100 if hn != ln else 50.0
        k_val, d_val = (1/n)*rsv + (1-1/n)*k_val, (1/m2)*k_val + (1-1/m2)*d_val
        result.append({"date": kline["date"], "close": kline["close"],
                       "k": round(k_val, 2), "d": round(d_val, 2), "j": round(3*k_val-2*d_val, 2)})
    return result


def calc_boll(klines: list[dict], period: int = 20, num_std: float = 2.0) -> list[dict]:
    closes = [k["close"] for k in klines]
    result = []
    for i, k in enumerate(klines):
        if i < period - 1:
            result.append({"date": k["date"], "close": k["close"],
                           "upper": None, "middle": None, "lower": None, "bandwidth": None})
            continue
        w = closes[i-period+1:i+1]
        ma, std = sum(w)/period, (sum((x-sum(w)/period)**2 for x in w)/period)**0.5
        up, lo = ma+num_std*std, ma-num_std*std
        result.append({"date": k["date"], "close": k["close"],
                       "upper": round(up, 4), "middle": round(ma, 4), "lower": round(lo, 4),
                       "bandwidth": round((up-lo)/ma*100, 2) if ma else None})
    return result


# ═══════════════════════════════════════════════
# Layer 3.5: 缠论层（参考 czsc 改进版）
# ═══════════════════════════════════════════════

def _merge_bar(a: dict, b: dict, direction: str) -> dict:
    """合并两根K线（包含关系处理），返回合并后的 dict。

    参考 czsc remove_include:
      - 向上取高高: high=max, low=max
      - 向下取低低: high=min, low=min
      - 合并成交量
      - 记录 elements（被合并的原始K线）
    """
    if direction == "up":
        merged = {
            "high": max(a["high"], b["high"]),
            "low": max(a["low"], b["low"]),
            "date": b["date"],
            "open": a["open"],
            "close": b["close"] if b["close"] > a["close"] else a["close"],
        }
    else:
        merged = {
            "high": min(a["high"], b["high"]),
            "low": min(a["low"], b["low"]),
            "date": b["date"],
            "open": a["open"],
            "close": b["close"] if b["close"] < a["close"] else a["close"],
        }
    merged["volume"] = a.get("volume", 0) + b.get("volume", 0)
    # 追踪原始K线
    a_elems = a.get("_elements", [a])
    b_elems = b.get("_elements", [b])
    merged["_elements"] = a_elems + b_elems
    return merged


def _determine_direction(a: dict, b: dict) -> str:
    """判断K线方向（参考 czsc: 比较 a.high 和 b.high）"""
    if b["high"] > a["high"]:
        return "up"
    elif b["high"] < a["high"]:
        return "down"
    return "up"  # 相等时默认向上


def kline_contain(klines: list[dict]) -> list[dict]:
    """
    K线包含处理（参考 czsc remove_include 改进版）。

    流程：
      1. 以最初两根K线确定方向（up/down）
      2. 检查第三根是否与第二根包含
      3. 包含则合并，不包含则追加并更新方向
      4. 合并后的K线记录被合并的原始K线（_elements 字段）
    """
    if len(klines) < 3:
        return [dict(k) for k in klines]

    processed = [dict(klines[0])]
    processed[0]["_elements"] = [processed[0]]

    i = 1
    while i < len(klines):
        curr = dict(klines[i])
        curr["_elements"] = [curr]

        if len(processed) < 2:
            processed.append(curr)
            i += 1
            continue

        prev = processed[-1]
        prev2 = processed[-2]

        # 用前两根K线确定方向
        direction = _determine_direction(prev2, prev)

        # 检查 curr 是否与 prev 包含
        has_inclusion = (
            (curr["high"] >= prev["high"] and curr["low"] <= prev["low"]) or
            (curr["high"] <= prev["high"] and curr["low"] >= prev["low"])
        )

        if has_inclusion:
            # 合并 prev 和 curr
            merged = _merge_bar(prev, curr, direction)
            processed[-1] = merged
        else:
            processed.append(curr)

        i += 1

    return processed


def find_fractals(klines: list[dict]) -> list[dict]:
    """
    识别顶分型和底分型（参考 czsc check_fx 严格 4 条件）。

    顶分型（Mark=G）：中间K线的高点和低点都最高
      k1.high < k2.high AND k2.high > k3.high
      AND k1.low < k2.low AND k2.low > k3.low

    底分型（Mark=D）：中间K线的低点和高点都最低
      k1.low > k2.low AND k2.low < k3.low
      AND k1.high > k2.high AND k2.high < k3.high

    返回 [{index, type("top"/"bottom"), high, low, fx, date}, ...]
    fx 为顶分型的 high 或底分型的 low
    """
    if len(klines) < 3:
        return []

    processed = kline_contain(klines)
    fractals = []

    for i in range(1, len(processed) - 1):
        k1, k2, k3 = processed[i - 1], processed[i], processed[i + 1]

        # 顶分型检查：k2的高点和低点都最高
        if (k1["high"] < k2["high"] and k2["high"] > k3["high"] and
            k1["low"] < k2["low"] and k2["low"] > k3["low"]):
            fractals.append({
                "index": i,
                "type": "top",
                "high": k2["high"],
                "low": k2["low"],
                "fx": k2["high"],
                "date": k2["date"],
                "kline": k2,
            })

        # 底分型检查：k2的低点和高点都最低
        elif (k1["low"] > k2["low"] and k2["low"] < k3["low"] and
              k1["high"] > k2["high"] and k2["high"] < k3["high"]):
            fractals.append({
                "index": i,
                "type": "bottom",
                "high": k2["high"],
                "low": k2["low"],
                "fx": k2["low"],
                "date": k2["date"],
                "kline": k2,
            })

    return fractals


def _filter_alternating_fractals(fractals: list[dict], min_bi_len: int = 6) -> list[dict]:
    """过滤相邻同向分型，保留更极端的一个，确保严格交替。

    参考 czsc check_fxs + check_bi:
      - 连续顶分型取最高
      - 连续底分型取最低
      - 间距不足 min_bi_len 的舍弃
    """
    if not fractals:
        return []

    filtered = [fractals[0]]

    for f in fractals[1:]:
        last = filtered[-1]

        if f["type"] == last["type"]:
            # 同向分型，取更极端值
            if f["type"] == "top" and f["fx"] > last["fx"]:
                filtered[-1] = f  # 顶更高，替换
            elif f["type"] == "bottom" and f["fx"] < last["fx"]:
                filtered[-1] = f  # 底更低，替换
        else:
            # 异向分型，检查间距
            span = f["index"] - last["index"]
            if span >= min_bi_len:
                filtered.append(f)

    return filtered


def build_strokes(klines: list[dict], fractals: list[dict] = None, min_bi_len: int = 6) -> list[dict]:
    """
    从分型序列构建笔（参考 czsc check_bi 改进版）。

    核心逻辑：
      1. 从首个分型开始
      2. 向上笔（D→G）：选取最高顶（fx 最大）作为终点
      3. 向下笔（G→D）：选取最低底（fx 最小）作为终点
      4. 检查两分型是否相互包含（包含关系则舍弃）
      5. 检查间距 >= min_bi_len
      6. 处理笔断裂：最新笔被突破时回退合并

    Args:
        klines: 原始K线列表
        fractals: 分型列表（可选，自动计算）
        min_bi_len: 笔的最小K线数（默认6，对齐czsc）

    Returns:
        [{type, direction, start_index, end_index, start_date, end_date,
          high, low, fx_a, fx_b, ...}]
    """
    if fractals is None:
        fractals = find_fractals(klines)

    # 先过滤交替分型
    filtered = _filter_alternating_fractals(fractals, min_bi_len=min_bi_len)

    if len(filtered) < 2:
        return []

    strokes = []
    i = 0

    while i < len(filtered) - 1:
        fx_a = filtered[i]
        direction = "up" if fx_a["type"] == "bottom" else "down"

        # 寻找最优配对分型
        fx_b = None
        j = i + 1
        while j < len(filtered):
            candidate = filtered[j]
            if candidate["type"] != fx_a["type"]:
                # 判断是否满足方向条件
                if direction == "up":
                    # 向上笔：底→顶，顶的 fx 必须 > 底的 fx
                    if candidate["fx"] > fx_a["fx"]:
                        if fx_b is None:
                            fx_b = candidate
                            j += 1
                            continue
                        # 在符合条件的顶中选最高的
                        if candidate["fx"] > fx_b["fx"]:
                            # 检查间距
                            span = candidate["index"] - fx_a["index"]
                            if span >= min_bi_len:
                                fx_b = candidate
                else:
                    # 向下笔：顶→底，底的 fx 必须 < 顶的 fx
                    if candidate["fx"] < fx_a["fx"]:
                        if fx_b is None:
                            fx_b = candidate
                            j += 1
                            continue
                        # 在符合条件的底中选最低的
                        if candidate["fx"] < fx_b["fx"]:
                            span = candidate["index"] - fx_a["index"]
                            if span >= min_bi_len:
                                fx_b = candidate
            j += 1

        if fx_b is None:
            i += 1
            continue

        # 检查分型间是否相互包含（包含关系则笔不成立）
        ab_include = (
            (fx_a["high"] > fx_b["high"] and fx_a["low"] < fx_b["low"]) or
            (fx_a["high"] < fx_b["high"] and fx_a["low"] > fx_b["low"])
        )
        if ab_include:
            i += 1
            continue

        # 检查间距
        span = fx_b["index"] - fx_a["index"]
        if span < min_bi_len:
            i += 1
            continue

        # 构建笔
        stroke = {
            "type": fx_a["type"],
            "direction": direction,
            "start_index": fx_a["index"],
            "end_index": fx_b["index"],
            "start_date": fx_a["date"],
            "end_date": fx_b["date"],
            "high": max(fx_a["high"], fx_b["high"]),
            "low": min(fx_a["low"], fx_b["low"]),
            "fx_a": fx_a,
            "fx_b": fx_b,
        }
        strokes.append(stroke)
        i = filtered.index(fx_b)

    # 处理笔断裂：最后向上笔的高点被突破，或最后向下笔的低点被跌破
    if strokes and len(strokes) >= 1 and klines:
        last_stroke = strokes[-1]
        last_price = klines[-1]["close"]
        if last_stroke["direction"] == "up":
            # 向上笔：如果最新价格突破笔的高点，标记为断裂
            if last_price > last_stroke["high"]:
                strokes[-1]["broken"] = True
        elif last_stroke["direction"] == "down":
            # 向下笔：如果最新价格跌破笔的低点，标记为断裂
            if last_price < last_stroke["low"]:
                strokes[-1]["broken"] = True

    return strokes


def build_segments(klines: list[dict], strokes: list[dict] = None) -> list[dict]:
    """从笔构建线段（保留原逻辑，兼容 czsc 笔结构）。"""
    if strokes is None:
        strokes = build_strokes(klines)
    if len(strokes) < 3:
        return []
    segments = []
    i = 0
    while i <= len(strokes) - 3:
        s1, s2, s3 = strokes[i], strokes[i + 1], strokes[i + 2]
        if s1["direction"] == s2["direction"] or s2["direction"] == s3["direction"]:
            i += 1
            continue
        overlap_high = min(s1["high"], s2["high"], s3["high"])
        overlap_low = max(s1["low"], s2["low"], s3["low"])
        if overlap_high <= overlap_low:
            i += 1
            continue
        j = i + 3
        while j < len(strokes):
            next_s = strokes[j]
            new_high = min(overlap_high, next_s["high"])
            new_low = max(overlap_low, next_s["low"])
            if new_high <= new_low:
                break
            overlap_high, overlap_low = new_high, new_low
            j += 1
        seg = {
            "start_index": strokes[i]["start_index"],
            "end_index": strokes[j - 1]["end_index"],
            "start_date": strokes[i]["start_date"],
            "end_date": strokes[j - 1]["end_date"],
            "high": max(s["high"] for s in strokes[i:j]),
            "low": min(s["low"] for s in strokes[i:j]),
            "stroke_count": j - i,
            "direction": s1["direction"],
        }
        segments.append(seg)
        i = j
    return segments


def find_pivots(strokes: list[dict], min_overlap: int = 3) -> list[dict]:
    """
    从笔中识别中枢（参考 czsc ZS 实现）。

    中枢三要素（ZG/ZD/ZZ）：
      - ZG（中枢上沿）= 前3笔 high 的最小值
      - ZD（中枢下沿）= 前3笔 low 的最大值
      - ZG >= ZD 则中枢有效
      - GG（中枢最高点）= 所有笔中 high 的最大值
      - DD（中枢最低点）= 所有笔中 low 的最小值

    与旧版区别：直接在笔上识别，不再通过线段过渡。
    """
    if len(strokes) < min_overlap:
        return []
    pivots = []
    i = 0
    while i <= len(strokes) - min_overlap:
        # 取前3笔确定中枢区间
        s1, s2, s3 = strokes[i], strokes[i + 1], strokes[i + 2]
        zg = min(s1["high"], s2["high"], s3["high"])  # 中枢上沿
        zd = max(s1["low"], s2["low"], s3["low"])      # 中枢下沿

        if zg < zd:
            i += 1
            continue  # 中枢无效

        # 扩展：检查后续笔是否仍在中枢区间内
        gg = max(s1["high"], s2["high"], s3["high"])   # 中枢最高点
        dd = min(s1["low"], s2["low"], s3["low"])      # 中枢最低点

        j = i + 3
        while j < len(strokes):
            s = strokes[j]
            # 检查笔是否与中枢区间重叠
            in_zone = (
                (s["high"] >= zd and s["high"] <= zg) or
                (s["low"] >= zd and s["low"] <= zg) or
                (s["high"] >= zg and s["low"] <= zd)
            )
            if not in_zone:
                break
            gg = max(gg, s["high"])
            dd = min(dd, s["low"])
            j += 1

        pivots.append({
            "start_index": strokes[i]["start_index"],
            "end_index": strokes[j - 1]["end_index"],
            "start_date": strokes[i]["start_date"],
            "end_date": strokes[j - 1]["end_date"],
            "high": gg,
            "low": dd,
            "zg": zg,       # 中枢上沿
            "zd": zd,       # 中枢下沿
            "zz": round(zd + (zg - zd) * 0.5, 4),  # 中枢中轴
            "gg": gg,       # 中枢最高点
            "dd": dd,       # 中枢最低点
            "stroke_count": j - i,
            "zz_width": round(zg - zd, 4),
        })
        i = j
    return pivots


def classify_trend(pivots: list[dict], strokes: list[dict]) -> dict:
    """根据中枢数量识别走势类型（保留原逻辑，兼容新中枢结构）。"""
    if not pivots:
        if strokes:
            up_count = sum(1 for s in strokes if s["direction"] == "up")
            down_count = len(strokes) - up_count
            if up_count > down_count:
                return {"type": "uptrend", "pivot_count": 0, "direction": "up",
                        "description": "无中枢单边上涨"}
            else:
                return {"type": "downtrend", "pivot_count": 0, "direction": "down",
                        "description": "无中枢单边下跌"}
        return {"type": "unknown", "pivot_count": 0, "direction": "neutral",
                "description": "无足够数据判断"}
    if len(pivots) == 1:
        direction = "up" if strokes and strokes[-1]["direction"] == "up" else "down"
        return {"type": "consolidation", "pivot_count": 1, "direction": direction,
                "description": f"单中枢盘整（{'偏多' if direction=='up' else '偏空'}）"}
    first_pz = pivots[0]
    last_pz = pivots[-1]
    is_up = last_pz["gg"] > first_pz["gg"] and last_pz["dd"] > first_pz["dd"]
    if is_up:
        return {"type": "uptrend", "pivot_count": len(pivots),
                "direction": "up", "description": f"上涨趋势，含 {len(pivots)} 个中枢"}
    else:
        return {"type": "downtrend", "pivot_count": len(pivots),
                "direction": "down", "description": f"下跌趋势，含 {len(pivots)} 个中枢"}


def detect_divergence(klines: list[dict], strokes: list[dict] = None) -> list[dict]:
    """
    检测背驰（参考 czsc 思路改进版）。

    基于笔的 MACD 面积对比：
      - 相邻同向笔，后笔价格创新高/新低但 MACD 面积缩小 = 背驰
      - 面积缩小 15% 为弱背驰，50% 为强背驰
    """
    if strokes is None:
        strokes = build_strokes(klines)
    if not strokes or len(strokes) < 2:
        return []

    macd_data = calc_macd(klines)
    if not macd_data:
        return []

    macd_map = {m["date"]: m for m in macd_data}
    macd_dates = [m["date"] for m in macd_data]
    divergences = []

    for i in range(len(strokes) - 1):
        s1, s2 = strokes[i], strokes[i + 1]
        if s1["direction"] != s2["direction"]:
            continue

        def macd_area(start_date: str, end_date: str) -> float:
            area = 0.0
            in_range = False
            for d in macd_dates:
                if d >= start_date:
                    in_range = True
                if in_range:
                    if d > end_date:
                        break
                    m = macd_map.get(d, {})
                    hist = abs(m.get("macd_hist", 0))
                    area += hist
            return area

        s1_area = macd_area(s1["start_date"], s1["end_date"])
        s2_area = macd_area(s2["start_date"], s2["end_date"])

        if s1["direction"] == "up":
            price_higher = s2["high"] > s1["high"]
            macd_weaker = s2_area < s1_area * 0.85
            if price_higher and macd_weaker:
                severity = "strong" if s2_area < s1_area * 0.5 else "weak"
                divergences.append({
                    "type": "top_divergence",
                    "date": s2["end_date"],
                    "severity": severity,
                    "detail": f"顶背驰：{'强' if severity=='strong' else '弱'}，MACD 面积从 {s1_area:.1f} 衰减至 {s2_area:.1f}",
                    "stroke_index": i + 1,
                })
        else:
            price_lower = s2["low"] < s1["low"]
            macd_weaker = s2_area < s1_area * 0.85
            if price_lower and macd_weaker:
                severity = "strong" if s2_area < s1_area * 0.5 else "weak"
                divergences.append({
                    "type": "bottom_divergence",
                    "date": s2["end_date"],
                    "severity": severity,
                    "detail": f"底背驰：{'强' if severity=='strong' else '弱'}，MACD 面积从 {s1_area:.1f} 衰减至 {s2_area:.1f}",
                    "stroke_index": i + 1,
                })

    return divergences


def find_buy_sell_points(klines: list[dict], pivots: list[dict] = None,
                          strokes: list[dict] = None,
                          divergences: list[dict] = None) -> dict:
    """
    缠论三类买卖点定位（参考 czsc 分类逻辑改进版）。

    一买：底背驰后
    二买：一买后回调不创新低
    三买：价格突破中枢后回踩不入中枢
    一卖：顶背驰后
    二卖：一卖后反弹不创新高
    三卖：价格跌破中枢后反弹不进入中枢
    """
    if strokes is None:
        strokes = build_strokes(klines)
    if pivots is None:
        pivots = find_pivots(strokes)
    if divergences is None:
        divergences = detect_divergence(klines, strokes)

    result = {"buy_points": [], "sell_points": []}
    if not klines or len(klines) < 10:
        return result

    last_price = klines[-1]["close"]

    # 一买/一卖：底背驰/顶背驰
    for d in divergences:
        if d["type"] == "bottom_divergence":
            result["buy_points"].append({
                "type": "first_buy",
                "level": "strong" if d["severity"] == "strong" else "weak",
                "price": last_price,
                "detail": f"一买（{d['detail']}）",
            })
        elif d["type"] == "top_divergence":
            result["sell_points"].append({
                "type": "first_sell",
                "level": "strong" if d["severity"] == "strong" else "weak",
                "price": last_price,
                "detail": f"一卖（{d['detail']}）",
            })

    # 二买：一买后回调不创新低
    if result["buy_points"] and strokes and len(strokes) >= 2:
        # 找最近的下行笔的低点
        down_strokes = [s for s in strokes if s["direction"] == "down"]
        if down_strokes:
            last_down = down_strokes[-1]
            first_buy = result["buy_points"][0]
            if last_price > last_down["low"] * 1.01:  # 未创新低
                result["buy_points"].append({
                    "type": "second_buy",
                    "level": "potential",
                    "price": last_price,
                    "detail": f"二买：一买后回调不创新低（{last_down['low']}），当前 {last_price}",
                })

    # 三买：价格突破中枢上沿后回踩不入中枢
    if pivots and strokes:
        last_pivot = pivots[-1]
        # 中枢上方且有向上笔
        up_after_pivot = [s for s in strokes if s["direction"] == "up" and s["start_index"] >= last_pivot["end_index"]]
        if up_after_pivot and last_price > last_pivot["zg"]:
            result["buy_points"].append({
                "type": "third_buy",
                "level": "potential",
                "price": last_price,
                "detail": f"三买：价格 {last_price} 位于中枢上方 {last_pivot['zg']}，回踩不入中枢则确认",
            })

    # 二卖：一卖后反弹不创新高
    if result["sell_points"] and strokes and len(strokes) >= 2:
        up_strokes = [s for s in strokes if s["direction"] == "up"]
        if up_strokes:
            last_up = up_strokes[-1]
            if last_price < last_up["high"] * 0.99:  # 未创新高
                result["sell_points"].append({
                    "type": "second_sell",
                    "level": "potential",
                    "price": last_price,
                    "detail": f"二卖：一卖后反弹不创新高（{last_up['high']}），当前 {last_price}",
                })

    # 三卖：价格跌破中枢下沿
    if pivots:
        last_pivot = pivots[-1]
        if last_price < last_pivot["zd"]:
            result["sell_points"].append({
                "type": "third_sell",
                "level": "potential",
                "price": last_price,
                "detail": f"三卖：价格 {last_price} 跌破中枢下沿 {last_pivot['zd']}，反弹不回中枢则确认",
            })

    return result


def chan_theory_full(klines: list[dict], min_bi_len: int = 6) -> dict:
    """
    缠论全流程计算（参考 czsc 改进版）。

    流程：包含处理 → 分型 → 笔 → 线段 → 中枢 → 背驰 → 买卖点

    Args:
        klines: 原始K线列表
        min_bi_len: 笔的最小K线数（默认6，对齐czsc）

    Returns:
        完整缠论分析结构
    """
    if not klines or len(klines) < 10:
        return {"error": "K线数据不足（至少 10 根）"}

    klines_clean = kline_contain(klines)
    fractals = find_fractals(klines)
    strokes = build_strokes(klines, fractals, min_bi_len=min_bi_len)
    segments = build_segments(klines, strokes)
    pivots = find_pivots(strokes)
    divergences = detect_divergence(klines, strokes)
    buy_sell = find_buy_sell_points(klines, pivots, strokes, divergences)
    trend = classify_trend(pivots, strokes)

    return {
        "klines_count": len(klines),
        "klines_clean_count": len(klines_clean),
        "fractals_count": len(fractals),
        "fractals": fractals,
        "strokes_count": len(strokes),
        "strokes": strokes,
        "segments_count": len(segments),
        "segments": segments,
        "pivots_count": len(pivots),
        "pivots": pivots,
        "divergences_count": len(divergences),
        "divergences": divergences,
        "buy_sell_points": buy_sell,
        "trend": trend,
        "current_price": klines[-1]["close"] if klines else None,
    }


def chan_risk_assessment(klines: list[dict], min_bi_len: int = 6) -> dict:
    """
    基于缠论输出风控评估结论（兼容原接口，使用改进算法）。

    - 当前走势类型
    - 背驰信号
    - 买卖点区域
    - 中枢位置
    - 综合评分

    Args:
        klines: 原始K线列表
        min_bi_len: 笔的最小K线数

    Returns:
        dict 包含 trend/relative_position/risk_signals/chan_score/chan_verdict 等
    """
    result = chan_theory_full(klines, min_bi_len=min_bi_len)
    if "error" in result:
        return result

    trend = result["trend"]
    pivots = result["pivots"]
    divergences = result["divergences"]
    buy_sell = result["buy_sell_points"]
    strokes = result["strokes"]
    price = result["current_price"]

    relative_position = "unknown"
    distance_to_pivot = None
    if pivots:
        last_pz = pivots[-1]
        if price > last_pz["zg"]:
            relative_position = "above_pivot"
            distance_to_pivot = round((price - last_pz["zg"]) / last_pz["zg"] * 100, 2)
        elif price < last_pz["zd"]:
            relative_position = "below_pivot"
            distance_to_pivot = round((price - last_pz["zd"]) / last_pz["zd"] * 100, 2)
        else:
            relative_position = "within_pivot"
            distance_to_pivot = 0.0

    risk_signals = []
    for d in divergences:
        if d["type"] == "top_divergence":
            risk_signals.append({"signal": "bearish_divergence", "severity": d["severity"], "detail": d["detail"]})
        elif d["type"] == "bottom_divergence":
            risk_signals.append({"signal": "bullish_divergence", "severity": d["severity"], "detail": d["detail"]})
    if buy_sell.get("buy_points"):
        for bp in buy_sell["buy_points"]:
            risk_signals.append({"signal": f"{bp['type']}", "severity": bp.get("level", "potential"), "detail": bp["detail"]})
    if buy_sell.get("sell_points"):
        for sp in buy_sell["sell_points"]:
            risk_signals.append({"signal": f"{sp['type']}", "severity": sp.get("level", "potential"), "detail": sp["detail"]})
    if relative_position == "above_pivot":
        risk_signals.append({"signal": "above_pivot", "severity": "bullish",
                             "detail": f"价格位于中枢上方 {distance_to_pivot}%，偏强"})
    elif relative_position == "below_pivot":
        risk_signals.append({"signal": "below_pivot", "severity": "bearish",
                             "detail": f"价格位于中枢下方 {distance_to_pivot}%，偏弱"})
    else:
        risk_signals.append({"signal": "within_pivot", "severity": "neutral",
                             "detail": "价格在中枢内震荡，等待方向选择"})

    # 综合评分
    score = 0
    if trend["direction"] == "up":
        score += 2
    elif trend["direction"] == "down":
        score -= 2
    if relative_position == "above_pivot":
        score += 1
    elif relative_position == "below_pivot":
        score -= 1
    bull_div = sum(1 for d in divergences if d["type"] == "bottom_divergence")
    bear_div = sum(1 for d in divergences if d["type"] == "top_divergence")
    score += bull_div * 3 - bear_div * 3

    # 笔断裂信号
    if strokes and strokes[-1].get("broken"):
        if strokes[-1]["direction"] == "up":
            risk_signals.append({"signal": "bi_broken_up", "severity": "bullish",
                                 "detail": "最后向上笔被突破，上升延续"})
            score += 1
        else:
            risk_signals.append({"signal": "bi_broken_down", "severity": "bearish",
                                 "detail": "最后向下笔被跌破，下跌延续"})
            score -= 1

    if score >= 3:
        chan_verdict = "偏多"
    elif score <= -3:
        chan_verdict = "偏空"
    else:
        chan_verdict = "中性"

    return {
        "trend": trend,
        "relative_position": relative_position,
        "distance_to_pivot_pct": distance_to_pivot,
        "risk_signals": risk_signals,
        "chan_score": score,
        "chan_verdict": chan_verdict,
        "pivots": pivots,
        "strokes_count": result["strokes_count"],
        "segments_count": result["segments_count"],
        "divergences": divergences,
        "buy_sell_points": buy_sell,
        # 深度缠论数据（供推荐模板使用）
        "fractals": result.get("fractals", []),
        "strokes": result.get("strokes", []),
    }


__all__ = [
    # 技术指标
    "_ema", "calc_ma", "calc_macd", "calc_rsi", "calc_kdj", "calc_boll",
    # 缠论
    "kline_contain", "find_fractals", "build_strokes", "build_segments",
    "find_pivots", "classify_trend", "detect_divergence",
    "find_buy_sell_points", "chan_theory_full", "chan_risk_assessment",
]