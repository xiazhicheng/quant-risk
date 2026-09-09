"""Deterministic paper/backtest execution primitives for CN/HK equities."""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from .strategy_models import DecisionReceipt, Fill, OrderIntent, PositionState, RunMode, Verdict


@dataclass(frozen=True)
class CostConfig:
    commission_rate: float = 0.0003
    minimum_commission: float = 5.0
    stamp_duty_sell_rate: float = 0.0005
    trading_levy_rate: float = 0.0
    transaction_fee_rate: float = 0.0
    slippage_bps: float = 8.0


@dataclass(frozen=True)
class PortfolioLimits:
    max_total_exposure: float = 0.80
    min_cash_ratio: float = 0.20
    max_stock_exposure: float = 0.15
    max_sector_exposure: float = 0.30
    max_market_exposure: float = 0.60


class ExecutionGuard:
    """Validate live orders; all research/paper calls fail closed."""

    def __init__(self, limits: PortfolioLimits | None = None):
        self.limits = limits or PortfolioLimits()

    def validate(self, receipt: DecisionReceipt, order: OrderIntent,
                 portfolio: dict[str, Any] | None = None) -> tuple[bool, str]:
        if receipt.run_mode != RunMode.LIVE:
            return False, f"运行模式={receipt.run_mode.value}，仅live允许真实订单"
        if not receipt.audit_complete or not receipt.provenance_id:
            return False, "缺少完整审计凭证或provenance_id，fail-closed禁止下单"
        if receipt.decision.verdict != Verdict.ALLOW or not receipt.decision.entry_eligible:
            return False, f"规则裁决={receipt.decision.verdict.value}，禁止下单"
        if order.quantity <= 0:
            return False, "订单数量必须为正"
        portfolio = portfolio or {}
        if float(portfolio.get("total_exposure", 0)) > self.limits.max_total_exposure:
            return False, "组合总仓位已达上限"
        if float(portfolio.get("stock_exposure", 0)) > self.limits.max_stock_exposure:
            return False, "单股仓位已达上限"
        if float(portfolio.get("sector_exposure", 0)) > self.limits.max_sector_exposure:
            return False, "板块仓位已达上限"
        if float(portfolio.get("market_exposure", 0)) > self.limits.max_market_exposure:
            return False, "市场仓位已达上限"
        if receipt.market == "cn" and order.quantity % 100 != 0:
            return False, "A股订单数量必须为100股整数倍"
        return True, "订单通过执行门禁"


@dataclass(frozen=True)
class ExecutionResult:
    accepted: bool
    reason: str
    fill: Fill | None = None
    position: PositionState | None = None


class MarketExecutionModel:
    def __init__(self, market: str, costs: CostConfig | None = None, lot_size: int | None = None):
        self.market = market.lower()
        self.costs = costs or CostConfig()
        self.lot_size = lot_size or (100 if self.market == "cn" else 1)

    def normalize_quantity(self, quantity: int) -> int:
        return max(0, (int(quantity) // self.lot_size) * self.lot_size)

    def can_fill(self, order: OrderIntent, bar: dict[str, Any], position: PositionState | None = None) -> tuple[bool, str]:
        if not bar or float(bar.get("close") or 0) <= 0:
            return False, "成交价数据缺失"
        if float(bar.get("volume") or 0) <= 0:
            return False, "当日无成交或停牌"
        quantity = self.normalize_quantity(order.quantity)
        if quantity <= 0:
            return False, f"数量不足一个交易单位（{self.lot_size}）"
        if order.side.upper() == "SELL" and self.market == "cn":
            available = position.available_quantity if position else 0
            if quantity > available:
                return False, "A股T+1：可卖数量不足"
        if self.market == "cn":
            high_limit = float(bar.get("high_limit") or 0)
            low_limit = float(bar.get("low_limit") or 0)
            px = float(order.limit_price or bar.get("open") or bar.get("close") or 0)
            if high_limit > 0 and px >= high_limit:
                return False, "触及涨停，买单不可成交"
            if low_limit > 0 and px <= low_limit:
                return False, "触及跌停，卖单不可成交"
        return True, "可成交"

    def execute(self, order: OrderIntent, bar: dict[str, Any], position: PositionState | None = None) -> ExecutionResult:
        ok, reason = self.can_fill(order, bar, position)
        if not ok:
            return ExecutionResult(False, reason, position=position)
        quantity = self.normalize_quantity(order.quantity)
        raw_price = float(order.limit_price or bar.get("open") or bar.get("close"))
        slip = raw_price * self.costs.slippage_bps / 10000
        price = raw_price + slip if order.side.upper() == "BUY" else raw_price - slip
        notional = price * quantity
        commission = max(notional * self.costs.commission_rate, self.costs.minimum_commission)
        if order.side.upper() == "SELL":
            commission += notional * self.costs.stamp_duty_sell_rate
        if self.market == "hk":
            commission += notional * (self.costs.trading_levy_rate + self.costs.transaction_fee_rate)
        fill = Fill(order_id=f"paper-{order.run_id}-{order.code}", fill_time=order.earliest_execution_time,
                    price=round(price, 6), quantity=quantity, fees=round(commission, 6), slippage=round(slip * quantity, 6))
        return ExecutionResult(True, "成交", fill=fill, position=position)


def update_position(position: PositionState | None, order: OrderIntent, fill: Fill, strategy_id: str) -> PositionState:
    """Apply a fill to immutable position state; A股 availability is conservative T+1."""
    if position is None:
        position = PositionState(order.market, order.code, strategy_id)
    if order.side.upper() == "BUY":
        total_qty = position.quantity + fill.quantity
        avg = ((position.entry_price * position.quantity) + (fill.price * fill.quantity)) / total_qty if total_qty else 0
        available = position.available_quantity if order.market != "cn" else position.available_quantity
        return replace(position, quantity=total_qty, available_quantity=available,
                       entry_price=avg, entry_time=fill.fill_time,
                       max_close_since_entry=max(position.max_close_since_entry, fill.price))
    remaining = max(0, position.quantity - fill.quantity)
    return replace(position, quantity=remaining, available_quantity=max(0, position.available_quantity - fill.quantity),
                   realized_pnl=position.realized_pnl + (fill.price - position.entry_price) * fill.quantity - fill.fees)


__all__ = ["CostConfig", "PortfolioLimits", "ExecutionGuard", "ExecutionResult", "MarketExecutionModel", "update_position"]
