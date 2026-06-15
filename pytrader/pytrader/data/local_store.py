"""SQLite-based persistence for orders, positions, and account."""

import sqlite3
from typing import List, Optional, Any
from datetime import datetime, timezone

# NOTE: This file is not currently used in the SDK
# The models (Order, Position, Account) are not defined in the SDK
# If needed, these should be implemented or this file should be removed
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    # Type stubs for unused classes
    from typing import Any
    Order = Any
    Position = Any
    Account = Any
else:
    # Dummy classes to prevent runtime errors if this file is accidentally imported
    class Order:
        pass
    class Position:
        pass
    class Account:
        pass
from ..utils.enums import OrderStatus
from ..utils.currency import format_pkr


def _parse_ts(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    ts = datetime.fromisoformat(value)
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


class LocalStore:
    """
    SQLite-based persistence layer for PyTrader.
    
    Stores orders, positions, and account information in SQLite database.
    """
    
    def __init__(self, db_path: str = "pytrader.db"):
        """
        Initialize local store.
        
        Args:
            db_path: Path to SQLite database file (default: "pytrader.db")
        """
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self) -> None:
        """Initialize database tables with thread-safe connection."""
        # Use timeout for concurrent access (default 5 seconds)
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        try:
            cursor = conn.cursor()
            
            # Orders table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS orders (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    qty INTEGER NOT NULL,
                    side TEXT NOT NULL,
                    order_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    time_in_force TEXT NOT NULL,
                    price REAL,
                    filled_avg_price REAL,
                    filled_qty INTEGER,
                    commission REAL DEFAULT 0.0,
                    slippage_applied REAL DEFAULT 0.0,
                    total_cost REAL,
                    created_at TEXT NOT NULL,
                    submitted_at TEXT,
                    filled_at TEXT,
                    cancelled_at TEXT
                )
            """)
            
            # Positions table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS positions (
                    symbol TEXT PRIMARY KEY,
                    qty INTEGER NOT NULL,
                    avg_price REAL NOT NULL,
                    market_value REAL,
                    unrealized_pnl REAL,
                    unrealized_pnl_pct REAL,
                    updated_at TEXT NOT NULL
                )
            """)
            
            # Account table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS account (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    balance REAL NOT NULL,
                    equity REAL NOT NULL,
                    buying_power REAL NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            
            conn.commit()
        finally:
            conn.close()
    
    def save_order(self, order: Order) -> None:
        """
        Save order to database with thread-safe access.
        
        Args:
            order: Order object to save
        """
        with sqlite3.connect(self.db_path, timeout=5.0) as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT OR REPLACE INTO orders (
                    id, symbol, qty, side, order_type, status, time_in_force,
                    price, filled_avg_price, filled_qty, commission, slippage_applied,
                    total_cost, created_at, submitted_at, filled_at, cancelled_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                order.id,
                order.symbol,
                order.qty,
                order.side.value,
                order.order_type.value,
                order.status.value,
                order.time_in_force.value,
                order.price,
                order.filled_avg_price,
                order.filled_qty,
                order.commission,
                order.slippage_applied,
                order.total_cost,
                order.created_at.isoformat(),
                order.submitted_at.isoformat() if order.submitted_at else None,
                order.filled_at.isoformat() if order.filled_at else None,
                order.cancelled_at.isoformat() if order.cancelled_at else None
            ))
            
            conn.commit()
    
    def get_orders(
        self,
        status: Optional[OrderStatus] = None,
        symbol: Optional[str] = None
    ) -> List[Order]:
        """
        Get orders from database with thread-safe access.
        
        Args:
            status: Filter by order status (optional)
            symbol: Filter by symbol (optional)
            
        Returns:
            List of Order objects
        """
        with sqlite3.connect(self.db_path, timeout=5.0) as conn:
            cursor = conn.cursor()
            
            query = "SELECT * FROM orders WHERE 1=1"
            params = []
            
            if status:
                query += " AND status = ?"
                params.append(status.value)
            
            if symbol:
                query += " AND symbol = ?"
                params.append(symbol.upper())
            
            query += " ORDER BY created_at DESC"
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            orders = []
            for row in rows:
                order_dict = {
                    "id": row[0],
                    "symbol": row[1],
                    "qty": row[2],
                    "side": row[3],
                    "order_type": row[4],
                    "status": row[5],
                    "time_in_force": row[6],
                    "price": row[7],
                    "filled_avg_price": row[8],
                    "filled_qty": row[9],
                    "commission": row[10] or 0.0,
                    "slippage_applied": row[11] or 0.0,
                    "total_cost": row[12],
                    "created_at": _parse_ts(row[13]),
                    "submitted_at": _parse_ts(row[14]),
                    "filled_at": _parse_ts(row[15]),
                    "cancelled_at": _parse_ts(row[16]),
                }
                orders.append(Order(**order_dict))
            
            return orders
    
    def get_order_by_id(self, order_id: str) -> Optional[Order]:
        """
        Get order by ID.
        
        Args:
            order_id: Order ID
            
        Returns:
            Order object or None if not found
        """
        orders = self.get_orders()
        for order in orders:
            if order.id == order_id:
                return order
        return None
    
    def update_order_status(
        self,
        order_id: str,
        status: OrderStatus,
        filled_avg_price: Optional[float] = None,
        filled_qty: Optional[int] = None,
        filled_at: Optional[datetime] = None,
        cancelled_at: Optional[datetime] = None
    ) -> None:
        """
        Update order status and fill information with thread-safe access.
        
        Args:
            order_id: Order ID
            status: New order status
            filled_avg_price: Average fill price (if filled)
            filled_qty: Filled quantity (if filled)
            filled_at: Fill timestamp (if filled)
            cancelled_at: Cancellation timestamp (if cancelled)
        """
        with sqlite3.connect(self.db_path, timeout=5.0) as conn:
            cursor = conn.cursor()
            
            updates = [f"status = '{status.value}'"]
            
            if filled_avg_price is not None:
                updates.append(f"filled_avg_price = {filled_avg_price}")
            
            if filled_qty is not None:
                updates.append(f"filled_qty = {filled_qty}")
            
            if filled_at:
                updates.append(f"filled_at = '{filled_at.isoformat()}'")
            
            if cancelled_at:
                updates.append(f"cancelled_at = '{cancelled_at.isoformat()}'")
            
            query = f"UPDATE orders SET {', '.join(updates)} WHERE id = ?"
            cursor.execute(query, (order_id,))
            
            conn.commit()
    
    def get_positions(self) -> List[Position]:
        """
        Get all positions from database.
        
        Returns:
            List of Position objects
        """
        with sqlite3.connect(self.db_path, timeout=5.0) as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT * FROM positions")
            rows = cursor.fetchall()
            
            positions = []
            for row in rows:
                position_dict = {
                    "symbol": row[0],
                    "qty": row[1],
                    "avg_price": row[2],
                    "market_value": row[3],
                    "unrealized_pnl": row[4],
                    "unrealized_pnl_pct": row[5],
                    "updated_at": _parse_ts(row[6])
                }
                positions.append(Position(**position_dict))
            
            return positions
    
    def get_position(self, symbol: str) -> Optional[Position]:
        """
        Get position for a specific symbol.
        
        Args:
            symbol: Stock symbol
            
        Returns:
            Position object or None if not found
        """
        positions = self.get_positions()
        for position in positions:
            if position.symbol.upper() == symbol.upper():
                return position
        return None
    
    def update_position(
        self,
        symbol: str,
        qty: int,
        price: float,
        market_value: Optional[float] = None,
        unrealized_pnl: Optional[float] = None,
        unrealized_pnl_pct: Optional[float] = None
    ) -> None:
        """
        Update or create position.
        
        Args:
            symbol: Stock symbol
            qty: Quantity (positive for long, negative for short)
            price: Average entry price
            market_value: Current market value (optional)
            unrealized_pnl: Unrealized P/L (optional)
            unrealized_pnl_pct: Unrealized P/L percentage (optional)
        """
        with sqlite3.connect(self.db_path, timeout=5.0) as conn:
            cursor = conn.cursor()
            
            # Check if position exists
            cursor.execute("SELECT qty FROM positions WHERE symbol = ?", (symbol.upper(),))
            existing = cursor.fetchone()
            
            if existing:
                # Update existing position
                cursor.execute("""
                    UPDATE positions SET
                        qty = ?,
                        avg_price = ?,
                        market_value = ?,
                        unrealized_pnl = ?,
                        unrealized_pnl_pct = ?,
                        updated_at = ?
                    WHERE symbol = ?
                """, (
                    qty,
                    price,
                    market_value,
                    unrealized_pnl,
                    unrealized_pnl_pct,
                    datetime.now(timezone.utc).isoformat(),
                    symbol.upper()
                ))
            else:
                # Create new position
                cursor.execute("""
                    INSERT INTO positions (
                        symbol, qty, avg_price, market_value,
                        unrealized_pnl, unrealized_pnl_pct, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    symbol.upper(),
                    qty,
                    price,
                    market_value,
                    unrealized_pnl,
                    unrealized_pnl_pct,
                    datetime.now(timezone.utc).isoformat()
                ))
            
            conn.commit()
    
    def delete_position(self, symbol: str) -> None:
        """
        Delete position for a symbol.
        
        Args:
            symbol: Stock symbol
        """
        with sqlite3.connect(self.db_path, timeout=5.0) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM positions WHERE symbol = ?", (symbol.upper(),))
            conn.commit()
    
    def update_balance(self, balance: float) -> None:
        """
        Update account balance.
        
        Args:
            balance: New balance in PKR
        """
        account = self.get_account()
        if account:
            self.update_account(
                balance=balance,
                equity=account.equity,
                buying_power=account.buying_power
            )
        else:
            # Create initial account
            self.update_account(
                balance=balance,
                equity=balance,
                buying_power=balance
            )
    
    def update_account(
        self,
        balance: float,
        equity: float,
        buying_power: float
    ) -> None:
        """
        Update account information.
        
        Args:
            balance: Cash balance in PKR
            equity: Total equity in PKR
            buying_power: Available buying power in PKR
        """
        with sqlite3.connect(self.db_path, timeout=5.0) as conn:
            cursor = conn.cursor()
            
            # Check if account exists
            cursor.execute("SELECT id FROM account WHERE id = 1")
            existing = cursor.fetchone()
            
            if existing:
                # Update existing account
                cursor.execute("""
                    UPDATE account SET
                        balance = ?,
                        equity = ?,
                        buying_power = ?,
                        updated_at = ?
                    WHERE id = 1
                """, (
                    format_pkr(balance),
                    format_pkr(equity),
                    format_pkr(buying_power),
                    datetime.now(timezone.utc).isoformat()
                ))
            else:
                # Create new account
                cursor.execute("""
                    INSERT INTO account (
                        id, balance, equity, buying_power, updated_at
                    ) VALUES (1, ?, ?, ?, ?)
                """, (
                    format_pkr(balance),
                    format_pkr(equity),
                    format_pkr(buying_power),
                    datetime.now(timezone.utc).isoformat()
                ))
            
            conn.commit()
    
    def get_account(self) -> Optional[Account]:
        """
        Get account information.
        
        Returns:
            Account object or None if not found
        """
        with sqlite3.connect(self.db_path, timeout=5.0) as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT * FROM account WHERE id = 1")
            row = cursor.fetchone()
            
            if row:
                return Account(
                    balance=row[1],
                    equity=row[2],
                    buying_power=row[3],
                    updated_at=_parse_ts(row[4])
                )
            
            return None
    
    def clear_all(self) -> None:
        """
        Clear all data from database (for backtesting reset).
        
        WARNING: This deletes all orders, positions, and resets account balance.
        Use with caution!
        """
        with sqlite3.connect(self.db_path, timeout=5.0) as conn:
            cursor = conn.cursor()
            
            # Delete all orders
            cursor.execute("DELETE FROM orders")
            
            # Delete all positions
            cursor.execute("DELETE FROM positions")
            
            # Note: We keep the account table but will reset it in update_account
            conn.commit()

