import asyncio

from scripts.quantrisk import data


def test_30m_market_symbol_mapping(monkeypatch):
    seen = []

    async def fake_yahoo(symbol, interval="1d", range_="1y"):
        seen.append((symbol, interval, range_))
        return [{"date": f"2020-01-01 {i:02d}:00", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 100} for i in range(45)]

    monkeypatch.setattr(data, "stock_kline_yahoo_async", fake_yahoo)

    async def run():
        cn = await data.stock_kline_30m_async("600000", "cn")
        hk = await data.stock_kline_30m_async("09911", "hk")
        return cn, hk

    cn, hk = asyncio.run(run())
    assert cn["available"] is True
    assert hk["available"] is True
    assert seen[0][0] == "600000.SS"
    assert seen[1][0] == "9911.HK"
    assert all(item[1] == "30m" for item in seen)


def test_30m_failure_is_explicit(monkeypatch):
    async def fake_yahoo(*args, **kwargs):
        return []

    async def fake_empty(*args, **kwargs):
        return []

    for fn in ("stock_kline_30m_eastmoney_async", "stock_kline_30m_sina_async",
               "stock_kline_30m_tencent_async"):
        monkeypatch.setattr(data, fn, fake_empty)
    monkeypatch.setattr(data, "stock_kline_yahoo_async", fake_yahoo)
    result = asyncio.run(data.stock_kline_30m_async("000001", "cn"))
    assert result["available"] is False
    assert result["bar_count"] == 0
    assert "不足" in result["error"]


def test_30m_eastmoney_fallback(monkeypatch):
    """Yahoo 限流返回空时，东财回退生效且 source 标注为东财。"""

    async def fake_yahoo(*args, **kwargs):
        return []

    async def fake_em(code, market):
        return [{"date": f"2020-01-01 {i:02d}:00", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 100} for i in range(45)]

    async def fake_empty(*args, **kwargs):
        return []

    for fn in ("stock_kline_30m_sina_async", "stock_kline_30m_tencent_async"):
        monkeypatch.setattr(data, fn, fake_empty)
    monkeypatch.setattr(data, "stock_kline_yahoo_async", fake_yahoo)
    monkeypatch.setattr(data, "stock_kline_30m_eastmoney_async", fake_em)
    result = asyncio.run(data.stock_kline_30m_async("600054", "cn"))
    assert result["available"] is True
    assert result["source"] == "东财"
    assert result["bar_count"] == 45


def test_30m_sina_fallback(monkeypatch):
    """Yahoo 与东财都失败时，新浪 A股 30m 兜底生效。"""

    async def fake_empty(*args, **kwargs):
        return []

    async def fake_yahoo(*args, **kwargs):
        raise RuntimeError("Yahoo 403")

    async def fake_sina(code, market):
        return [{"date": f"2020-01-01 {i:02d}:00", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 100} for i in range(45)]

    for fn in ("stock_kline_30m_eastmoney_async", "stock_kline_30m_tencent_async"):
        monkeypatch.setattr(data, fn, fake_empty)
    monkeypatch.setattr(data, "stock_kline_yahoo_async", fake_yahoo)
    monkeypatch.setattr(data, "stock_kline_30m_sina_async", fake_sina)
    result = asyncio.run(data.stock_kline_30m_async("600054", "cn"))
    assert result["available"] is True
    assert result["source"] == "新浪"
    assert result["bar_count"] == 45


def test_30m_deduplicates(monkeypatch):
    async def fake_yahoo(*args, **kwargs):
        rows = [{"date": f"2020-01-01 {i:02d}:00", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 100} for i in range(44)]
        rows.append(rows[-1].copy())
        return rows

    monkeypatch.setattr(data, "stock_kline_yahoo_async", fake_yahoo)
    result = asyncio.run(data.stock_kline_30m_async("000001", "cn"))
    assert result["bar_count"] == 44
    assert len({x["date"] for x in result["bars"]}) == 44
