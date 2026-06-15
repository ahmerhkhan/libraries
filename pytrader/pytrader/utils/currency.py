"""PKR currency formatting utilities."""


def format_pkr(amount: float) -> float:
    """
    Format amount in PKR to 2 decimal places.
    
    Args:
        amount: The amount to format
        
    Returns:
        Amount rounded to 2 decimal places
    """
    return round(amount, 2)


def format_balance(balance: float) -> float:
    """
    Format account balance in PKR to 2 decimal places.
    
    Args:
        balance: The balance to format
        
    Returns:
        Balance rounded to 2 decimal places
    """
    return format_pkr(balance)


def format_price(price: float) -> float:
    """
    Format stock price in PKR to 2 decimal places.
    
    Args:
        price: The price to format
        
    Returns:
        Price rounded to 2 decimal places
    """
    return format_pkr(price)

