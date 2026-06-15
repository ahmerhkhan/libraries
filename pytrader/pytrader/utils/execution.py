"""Market order execution simulation with slippage and fees."""

import random
from typing import Dict, Any

from .currency import format_pkr, format_price


def calculate_execution_price(
    base_price: float,
    side: str,
    slippage_pct: float = 0.001,
    spread_pct: float = 0.001
) -> float:
    """
    Calculate execution price with slippage and spread.
    
    Args:
        base_price: Base price from quote
        side: "buy" or "sell"
        slippage_pct: Percentage slippage (default 0.1% = 0.001)
        spread_pct: Percentage spread (default 0.1% = 0.001)
        
    Returns:
        Execution price adjusted for slippage and spread
    """
    total_adjustment = slippage_pct + spread_pct
    
    if side.lower() == "buy":
        # BUY: Pay slightly more (above ask)
        exec_price = base_price * (1 + total_adjustment)
    elif side.lower() == "sell":
        # SELL: Receive slightly less (below bid)
        exec_price = base_price * (1 - total_adjustment)
    else:
        raise ValueError(f"Invalid side: {side}. Must be 'buy' or 'sell'")
    
    return format_price(exec_price)


def simulate_execution_delay(min_ms: int = 100, max_ms: int = 500) -> float:
    """
    Simulate execution delay for realistic order processing.
    
    Args:
        min_ms: Minimum delay in milliseconds (default 100)
        max_ms: Maximum delay in milliseconds (default 500)
        
    Returns:
        Delay in seconds (float)
    """
    delay_ms = random.randint(min_ms, max_ms)
    return delay_ms / 1000.0


def calculate_commission(order_value: float, commission_per_trade: float = 0.0) -> float:
    """
    Calculate commission fee for an order.
    
    Args:
        order_value: Total value of the order (price * quantity)
        commission_per_trade: Flat fee per order in PKR (default 0.0)
        
    Returns:
        Commission fee in PKR, formatted to 2 decimal places
    """
    return format_pkr(commission_per_trade)


def execute_market_order(
    quote: Dict[str, Any],
    side: str,
    qty: int,
    slippage_pct: float = 0.001,
    commission_per_trade: float = 0.0,
    execution_delay_ms: tuple = (100, 500)
) -> Dict[str, Any]:
    """
    Complete market order execution simulation with price, delay, slippage, and commission.
    
    Args:
        quote: Quote dictionary with 'last_price', 'bid', 'ask', etc.
        side: "buy" or "sell"
        qty: Order quantity
        slippage_pct: Percentage slippage (default 0.1% = 0.001)
        commission_per_trade: Flat fee per order in PKR (default 0.0)
        execution_delay_ms: Tuple of (min, max) milliseconds for execution delay
        
    Returns:
        Dictionary with execution details:
        {
            "execution_price": float,
            "slippage_applied": float,
            "commission": float,
            "total_cost": float,
            "execution_delay": float
        }
    """
    # Get base price from quote (prefer bid/ask, fallback to last_price)
    if side.lower() == "buy":
        base_price = quote.get("ask") or quote.get("last_price")
    else:  # sell
        base_price = quote.get("bid") or quote.get("last_price")
    
    if base_price is None:
        raise ValueError("Quote must contain 'last_price', 'bid', or 'ask'")
    
    # Calculate execution price with slippage
    execution_price = calculate_execution_price(base_price, side, slippage_pct)
    
    # Calculate order value
    order_value = execution_price * qty
    
    # Calculate commission
    commission = calculate_commission(order_value, commission_per_trade)
    
    # Calculate total cost
    if side.lower() == "buy":
        total_cost = order_value + commission
    else:  # sell
        total_cost = order_value - commission
    
    # Simulate execution delay
    execution_delay = simulate_execution_delay(
        execution_delay_ms[0],
        execution_delay_ms[1]
    )
    
    return {
        "execution_price": execution_price,
        "slippage_applied": slippage_pct,
        "commission": commission,
        "total_cost": format_pkr(total_cost),
        "execution_delay": execution_delay,
        "base_price": base_price,
        "order_value": format_pkr(order_value)
    }

