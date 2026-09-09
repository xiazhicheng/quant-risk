from scripts.quantrisk.feature_engine import build_feature_snapshot
from scripts.quantrisk.strategy_models import DataQuality, PositionState


def legacy_result(price=11.5, trail_pct=5.0):
    return {
        "market": "cn", "code": "600000", "as_of": "2026-09-09T15:00:00+08:00",
        "price": price, "total": 80, "error": "", "direction_conflict": False,
        "flow": {"quality": "VALUE", "available": True, "vol_ratio": 1.2, "pct_5d": 3.0},
        "stroke": {"direction": "up", "trend_direction": "up", "previous_low": 10.0,
                   "previous_high": 12.0, "conclusion": "道氏结论：🟢上升趋势"},
        "segment": {"direction": "up", "available": True,
                    "conclusion": "道氏结论：🟢上升趋势"},
        "stage": "公众参与", "health": {"healthy": True},
        "index_sync": {"sync": True, "quality": "VALUE"},
        "trail_pct": trail_pct,
    }


def test_feature_snapshot_preserves_enum_types():
    snapshot = build_feature_snapshot(legacy_result())
    assert snapshot.data_quality is DataQuality.VALUE
    assert snapshot.flow_quality is DataQuality.VALUE


def test_position_peak_drives_trailing_stop():
    position = PositionState("cn", "600000", "swing_band",
                             quantity=100, available_quantity=100,
                             entry_price=10.0, entry_time="2026-09-01",
                             max_close_since_entry=12.0)
    snapshot = build_feature_snapshot(legacy_result(price=11.3, trail_pct=5.0), position=position)
    assert snapshot.metadata["position_trail_stop"] == 11.4
    assert snapshot.trail_stop_hit is True


def test_missing_flow_blocks_feature_snapshot():
    result = legacy_result()
    result["flow"] = {"quality": "MISSING", "available": False, "vol_ratio": 1.2}
    snapshot = build_feature_snapshot(result)
    assert snapshot.data_quality is DataQuality.MISSING
    assert "DATA_QUALITY_MISSING" in snapshot.risk_flags


def test_band_alias_normalizes_and_intraday_is_optional():
    """单策略归一：tactical/trend 别名都映射 swing_band，30m 是入场优化非硬门槛。"""
    band = build_feature_snapshot(legacy_result(), "swing_band")
    tactical = build_feature_snapshot(legacy_result(), "tactical")
    trend = build_feature_snapshot(legacy_result(), "trend")
    assert band.strategy_id == tactical.strategy_id == trend.strategy_id == "swing_band"
    assert band.intraday_confirmation_required is False
    assert band.metadata["ruleset_hash"] == tactical.metadata["ruleset_hash"] == trend.metadata["ruleset_hash"]
