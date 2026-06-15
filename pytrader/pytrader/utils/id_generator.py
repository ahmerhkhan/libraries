"""Unique order ID generation."""

import uuid
from datetime import datetime, timezone


def generate_order_id() -> str:
    """
    Generate unique order ID.
    
    Returns:
        Unique order ID string (UUID-based)
    """
    return str(uuid.uuid4())


def generate_order_id_with_timestamp() -> str:
    """
    Generate unique order ID with timestamp prefix.
    
    Returns:
        Unique order ID string with timestamp prefix
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    unique_id = str(uuid.uuid4())[:8]
    return f"{timestamp}-{unique_id}"

