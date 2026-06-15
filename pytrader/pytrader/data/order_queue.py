"""Order queue for queuing orders outside market hours."""

from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
import sqlite3
import threading

# NOTE: This file is not currently used in the SDK
# The Order model is not defined in the SDK
# If needed, this should be implemented or this file should be removed
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from typing import Any
    Order = Any
else:
    # Dummy class to prevent runtime errors if this file is accidentally imported
    class Order:
        pass
from ..utils.market_hours import PSXMarketHours


class OrderQueue:
    """
    Queue for orders submitted outside market hours.
    
    Orders are stored and executed automatically when market opens.
    """
    
    def __init__(self, db_path: str = "pytrader.db"):
        """
        Initialize order queue.
        
        Args:
            db_path: Path to SQLite database
        """
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_queue_table()
    
    def _init_queue_table(self) -> None:
        """Initialize order queue table."""
        with sqlite3.connect(self.db_path, timeout=5.0) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS order_queue (
                    order_id TEXT PRIMARY KEY,
                    order_data TEXT NOT NULL,
                    queued_at TEXT NOT NULL,
                    execute_at TEXT,
                    status TEXT DEFAULT 'queued',
                    bot_id TEXT,
                    FOREIGN KEY (order_id) REFERENCES orders(id)
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_queue_status ON order_queue(status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_queue_execute_at ON order_queue(execute_at)")
            conn.commit()
    
    def enqueue_order(self, order: Order, bot_id: Optional[str] = None) -> None:
        """
        Add order to queue.
        
        Args:
            order: Order object to queue
            bot_id: Bot identifier (optional)
        """
        import json
        
        with self._lock:
            # Calculate execute_at (next market open)
            execute_at = PSXMarketHours.get_next_market_open()
            
            # Serialize order to JSON
            order_data = {
                "id": order.id,
                "symbol": order.symbol,
                "qty": order.qty,
                "side": order.side.value,
                "order_type": order.order_type.value,
                "price": order.price,
                "time_in_force": order.time_in_force.value
            }
            
            with sqlite3.connect(self.db_path, timeout=5.0) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO order_queue
                    (order_id, order_data, queued_at, execute_at, status, bot_id)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    order.id,
                    json.dumps(order_data),
                    datetime.now(timezone.utc).isoformat(),
                    execute_at.isoformat(),
                    "queued",
                    bot_id
                ))
                conn.commit()
    
    def dequeue_orders(self, bot_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get and remove queued orders that are ready to execute.
        
        Args:
            bot_id: Filter by bot_id (optional)
            
        Returns:
            List of order dictionaries ready to execute
        """
        import json
        
        # Use market hours service for backend-integrated checks
        try:
            from ..utils.market_hours_service import get_market_hours_service
            service = get_market_hours_service()
            if not service.is_market_open():
                return []
        except Exception:
            # Fallback to direct check if service unavailable
            if not PSXMarketHours.is_market_open():
                return []
        
        with self._lock:
            current_time = datetime.now(timezone.utc).isoformat()
            
            with sqlite3.connect(self.db_path, timeout=5.0) as conn:
                cursor = conn.cursor()
                
                query = """
                    SELECT order_id, order_data, queued_at, bot_id
                    FROM order_queue
                    WHERE status = 'queued' AND execute_at <= ?
                """
                params = [current_time]
                
                if bot_id:
                    query += " AND bot_id = ?"
                    params.append(bot_id)
                
                query += " ORDER BY queued_at ASC"
                
                cursor.execute(query, params)
                rows = cursor.fetchall()
                
                orders = []
                order_ids = []
                
                for row in rows:
                    order_id, order_data_json, queued_at, bot_id_val = row
                    order_data = json.loads(order_data_json)
                    order_data["queued_at"] = queued_at
                    order_data["bot_id"] = bot_id_val
                    orders.append(order_data)
                    order_ids.append(order_id)
                
                # Mark as processing
                if order_ids:
                    placeholders = ','.join(['?' for _ in order_ids])
                    cursor.execute(f"""
                        UPDATE order_queue
                        SET status = 'processing'
                        WHERE order_id IN ({placeholders})
                    """, order_ids)
                    conn.commit()
                
                return orders
    
    def remove_queued_order(self, order_id: str) -> None:
        """
        Remove order from queue.
        
        Args:
            order_id: Order ID to remove
        """
        with self._lock:
            with sqlite3.connect(self.db_path, timeout=5.0) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    DELETE FROM order_queue
                    WHERE order_id = ?
                """, (order_id,))
                conn.commit()
    
    def mark_executed(self, order_id: str) -> None:
        """
        Mark queued order as executed.
        
        Args:
            order_id: Order ID that was executed
        """
        with self._lock:
            with sqlite3.connect(self.db_path, timeout=5.0) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE order_queue
                    SET status = 'executed'
                    WHERE order_id = ?
                """, (order_id,))
                conn.commit()
    
    def get_queued_orders(self, bot_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get all queued orders (without removing them).
        
        Args:
            bot_id: Filter by bot_id (optional)
            
        Returns:
            List of queued order dictionaries
        """
        import json
        
        with self._lock:
            with sqlite3.connect(self.db_path, timeout=5.0) as conn:
                cursor = conn.cursor()
                
                query = """
                    SELECT order_id, order_data, queued_at, execute_at, bot_id
                    FROM order_queue
                    WHERE status = 'queued'
                """
                params = []
                
                if bot_id:
                    query += " AND bot_id = ?"
                    params.append(bot_id)
                
                query += " ORDER BY execute_at ASC"
                
                cursor.execute(query, params)
                rows = cursor.fetchall()
                
                orders = []
                for row in rows:
                    order_id, order_data_json, queued_at, execute_at, bot_id_val = row
                    order_data = json.loads(order_data_json)
                    order_data["queued_at"] = queued_at
                    order_data["execute_at"] = execute_at
                    order_data["bot_id"] = bot_id_val
                    orders.append(order_data)
                
                return orders

