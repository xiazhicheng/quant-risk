"""Point-in-time replay helpers shared by paper and backtest modes."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .execution import CostConfig, MarketExecutionModel
from .strategy_models import OrderIntent, PositionState


@dataclass(frozen=True)
class TradeEvent:
    date: str
    side: str
    price: float
    quantity: int
    fees: float
    slippage: float
    reason: str


@dataclass(frozen=True)
class ReplayResult:
    events: tuple[TradeEvent, ...]
    position: PositionState | None
    cash: float
    equity_curve: tuple[float, ...]
    rejected_orders: int


def _max_drawdown(curve: Iterable[float]) -> float:
    peak = None
    worst = 0.0
    for value in curve:
        value = float(value)
        peak = value if peak is None else max(peak, value)
        if peak:
            worst = min(worst, (value - peak) / peak)
    return round(abs(worst) * 100, 4)


def performance_metrics(equity_curve: Iterable[float], trades: Iterable[TradeEvent]) -> dict[str, float]:
    curve = [float(value) for value in equity_curve]
    events = list(trades)
    if not curve:
        return {"net_return_pct": 0.0, "max_drawdown_pct": 0.0, "profit_factor": 0.0, "win_rate_pct": 0.0}
    start, end = curve[0], curve[-1]
    pnl = [event.price * event.quantity * (1 if event.side == "SELL" else -1) - event.fees for event in events]
    gross_profit = sum(max(value, 0.0) for value in pnl)
    gross_loss = abs(sum(min(value, 0.0) for value in pnl))
    wins = sum(value > 0 for value in pnl)
    return {
        "net_return_pct": round((end - start) / start * 100, 4) if start else 0.0,
        "max_drawdown_pct": _max_drawdown(curve),
        "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss else (float("inf") if gross_profit else 0.0),
        "win_rate_pct": round(wins / len(pnl) * 100, 4) if pnl else 0.0,
        "trade_count": float(len(events)),
    }


def replay_orders(
    market: str,
    bars: list[dict[str, Any]],
    orders: list[OrderIntent],
    starting_cash: float = 100000.0,
    costs: CostConfig | None = None,
    strategy_id: str = "swing_tactical_1w2w",
) -> ReplayResult:
    """Replay orders at the first bar on/after earliest_execution_time.

    This is intentionally broker-free and deterministic. Orders that cannot fill
    are counted as rejects, never silently treated as fills.
    """
    model = MarketExecutionModel(market, costs)
    position: PositionState | None = None
    cash = float(starting_cash)
    events: list[TradeEvent] = []
    rejected = 0
    curve: list[float] = [cash]
    last_trade_date = ""
    for order in sorted(orders, key=lambda item: (item.earliest_execution_time, item.code, item.side)):
        bar = next((bar for bar in bars if str(bar.get("date", "")) >= order.earliest_execution_time), None)
        bar_date = str(bar.get("date", ""))[:10] if bar else ""
        if position and market.lower() == "cn" and bar_date and bar_date != last_trade_date:
            position = __import__("dataclasses", fromlist=["replace"]).replace(
                position, available_quantity=position.quantity
            )
        last_trade_date = bar_date or last_trade_date
        if not bar:
            rejected += 1
            continue
        result = model.execute(order, bar, position)
        if not result.accepted or result.fill is None:
            rejected += 1
            continue
        fill = result.fill
        notional = fill.price * fill.quantity
        if order.side.upper() == "BUY":
            total = notional + fill.fees
            if total > cash:
                rejected += 1
                continue
            cash -= total
        else:
            cash += notional - fill.fees
        position = __import__("scripts.quantrisk.execution", fromlist=["update_position"]).update_position(
            position, order, fill, strategy_id
        )
        events.append(TradeEvent(str(bar.get("date", "")), order.side.upper(), fill.price,
                                 fill.quantity, fill.fees, fill.slippage, order.reason))
        mark = cash + ((position.quantity * float(bar.get("close") or fill.price)) if position else 0.0)
        curve.append(mark)
    return ReplayResult(tuple(events), position, round(cash, 6), tuple(curve), rejected)


__all__ = ["TradeEvent", "ReplayResult", "performance_metrics", "replay_orders"]


@dataclass(frozen=True)
class ClosedTrade:
    """A completed buy->sell round trip; holding days derived from actual dates."""
    entry_date: str
    exit_date: str
    holding_days: int
    entry_price: float
    exit_price: float
    quantity: int
    fees: float
    return_pct: float
    exit_reason: str


def _holding_days(entry_date: str, exit_date: str) -> int:
    from datetime import date
    try:
        a = date.fromisoformat(str(entry_date)[:10])
        b = date.fromisoformat(str(exit_date)[:10])
        return max(1, (b - a).days)
    except Exception:
        return 1


def holding_period_stats(trades: Iterable[ClosedTrade]) -> dict[str, dict[str, float]]:
    """Group completed trades by actual holding days: <5 / 5-20 / 20-60 / >60."""
    groups = {"<5天": [], "5-20天": [], "20-60天": [], ">60天": []}
    for trade in trades:
        if trade.holding_days < 5:
            groups["<5天"].append(trade)
        elif trade.holding_days <= 20:
            groups["5-20天"].append(trade)
        elif trade.holding_days <= 60:
            groups["20-60天"].append(trade)
        else:
            groups[">60天"].append(trade)
    out: dict[str, dict[str, float]] = {}
    for label, items in groups.items():
        if not items:
            out[label] = {"count": 0.0, "win_rate_pct": 0.0, "avg_return_pct": 0.0, "total_return_pct": 0.0}
            continue
        wins = sum(t.return_pct > 0 for t in items)
        out[label] = {
            "count": float(len(items)),
            "win_rate_pct": round(wins / len(items) * 100, 2),
            "avg_return_pct": round(sum(t.return_pct for t in items) / len(items), 3),
            "total_return_pct": round(sum(t.return_pct for t in items), 3),
        }
    return out




@dataclass(frozen=True)
class ClosedTrade:
    """Completed buy->sell round trip; holding days derived from actual dates."""
    entry_date: str
    exit_date: str
    holding_days: int
    entry_price: float
    exit_price: float
    quantity: int
    fees: float
    return_pct: float
    exit_reason: str


def _holding_days(entry_date: str, exit_date: str) -> int:
    from datetime import date
    try:
        a = date.fromisoformat(str(entry_date)[:10])
        b = date.fromisoformat(str(exit_date)[:10])
        return max(1, (b - a).days)
    except Exception:
        return 1


def holding_period_stats(trades: Iterable[ClosedTrade]) -> dict[str, dict[str, float]]:
    """Group completed trades by actual holding days: <5 / 5-20 / 20-60 / >60."""
    groups = {"<5天": [], "5-20天": [], "20-60天": [], ">60天": []}
    for trade in trades:
        if trade.holding_days < 5:
            groups["<5天"].append(trade)
        elif trade.holding_days <= 20:
            groups["5-20天"].append(trade)
        elif trade.holding_days <= 60:
            groups["20-60天"].append(trade)
        else:
            groups[">60天"].append(trade)
    out: dict[str, dict[str, float]] = {}
    for label, items in groups.items():
        if not items:
            out[label] = {"count": 0.0, "win_rate_pct": 0.0, "avg_return_pct": 0.0, "total_return_pct": 0.0}
            continue
        wins = sum(t.return_pct > 0 for t in items)
        out[label] = {
            "count": float(len(items)),
            "win_rate_pct": round(wins / len(items) * 100, 2),
            "avg_return_pct": round(sum(t.return_pct for t in items) / len(items), 3),
            "total_return_pct": round(sum(t.return_pct for t in items), 3),
        }
    return out


def run_swing_replay(
    daily_bars: list[dict[str, Any]],
    market: str,
    strategy_config,
    rule_engine,
    starting_cash: float = 100000.0,
    costs: CostConfig | None = None,
    lot_size: int | None = None,
    assume_data_complete: bool = True,
) -> dict[str, Any]:
    """Event-driven swing replay with holding-days distribution.

    Entry: close satisfies ALLOW (Dow direction up + healthy + index synced) ->
    buy at next bar's open. Exit: close <= previous_low (Dow third signal) or
    close <= trailing stop from entry peak -> sell at next bar's open.
    Holding days come from actual dates, not a preset horizon.

    ``daily_bars`` must carry feature columns used by the entry rule:
    dow_direction / previous_low / previous_high / stage / health_ok / index_sync
    (caller precomputes these from the same Feature Engine so replay shares
    the production rule semantics).

    assume_data_complete=True skips fund-flow/index MISSING checks so history
    can be replayed; the result marks this simplification.
    """
    model = MarketExecutionModel(market, costs, lot_size)
    position: PositionState | None = None
    cash = float(starting_cash)
    trades: list[ClosedTrade] = []
    pending_buy = False
    pending_sell = False
    pending_sell_reason = ""
    curve: list[float] = [cash]
    trail_multiple = float(strategy_config.get("atr_trail_multiple", 2.0))
    trail_min = float(strategy_config.get("trail_pct_min", 5.0))
    trail_max = float(strategy_config.get("trail_pct_max", 11.0))

    bars = sorted(daily_bars, key=lambda b: str(b.get("date", "")))
    for bar in bars:
        date_str = str(bar.get("date", ""))[:10]
        close = float(bar.get("close") or 0)
        if close <= 0:
            continue
        # Execute pending orders at this bar's open (earliest next tradable bar)
        if pending_buy and position is None:
            result = model.execute(OrderIntent("replay", market, "T", "BUY", model.lot_size,
                                               date_str, date_str), bar, None)
            pending_buy = False
            if result.accepted and result.fill is not None:
                cash -= result.fill.price * result.fill.quantity + result.fill.fees
                position = PositionState(market, "T", strategy_config.strategy_id,
                                         quantity=result.fill.quantity,
                                         available_quantity=result.fill.quantity,
                                         entry_price=result.fill.price,
                                         entry_time=date_str,
                                         max_close_since_entry=result.fill.price)
        if pending_sell and position is not None:
            result = model.execute(OrderIntent("replay", market, "T", "SELL", position.quantity,
                                               date_str, date_str), bar, position)
            pending_sell = False
            if result.accepted and result.fill is not None:
                fill = result.fill
                cash += fill.price * fill.quantity - fill.fees
                cost_basis = position.entry_price * position.quantity
                return_pct = (fill.price - position.entry_price) / position.entry_price * 100 - fill.fees / cost_basis * 100 if cost_basis else 0.0
                trades.append(ClosedTrade(position.entry_time, date_str,
                                          _holding_days(position.entry_time, date_str),
                                          position.entry_price, fill.price, fill.quantity,
                                          fill.fees, round(return_pct, 4), pending_sell_reason))
                position = None
        if position is not None:
            position = position.update_close(close)
            # Exit checks (close-confirmed, executed next bar)
            exit_signal = ""
            previous_low = float(bar.get("previous_low") or 0)
            if previous_low > 0 and close <= previous_low:
                exit_signal = "跌破前低"
            else:
                atr_approx = max((float(bar.get("high") or close) - float(bar.get("low") or close)), 1e-9)
                trail_pct = max(trail_min, min(trail_max, trail_multiple * atr_approx / position.max_close_since_entry * 100))
                trailing = position.max_close_since_entry * (1 - trail_pct / 100)
                if close <= trailing:
                    exit_signal = "移动止盈"
            if exit_signal:
                pending_sell = True
                pending_sell_reason = exit_signal
        else:
            from .strategy_models import DataQuality, FeatureSnapshot
            features = FeatureSnapshot(
                market=market, code="T", strategy_id=strategy_config.strategy_id,
                as_of=date_str, rank_score=0.0,
                data_quality=DataQuality.VALUE if assume_data_complete else DataQuality.MISSING,
                suspended_or_delisted=False,
                daily_direction=str(bar.get("dow_direction") or "up"),
                intraday_direction="", intraday_available=False,
                intraday_confirmation_required=False, direction_conflict=False,
                momentum_weak=False, overall_down=False, low_volume=False,
                overheated=False, stage=str(bar.get("stage") or "公众参与"),
                health_ok=bool(bar.get("health_ok", True)),
                index_sync=True if assume_data_complete else bar.get("index_sync"),
                close_below_previous_low=False, trail_stop_hit=False,
                previous_low=float(bar.get("previous_low") or 0),
                previous_high=float(bar.get("previous_high") or 0),
                current_close=close,
                flow_quality=DataQuality.VALUE if assume_data_complete else DataQuality.MISSING,
            )
            if rule_engine.evaluate(features).verdict.value == "ALLOW":
                pending_buy = True
        mark = cash + ((position.quantity * close) if position else 0.0)
        curve.append(mark)
    return {
        "trades": trades,
        "holding_stats": holding_period_stats(trades),
        "equity_curve": curve,
        "final_cash": round(cash, 2),
        "open_position": position,
        "assume_data_complete": assume_data_complete,
    }


__all__ = ["TradeEvent", "ReplayResult", "ClosedTrade", "performance_metrics", "holding_period_stats",
           "replay_orders", "run_swing_replay"]
