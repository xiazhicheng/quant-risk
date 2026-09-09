"""Deterministic strategy, decision, and execution data models.

These models are deliberately independent from Semantica. The trading core can
run without the optional decision dependency, while Semantica adapters consume
the same immutable facts when enabled.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class RunMode(str, Enum):
    RESEARCH = "research"
    PAPER = "paper"
    LIVE = "live"


class StrategyId(str, Enum):
    """单一波段策略；旧 tactical/trend 名保留为历史别名（normalize 后统一为 swing_band）。

    用户确认（2026-09-09）：高抛低吸、持有时间不确定——持有周期由道氏破前低/移动止盈
    离场信号自然决定，不做 1-2周 vs 1-2月 的策略拆分。"""
    BAND = "swing_band"


class Verdict(str, Enum):
    ALLOW = "ALLOW"
    WATCH = "WATCH"
    REDUCE = "REDUCE"
    EXIT = "EXIT"
    BLOCK = "BLOCK"


class DataQuality(str, Enum):
    VALUE = "VALUE"
    MISSING = "MISSING"
    STALE = "STALE"


VERDICT_PRECEDENCE = {
    Verdict.ALLOW: 0,
    Verdict.WATCH: 1,
    Verdict.REDUCE: 2,
    Verdict.EXIT: 3,
    Verdict.BLOCK: 4,
}


def canonical_json(value: Any) -> str:
    """Stable JSON representation used for hashes and replay receipts."""
    if hasattr(value, "to_dict"):
        value = value.to_dict()
    elif hasattr(value, "__dataclass_fields__"):
        value = asdict(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class MarketSnapshot:
    market: str
    code: str
    as_of: str
    source: str = ""
    is_final: bool = True
    freshness_seconds: int | None = None
    quality: DataQuality = DataQuality.VALUE
    payload_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["quality"] = self.quality.value
        return result


@dataclass(frozen=True)
class PositionState:
    market: str
    code: str
    strategy_id: str
    quantity: int = 0
    available_quantity: int = 0
    entry_price: float = 0.0
    entry_time: str = ""
    max_close_since_entry: float = 0.0
    realized_pnl: float = 0.0

    @property
    def is_open(self) -> bool:
        return self.quantity > 0

    def update_close(self, close: float) -> "PositionState":
        if not self.is_open or close <= 0:
            return self
        return PositionState(**{**asdict(self), "max_close_since_entry": max(self.max_close_since_entry, close)})


@dataclass(frozen=True)
class FeatureSnapshot:
    market: str
    code: str
    strategy_id: str
    as_of: str
    rank_score: float
    data_quality: DataQuality
    suspended_or_delisted: bool
    daily_direction: str
    intraday_direction: str
    intraday_available: bool
    intraday_confirmation_required: bool
    direction_conflict: bool
    momentum_weak: bool
    overall_down: bool
    low_volume: bool
    overheated: bool
    stage: str
    health_ok: bool
    index_sync: bool | None
    close_below_previous_low: bool
    trail_stop_hit: bool
    previous_low: float = 0.0
    previous_high: float = 0.0
    current_close: float = 0.0
    flow_quality: DataQuality = DataQuality.VALUE
    risk_flags: tuple[str, ...] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["data_quality"] = self.data_quality.value
        result["flow_quality"] = self.flow_quality.value
        return result

    @property
    def facts_hash(self) -> str:
        return content_hash(self.to_dict())


@dataclass(frozen=True)
class RuleHit:
    rule_id: str
    verdict: Verdict
    priority: int
    reason: str
    engine: str = "python"

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["verdict"] = self.verdict.value
        return result


@dataclass(frozen=True)
class DecisionResult:
    verdict: Verdict
    entry_eligible: bool
    rule_hits: tuple[RuleHit, ...]
    engine: str
    error: str = ""
    shadow_match: bool | None = None
    shadow_verdict: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "entry_eligible": self.entry_eligible,
            "rule_hits": [hit.to_dict() for hit in self.rule_hits],
            "engine": self.engine,
            "error": self.error,
            "shadow_match": self.shadow_match,
            "shadow_verdict": self.shadow_verdict,
        }


@dataclass(frozen=True)
class DecisionReceipt:
    run_id: str
    strategy_id: str
    strategy_version: str
    run_mode: RunMode
    signal_time: str
    earliest_execution_time: str
    market: str
    code: str
    snapshot_hash: str
    facts_hash: str
    ruleset_hash: str
    code_commit: str
    decision: DecisionResult
    semantica_version: str = ""
    provenance_id: str = ""
    audit_complete: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "run_mode": self.run_mode.value,
            "decision": self.decision.to_dict(),
        }

    @property
    def receipt_hash(self) -> str:
        return content_hash(self.to_dict())


@dataclass(frozen=True)
class OrderIntent:
    run_id: str
    market: str
    code: str
    side: str
    quantity: int
    signal_time: str
    earliest_execution_time: str
    limit_price: float | None = None
    reason: str = ""


@dataclass(frozen=True)
class Fill:
    order_id: str
    fill_time: str
    price: float
    quantity: int
    fees: float
    slippage: float


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
