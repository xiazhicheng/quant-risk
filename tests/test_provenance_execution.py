from pathlib import Path

from scripts.quantrisk.execution import ExecutionGuard
from scripts.quantrisk.provenance import DecisionOutbox, build_receipt
from scripts.quantrisk.rule_engine import PythonReferenceRuleEngine
from scripts.quantrisk.strategy_models import (
    DataQuality,
    FeatureSnapshot,
    OrderIntent,
    RunMode,
)


def features():
    return FeatureSnapshot(
        market="cn", code="600000", strategy_id="swing_tactical_1w2w",
        as_of="2026-09-09T15:00:00+08:00", rank_score=80,
        data_quality=DataQuality.VALUE, suspended_or_delisted=False,
        daily_direction="up", intraday_direction="up", intraday_available=True,
        intraday_confirmation_required=True, direction_conflict=False,
        momentum_weak=False, overall_down=False, low_volume=False,
        overheated=False, stage="公众参与", health_ok=True, index_sync=True,
        close_below_previous_low=False, trail_stop_hit=False,
        previous_low=10, previous_high=12, current_close=11.5,
    )


def receipt(mode=RunMode.RESEARCH):
    f = features()
    d = PythonReferenceRuleEngine().evaluate(f)
    return build_receipt("run-1", f, d, "1.0.0", "rules-hash", mode,
                         snapshot_hash="snapshot-hash")


def test_receipt_hash_is_deterministic():
    assert receipt().receipt_hash == receipt().receipt_hash


def test_outbox_enqueue_is_idempotent(tmp_path):
    outbox = DecisionOutbox(tmp_path / "outbox.sqlite3")
    item = receipt()
    assert outbox.enqueue(item) == outbox.enqueue(item)
    assert len(outbox.pending()) == 1


def test_live_requires_provenance_id():
    item = receipt(RunMode.LIVE)
    order = OrderIntent("run-1", "cn", "600000", "BUY", 100,
                        item.signal_time, item.earliest_execution_time)
    ok, reason = ExecutionGuard().validate(item, order)
    assert ok is False and "provenance" in reason


def test_non_live_never_submits_real_order():
    item = receipt(RunMode.PAPER)
    order = OrderIntent("run-1", "cn", "600000", "BUY", 100,
                        item.signal_time, item.earliest_execution_time)
    ok, reason = ExecutionGuard().validate(item, order)
    assert ok is False and "仅live" in reason


def test_cn_lot_size_is_enforced():
    base = receipt(RunMode.LIVE)
    from dataclasses import replace
    item = replace(base, provenance_id="prov-1", audit_complete=True)
    order = OrderIntent("run-1", "cn", "600000", "BUY", 50,
                        item.signal_time, item.earliest_execution_time)
    ok, reason = ExecutionGuard().validate(item, order)
    assert ok is False and "100股" in reason
