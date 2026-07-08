# Chan Theory (缠论) Module

**Source file**: `/quantrisk/chan.py` (~553 lines)

A complete implementation of the **Chan Zhong Shuo Chan (缠中说禅)** technical analysis framework. Pure Python calculations — no numpy, no pandas, no external dependencies.

---

## Pipeline Overview

```
K-lines (input)
    ↓
1. kline_contain()        — K-line containment processing
    ↓
2. find_fractals()         — Fractal identification (top/bottom)
    ↓
3. build_strokes()         — Strokes construction (笔)
    ↓
4. build_segments()        — Segments construction (线段)
    ↓
5. find_pivots()           — Pivot zones / central hubs (中枢)
    ↓
6. classify_trend()        — Trend classification
    ↓
7. detect_divergence()     — Divergence detection (背驰)
    ↓
8. find_buy_sell_points()  — Three types of buy/sell points
    ↓
9. chan_risk_assessment()  — Risk assessment integration (entry point)
```

---

## Functions

### 1. K-line Containment — `kline_contain(klines)`

Merges adjacent K-lines where one is fully "contained" within the other:

- **Upward direction**: Take the higher high and the higher low (向上取高高)
- **Downward direction**: Take the lower high and the lower low (向下取低低)
- Direction is determined by comparing the last two processed K-lines
- Merged volume is additive

*Lines 105-138*

### 2. Fractal Identification — `find_fractals(klines)`

Identifies top/bottom fractals:

- **Top fractal**: A K-line with a higher high than both its neighbors
- **Bottom fractal**: A K-line with a lower low than both its neighbors
- Returns list of `[{index, type, high, low, date}, ...]`

*Lines 141-159*

### 3. Strokes Construction — `build_strokes(klines, fractals)`

Builds strokes (笔) from the fractal sequence:

1. **Direction alternation**: Top and bottom fractals must alternate
2. **De-duplication**: Among same-direction fractals, keep the extreme one (highest top / lowest bottom)
3. **Minimum span**: A valid stroke requires ≥4 K-lines between start and end fractal (span ≥ 4)
4. **Skipping logic**: If adjacent fractals are the same type or span is too short, attempt to use a further fractal

Returns `[{type, start_index, end_index, direction, high, low}, ...]`

*Lines 162-200*

### 4. Segments Construction — `build_segments(klines, strokes)`

Builds segments (线段) from stroke sequences:

- Requires at least 3 strokes
- Three adjacent strokes must alternate direction and have a shared overlap zone
- Once established, extends the segment by including subsequent strokes as long as overlap persists
- When overlap breaks, the segment ends

Returns `[{start_index, end_index, stroke_count, direction, high, low}, ...]`

*Lines 203-241*

### 5. Pivot Zone Identification — `find_pivots(segments, min_overlap=3)`

Identifies pivot zones / central hubs (中枢):

- **Sliding window** over segments looking for ≥3 overlapping segments
- Overlap interval = intersection of all segment price ranges
- **ZG** = pivot zone top (the highest of the lows)
- **ZD** = pivot zone bottom (the lowest of the highs)
- **ZZ width** = ZG - ZD (zone width)
- Default `min_overlap=3` segments required

Returns `[{start_index, end_index, high, low, zg, zd, zz_width, segment_count}, ...]`

*Lines 244-275*

### 6. Trend Classification — `classify_trend(pivots, segments)`

Classifies the overall trend based on pivot count and position:

| Pivot Count | Type | Direction |
|-------------|------|-----------|
| 0 | Single-sided trend (单边) | Up/down based on segment direction majority |
| 1 | Consolidation (盘整) | Sided based on last segment direction |
| ≥2 | Trend (趋势) | Determined by comparing first and last pivot positions |

*Lines 278-304*

### 7. Divergence Detection — `detect_divergence(klines, segments, strokes)`

Detects bullish/bearish divergence (背驰) using MACD area comparison:

