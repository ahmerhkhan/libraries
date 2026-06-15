"""
Synthetic bid/ask for paper trading when the upstream venue has no order book.

Spread: ±0.05% around last/mid (0.1% total). BUY fills at ask, SELL at bid;
mark-to-market for longs uses bid (liquidation).
"""

from __future__ import annotations

from typing import Any, Dict, Tuple


def synthetic_bid_ask_from_last(last: float) -> Tuple[float, float]:
    x = float(last)
    if x <= 0 or x != x:
        return 0.0, 0.0
    bid = round(x * 0.9995, 2)
    ask = round(x * 1.0005, 2)
    return bid, ask


def ensure_bid_ask_on_quote(quote: Dict[str, Any]) -> Dict[str, Any]:
    """Mutate a get_price()-style dict so bid/ask are always set when price > 0."""
    if not isinstance(quote, dict):
        return quote
    mid = float(quote.get("price") or 0.0)
    if mid <= 0:
        return quote
    bid = float(quote.get("bid") or 0.0)
    ask = float(quote.get("ask") or 0.0)
    if bid <= 0 or ask <= 0:
        bid, ask = synthetic_bid_ask_from_last(mid)
        quote["bid"] = bid
        quote["ask"] = ask
    return quote


def mark_execution_price(quote: Dict[str, Any], side: str) -> float:
    """
    Executable price for MARKET-style orders: ask for BUY, bid for SELL.
    Falls back to mid when quote is incomplete.
    """
    side_u = str(side or "").upper()
    ensure_bid_ask_on_quote(quote)
    mid = float(quote.get("price") or 0.0)
    bid = float(quote.get("bid") or 0.0)
    ask = float(quote.get("ask") or 0.0)
    if side_u == "BUY":
        if ask > 0:
            return ask
        if mid > 0:
            return synthetic_bid_ask_from_last(mid)[1]
        return 0.0
    if bid > 0:
        return bid
    if mid > 0:
        return synthetic_bid_ask_from_last(mid)[0]
    return 0.0


def mark_to_market_price(quote: Dict[str, Any], *, qty: float) -> float:
    """
    Position valuation: longs at bid (sale proceeds), shorts at ask (cover cost).
    """
    ensure_bid_ask_on_quote(quote)
    mid = float(quote.get("price") or 0.0)
    bid = float(quote.get("bid") or 0.0)
    ask = float(quote.get("ask") or 0.0)
    if qty < 0:
        if ask > 0:
            return ask
        if mid > 0:
            return synthetic_bid_ask_from_last(mid)[1]
        return 0.0
    if bid > 0:
        return bid
    if mid > 0:
        return synthetic_bid_ask_from_last(mid)[0]
    return 0.0
