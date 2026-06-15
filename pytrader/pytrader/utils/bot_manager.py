"""Bot instance manager with limits and tracking."""

from typing import Dict, List, Optional
from datetime import datetime, timezone
import threading
import sqlite3

from .exceptions import PyTraderError


class BotLimitExceededError(PyTraderError):
    """Raised when user exceeds bot limit."""
    pass


class BotManager:
    """
    Manages bot instances with limits and tracking.
    
    Supports:
    - Tracking active bot instances per user
    - Enforcing free tier limits (4 bots max)
    - Premium user support
    - Safe concurrent access
    """
    
    # Free tier limit
    FREE_TIER_BOT_LIMIT = 4
    
    def __init__(self, db_path: str = "pytrader.db", user_id: str = "default_user"):
        """
        Initialize bot manager.
        
        Args:
            db_path: Path to SQLite database
            user_id: User identifier (default: "default_user")
        """
        self.db_path = db_path
        self.user_id = user_id
        self._lock = threading.Lock()
        self._active_bots: Dict[str, datetime] = {}  # bot_id -> created_at
        
        self._init_bot_tracking_table()
    
    def _init_bot_tracking_table(self) -> None:
        """Initialize bot tracking table in database."""
        # Add timeout for thread-safe concurrent access (fixes hanging issue)
        with sqlite3.connect(self.db_path, timeout=5.0) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS bot_instances (
                    bot_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    is_active INTEGER DEFAULT 1,
                    store_path TEXT,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    is_premium INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL
                )
            """)
            conn.commit()
    
    def register_bot(
        self,
        bot_id: str,
        store_path: Optional[str] = None,
        is_premium: bool = False
    ) -> None:
        """
        Register a new bot instance.
        
        Args:
            bot_id: Unique bot identifier
            store_path: Path to bot's store (optional)
            is_premium: Whether user is premium (default: False)
            
        Raises:
            BotLimitExceededError: If free tier limit exceeded
        """
        with self._lock:
            # Check if user exists, create if not
            self._ensure_user_exists(is_premium)
            
            # Check bot limit
            active_count = self.get_active_bot_count()
            if not is_premium and active_count >= self.FREE_TIER_BOT_LIMIT:
                raise BotLimitExceededError(
                    f"Free tier limit of {self.FREE_TIER_BOT_LIMIT} bots exceeded. "
                    f"Current active bots: {active_count}. "
                    "Note: For open source SDK, this is a local limit. "
                    "To disable limits, set is_premium=True in TradingConfig or use "
                    "BotManager.set_premium(True). For production, implement backend validation."
                )
            
            # Register bot in database
            with sqlite3.connect(self.db_path, timeout=5.0) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO bot_instances
                    (bot_id, user_id, created_at, is_active, store_path)
                    VALUES (?, ?, ?, 1, ?)
                """, (
                    bot_id,
                    self.user_id,
                    datetime.now(timezone.utc).isoformat(),
                    store_path
                ))
                conn.commit()
            
            # Add to in-memory tracking
            self._active_bots[bot_id] = datetime.now(timezone.utc)
    
    def unregister_bot(self, bot_id: str) -> None:
        """
        Unregister a bot instance.
        
        Args:
            bot_id: Bot identifier to unregister
        """
        with self._lock:
            # Mark as inactive in database
            with sqlite3.connect(self.db_path, timeout=5.0) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE bot_instances
                    SET is_active = 0
                    WHERE bot_id = ? AND user_id = ?
                """, (bot_id, self.user_id))
                conn.commit()
            
            # Remove from in-memory tracking
            if bot_id in self._active_bots:
                del self._active_bots[bot_id]
    
    def get_active_bot_count(self) -> int:
        """
        Get count of active bot instances for current user.
        
        Returns:
            Number of active bots
        """
        with self._lock:
            with sqlite3.connect(self.db_path, timeout=5.0) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT COUNT(*) FROM bot_instances
                    WHERE user_id = ? AND is_active = 1
                """, (self.user_id,))
                count = cursor.fetchone()[0]
                return count
    
    def get_active_bots(self) -> List[str]:
        """
        Get list of active bot IDs for current user.
        
        Returns:
            List of bot IDs
        """
        with self._lock:
            with sqlite3.connect(self.db_path, timeout=5.0) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT bot_id FROM bot_instances
                    WHERE user_id = ? AND is_active = 1
                    ORDER BY created_at DESC
                """, (self.user_id,))
                return [row[0] for row in cursor.fetchall()]
    
    def is_premium(self) -> bool:
        """
        Check if current user is premium.
        
        Returns:
            True if premium, False otherwise
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT is_premium FROM users
                WHERE user_id = ?
            """, (self.user_id,))
            row = cursor.fetchone()
            return row[0] == 1 if row else False
    
    def set_premium(self, is_premium: bool = True) -> None:
        """
        Set premium status for current user.
        
        **Note**: This is for local tracking only. Since the SDK is open source,
        users can modify this locally. For production use with monetization,
        premium status should be validated server-side via API authentication.
        
        Args:
            is_premium: Premium status (default: True)
        """
        with self._lock:
            self._ensure_user_exists(is_premium)
            
            with sqlite3.connect(self.db_path, timeout=5.0) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE users
                    SET is_premium = ?
                    WHERE user_id = ?
                """, (1 if is_premium else 0, self.user_id))
                conn.commit()
    
    def _ensure_user_exists(self, is_premium: bool = False) -> None:
        """Ensure user record exists in database."""
        with sqlite3.connect(self.db_path, timeout=5.0) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR IGNORE INTO users
                (user_id, is_premium, created_at)
                VALUES (?, ?, ?)
            """, (
                self.user_id,
                1 if is_premium else 0,
                datetime.now(timezone.utc).isoformat()
            ))
            conn.commit()


# Global bot manager instance (singleton per user)
_global_bot_manager: Optional[BotManager] = None


def get_bot_manager(user_id: str = "default_user", db_path: str = "pytrader.db") -> BotManager:
    """
    Get or create global bot manager instance.
    
    Args:
        user_id: User identifier
        db_path: Database path
        
    Returns:
        BotManager instance
    """
    global _global_bot_manager
    if _global_bot_manager is None or _global_bot_manager.user_id != user_id:
        _global_bot_manager = BotManager(db_path=db_path, user_id=user_id)
    return _global_bot_manager