- Compares each adjacent pair of same-direction segments
- MACD **histogram area** is summed across each segment's date range
- **Bearish divergence** (顶背驰): Price higher, MACD area lower (< 85% of previous)
- **Bullish divergence** (底背驰): Price lower, MACD area lower (< 85% of previous)
- **Severity threshold**: 50% area = strong divergence; 85% = weak divergence

Returns `[{type, date, severity, detail}, ...]`

*Lines 307-364*

### 8. Buy/Sell Points — `find_buy_sell_points(klines, pivots, segments, divergences)`

Identifies the three classic Chan Theory buy/sell points:

| Point | Type | Condition |
|-------|------|-----------|
| 一买 | First buy | Bottom divergence (背驰终结) |
| 一卖 | First sell | Top divergence (背驰终结) |
| 二买 | Second buy | Price returns to pivot zone after first buy with support |
| 二卖 | Second sell | Price returns to pivot zone after first sell with resistance |
| 三买 | Third buy | Price pulls back to pivot zone top (ZG) without entering, then resumes up |
| 三卖 | Third sell | Price rallies to pivot zone bottom (ZD) without entering, then resumes down |

Returns `{buy_points: [{type, level, price, detail}], sell_points: [...]}`

*Lines 367-430*

### 9. Risk Assessment Integration — `chan_risk_assessment(klines)`

Entry-point function that runs the full pipeline and produces a risk assessment dictionary. Called by `StockAnalyzer._calc_technicals()`.

Returns:
```python
{
    "chan_verdict": str,          # "多方强势/偏多/盘整/偏空/空方强势"
    "chan_score": int,            # 1-5 score
    "chan_direction": str,        # "bullish"/"bearish"/"neutral"
    "strokes_count": int,
    "segments_count": int,
    "pivot_count": int,
    "trend": dict,                # From classify_trend()
    "divergences": list,
    "buy_points": list,
    "sell_points": list,
    "latest_zg": float,           # Most recent pivot zone top
    "latest_zd": float,           # Most recent pivot zone bottom
    "position_vs_pivot": str,     # "above"/"within"/"below" relative to latest pivot
}
```

*Lines 432-553*

---

## Key Parameters

| Parameter | Default | Effect |
|-----------|---------|--------|
| `min_overlap` | 3 | Minimum segments required to form a pivot zone |
| Divergence threshold | 85% | MACD area < 85% → divergence detected |
| Strong divergence | 50% | MACD area < 50% → strong divergence |
| Minimum stroke span | 4 | Minimum K-line gap between fractal pairs |


## Risk Assessment Logic

The `chan_risk_assessment()` function maps Chan Theory signals to a 1-5 score and directional verdict:

| Score | Verdict | Condition |
|-------|---------|-----------|
| 5 | 多方强势 (Strong bullish) | Bullish trend + buy signals + price above pivot zone |
| 4 | 偏多 (Leaning bullish) | Bullish trend or buy signals present |
| 3 | 盘整 (Consolidation) | No clear direction, within pivot zone |
| 2 | 偏空 (Leaning bearish) | Bearish trend or sell signals present |
| 1 | 空方强势 (Strong bearish) | Bearish trend + sell signals + price below pivot zone |

---

## Important Notes for Future Agents

- **All Chan functions assume K-line format**: `{"date", "open", "high", "low", "close", "volume"}`. This is the same format returned by all data sources.
- **No external dependencies**: Everything is pure Python. If you need to add new technical analysis features, keep them dependency-free.
- **Re-exported from indicators.py**: The module `/quantrisk/indicators.py` imports and re-exports all Chan Theory functions with `__all__`, so users can do `from quantrisk.indicators import chan_risk_assessment`.
- **K-line minimums**: The pipeline needs ≥20 K-lines for reliable results, ≥100 for proper pivot/segment analysis.
- **Performance**: All operations are O(n) or O(n²) on K-line count. For 500-1000 candles, runtime is negligible.