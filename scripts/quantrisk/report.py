"""
quantrisk — StockAnalyzer: 一键全量分析入口
"""
import asyncio
from typing import Optional

from .data import (
    close_async_session, close_tickflow, hk_stock_quote_tencent_async, hk_stock_quote_sina_async,
    stock_kline_yahoo_async, key_statistics_async, key_indicators_eastmoney_async,
    kline_tickflow_async,
)
from .indicators import (
    calc_ma, calc_macd, calc_rsi, calc_kdj, calc_boll,
    calc_support_resistance, calc_stop_loss_take_profit,
    chan_risk_assessment,
)


class StockAnalyzer:
    """股票分析器 — 一键全量分析"""

    def __init__(self):
        self._session = None

    # ── 底层并行执行 ──

    async def _gather(self, *coros):
        return await asyncio.gather(*coros, return_exceptions=True)

    # ── 港股全量分析 ──

    async def analyze_hk(self, code: str) -> dict:
        """港股全量分析（行情+K线+技术+基本面+缠论）"""
        symbol = f"{int(code)}.HK" if code.isdigit() else code
        secucode = f"{code}.HK"

        # 并行获取
        qt_tx, qt_sina, yahoo_stats, indicators, klines = await self._gather(
            hk_stock_quote_tencent_async(code),
            hk_stock_quote_sina_async(code),
            key_statistics_async(symbol),
            key_indicators_eastmoney_async(secucode, page_size=4),
            stock_kline_yahoo_async(symbol, "1d", "2y"),
        )

        # 合并行情
        if isinstance(qt_tx, BaseException): qt_tx = {}
        if isinstance(qt_sina, BaseException): qt_sina = {}
        if isinstance(yahoo_stats, BaseException): yahoo_stats = {}
        if isinstance(indicators, BaseException): indicators = []
        if isinstance(klines, BaseException): klines = []

        quote = dict(qt_tx)
        if not quote.get("name") and isinstance(qt_sina, dict):
            quote["name"] = qt_sina.get("name", "")
        if not quote.get("price") and isinstance(qt_sina, dict):
            quote["price"] = qt_sina.get("price", 0)
            quote["change_pct"] = qt_sina.get("change_pct", 0)

        ind = indicators[0] if isinstance(indicators, list) and indicators else {}

        # 技术指标 — Yahoo K线不足时用 TickFlow 备选
        if not klines or len(klines) < 20:
            tickflow_klines = await kline_tickflow_async(f"{code}.HK", "1d", 730)
            if tickflow_klines and len(tickflow_klines) >= 20:
                klines = tickflow_klines
        tech = self._calc_technicals(klines, quote)

        return {
            "code": code,
            "name": quote.get("name", ""),
            "quote": quote,
            "yahoo_stats": yahoo_stats,
            "indicator": ind,
            "technicals": tech,
            "klines_count": len(klines) if isinstance(klines, list) else 0,
        }

    # ── A股全量分析 ──

    async def analyze_cn(self, code: str) -> dict:
        """A股全量分析"""
        from .data import (cn_stock_quote_tencent_async, cn_stock_basic_info_async,
                           cn_stock_kline_tencent_async, cn_key_indicators_async,
                           cn_concept_blocks_async)

        quote, klines, basic, ind, blocks = await self._gather(
            cn_stock_quote_tencent_async(code),
            cn_stock_kline_tencent_async(code, 730),
            cn_stock_basic_info_async(code),
            cn_key_indicators_async(code),
            cn_concept_blocks_async(code),
        )

        if isinstance(quote, BaseException): quote = {}
        if isinstance(klines, BaseException): klines = []
        if isinstance(ind, BaseException): ind = []
        if isinstance(blocks, BaseException): blocks = {}
        if isinstance(basic, BaseException): basic = {}

        # 腾讯K线不足时用 TickFlow 备选
        if not klines or len(klines) < 20:
            tf_code = f"{code}.SH" if code.startswith(("6","9")) else f"{code}.SZ"
            tickflow_klines = await kline_tickflow_async(tf_code, "1d", 730)
            if tickflow_klines and len(tickflow_klines) >= 20:
                klines = tickflow_klines
        tech = self._calc_technicals(klines, quote)

        return {
            "code": code,
            "name": quote.get("name", ""),
            "quote": quote,
            "basic_info": basic,
            "indicator": ind[0] if isinstance(ind, list) and ind else ind,
            "concept_blocks": blocks,
            "technicals": tech,
            "klines_count": len(klines) if isinstance(klines, list) else 0,
        }

    # ── 美股全量分析 ──

    async def analyze_us(self, ticker: str) -> dict:
        """美股全量分析"""
        from .data import (us_stock_quote_tencent_async, us_stock_quote_sina_async,)

        qt_tx, qt_sina, yahoo_stats, klines = await self._gather(
            us_stock_quote_tencent_async(ticker),
            us_stock_quote_sina_async(ticker),
            key_statistics_async(ticker.upper()),
            stock_kline_yahoo_async(ticker.upper(), "1d", "2y"),
        )

        if isinstance(qt_tx, BaseException): qt_tx = {}
        if isinstance(qt_sina, BaseException): qt_sina = {}
        if isinstance(yahoo_stats, BaseException): yahoo_stats = {}
        if isinstance(klines, BaseException): klines = []

        quote = qt_tx or {}
        if isinstance(qt_sina, dict) and qt_sina:
            # 用新浪补全腾讯缺失/异常字段
            if not quote.get("name"):
                quote["name"] = qt_sina.get("name", "")
            if not quote.get("price"):
                quote["price"] = qt_sina.get("price", 0)
            if not quote.get("open"):
                quote["open"] = qt_sina.get("open", 0)
            if not quote.get("pe") or quote["pe"] <= 0 or quote["pe"] > 5000:
                quote["pe"] = qt_sina.get("pe", quote["pe"])
            if not quote.get("high_52w") or quote["high_52w"] <= 0:
                quote["high_52w"] = qt_sina.get("high_52w", 0)
            if not quote.get("low_52w") or quote["low_52w"] <= 0:
                quote["low_52w"] = qt_sina.get("low_52w", 0)
            if not quote.get("market_cap") or quote["market_cap"] <= 0:
                quote["market_cap"] = qt_sina.get("market_cap", 0)

        # 美股K线不足时用 TickFlow 备选
        if not klines or len(klines) < 20:
            tickflow_klines = await kline_tickflow_async(f"{ticker.upper()}.US", "1d", 730)
            if tickflow_klines and len(tickflow_klines) >= 20:
                klines = tickflow_klines
        tech = self._calc_technicals(klines, quote)

        return {
            "code": ticker.upper(),
            "name": quote.get("name", ""),
            "quote": quote,
            "yahoo_stats": yahoo_stats,
            "technicals": tech,
            "klines_count": len(klines) if isinstance(klines, list) else 0,
        }

    # ── 批量分析 ──

    async def analyze_hk_batch(self, codes: list[str]) -> dict[str, dict]:
        """批量分析多只港股"""
        results = await asyncio.gather(
            *[self.analyze_hk(c) for c in codes], return_exceptions=True
        )
        out = {}
        for code, r in zip(codes, results):
            if isinstance(r, dict):
                out[code] = r
            else:
                out[code] = {"error": str(r)}
        return out

    # ── 技术指标统一计算 ──

    def _calc_technicals(self, klines: list[dict], quote: dict) -> dict:
        if not klines or len(klines) < 20:
            return {
                "error": "K线数据不足",
                "latest": None, "ma": {}, "macd": {}, "rsi": {},
                "boll": {}, "kdj": {}, "support_resistance": {},
                "stop_loss_take_profit": {}, "chan": {"error": "K线数据不足"},
            }

        ma = calc_ma(klines, [5, 10, 20, 60])
        macd = calc_macd(klines)
        rsi = calc_rsi(klines, [6, 14])
        boll = calc_boll(klines)
        kdj = calc_kdj(klines)
        sr = calc_support_resistance(klines)
        chan = chan_risk_assessment(klines)

        # 止损止盈（用ATR）
        stop = calc_stop_loss_take_profit(
            entry_price=quote.get("price", klines[-1]["close"]),
            klines=klines[-60:],
        )

        return {
            "latest": klines[-1] if klines else None,
            "ma": ma[-1] if ma else {},
            "macd": macd[-1] if macd else {},
            "rsi": rsi[-1] if rsi else {},
            "boll": boll[-1] if boll else {},
            "kdj": kdj[-1] if kdj else {},
            "support_resistance": sr,
            "stop_loss_take_profit": stop,
            "chan": chan,
        }

    async def close(self):
        await close_async_session()
        await close_tickflow()


# ── 便捷函数 ──

async def analyze_hk(code: str) -> dict:
    """一键分析港股"""
    a = StockAnalyzer()
    try:
        return await a.analyze_hk(code)
    finally:
        await a.close()


async def analyze_cn(code: str) -> dict:
    """一键分析A股"""
    a = StockAnalyzer()
    try:
        return await a.analyze_cn(code)
    finally:
        await a.close()


async def analyze_us(ticker: str) -> dict:
    """一键分析美股"""
    a = StockAnalyzer()
    try:
        return await a.analyze_us(ticker)
    finally:
        await a.close()


async def analyze_hk_batch(codes: list[str]) -> dict[str, dict]:
    """批量分析港股"""
    a = StockAnalyzer()
    try:
        return await a.analyze_hk_batch(codes)
    finally:
        await a.close()
