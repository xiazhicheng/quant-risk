import asyncio

from scripts.quantrisk import data


def _bars(n, start="2026-01-01"):
    return [{"date": f"{start}", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 100} for _ in range(n)]


def test_hk_kline_tencent_sufficient_no_yahoo_call(monkeypatch):
    """腾讯 ≥20 根即停，不触发 Yahoo 兜底。"""
    called = {"yahoo": False}

    async def fake_tencent(code, period="day", count=120):
        return _bars(100)

    async def fake_yahoo(symbol, interval="1d", range_="1y"):
        called["yahoo"] = True
        return _bars(200)

    monkeypatch.setattr(data, "hk_kline_tencent_async", fake_tencent)
    monkeypatch.setattr(data, "stock_kline_yahoo_async", fake_yahoo)
    rows = asyncio.run(data.hk_kline_async("00700", "day", 365))
    assert len(rows) == 100
    assert called["yahoo"] is False


def test_hk_kline_yahoo_fallback(monkeypatch):
    """腾讯不足 20 根时，Yahoo 兜底生效。"""
    async def fake_tencent(code, period="day", count=120):
        return _bars(5)

    async def fake_yahoo(symbol, interval="1d", range_="1y"):
        return _bars(30)

    monkeypatch.setattr(data, "hk_kline_tencent_async", fake_tencent)
    monkeypatch.setattr(data, "stock_kline_yahoo_async", fake_yahoo)
    rows = asyncio.run(data.hk_kline_async("00700", "day", 365))
    assert len(rows) == 30


def test_hk_kline_fail_closed(monkeypatch):
    """双源全挂返回 []，不伪造数据、不抛异常。"""
    async def fake_tencent(code, period="day", count=120):
        return []

    async def fake_yahoo(symbol, interval="1d", range_="1y"):
        return []

    monkeypatch.setattr(data, "hk_kline_tencent_async", fake_tencent)
    monkeypatch.setattr(data, "stock_kline_yahoo_async", fake_yahoo)
    rows = asyncio.run(data.hk_kline_async("00700", "day", 365))
    assert rows == []


def test_hk_kline_yahoo_exception_returns_tencent_partial(monkeypatch):
    """Yahoo 抛异常时不炸，回退腾讯已有数据（可为空）。"""
    async def fake_tencent(code, period="day", count=120):
        return _bars(3)

    async def fake_yahoo(symbol, interval="1d", range_="1y"):
        raise RuntimeError("rate limited")

    monkeypatch.setattr(data, "hk_kline_tencent_async", fake_tencent)
    monkeypatch.setattr(data, "stock_kline_yahoo_async", fake_yahoo)
    rows = asyncio.run(data.hk_kline_async("00700", "day", 365))
    assert len(rows) == 3


def test_hk_kline_weekly_tencent_only(monkeypatch):
    """周K单点：腾讯足够即停，Yahoo 不被调用。"""
    called = {"yahoo": False}

    async def fake_tencent(code, period="day", count=120):
        return _bars(30)

    async def fake_yahoo(symbol, interval="1d", range_="1y"):
        called["yahoo"] = True
        return _bars(30)

    monkeypatch.setattr(data, "hk_kline_tencent_async", fake_tencent)
    monkeypatch.setattr(data, "stock_kline_yahoo_async", fake_yahoo)
    rows = asyncio.run(data.hk_kline_async("00700", "week", 120))
    assert len(rows) == 30
    assert called["yahoo"] is False


def test_hk_kline_weekly_empty_no_yahoo(monkeypatch):
    """周K腾讯空时返回 []，不触发 Yahoo（周K无兜底）。"""
    called = {"yahoo": False}

    async def fake_tencent(code, period="day", count=120):
        return []

    async def fake_yahoo(symbol, interval="1d", range_="1y"):
        called["yahoo"] = True
        return _bars(30)

    monkeypatch.setattr(data, "hk_kline_tencent_async", fake_tencent)
    monkeypatch.setattr(data, "stock_kline_yahoo_async", fake_yahoo)
    rows = asyncio.run(data.hk_kline_async("00700", "week", 120))
    assert rows == []
    assert called["yahoo"] is False


def test_get_json_http_error_returns_empty(monkeypatch):
    """1d：_get_json 非 2xx 返回 {}，不抛异常。"""
    class FakeResp:
        status = 429
        async def text(self):
            return "<html>rate limited</html>"

    class FakeCtx:
        async def __aenter__(self):
            return FakeResp()
        async def __aexit__(self, *a):
            return False

    class FakeSession:
        def get(self, url, **kw):
            return FakeCtx()

    async def fake_session():
        return FakeSession()

    monkeypatch.setattr(data, "get_async_session", fake_session)
    assert asyncio.run(data._get_json("https://example.com/x")) == {}
    assert asyncio.run(data._get("https://example.com/x")) == ""


def test_get_json_bad_body_returns_empty(monkeypatch):
    """1d：_get_json 非 JSON 响应返回 {}，不抛 JSONDecodeError。"""
    class FakeResp:
        status = 200
        async def text(self):
            return "<html>not json</html>"

    class FakeCtx:
        async def __aenter__(self):
            return FakeResp()
        async def __aexit__(self, *a):
            return False

    class FakeSession:
        def get(self, url, **kw):
            return FakeCtx()

    async def fake_session():
        return FakeSession()

    monkeypatch.setattr(data, "get_async_session", fake_session)
    assert asyncio.run(data._get_json("https://example.com/x")) == {}
