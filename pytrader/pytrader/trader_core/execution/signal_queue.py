"""
Persistent signal queue for storing buy/sell signals generated during off-hours.

Signals are stored in SQLite and automatically executed when market opens,
even if the bot process restarts.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from ...utils.market_hours import PSXMarketHours
from ...utils.logger import log_line


class SignalQueue:
    """
    Persistent queue for trading signals generated during off-hours.
    
    Signals are stored in SQLite and can be executed when market opens,
    even if the bot process restarts.
    """
    
    def __init__(self, db_path: Optional[Path] = None, bot_id: str = "default", user_id: str = "default"):
        """
        Initialize signal queue.
        
        Args:
            db_path: Path to SQLite database (default: user_data/signals/{user_id}_{bot_id}.db)
            bot_id: Bot identifier
            user_id: User identifier
        """
        self.bot_id = bot_id
        self.user_id = user_id
        
        if db_path is None:
            data_dir = Path("user_data/signals")
            data_dir.mkdir(parents=True, exist_ok=True)
            db_path = data_dir / f"{user_id}_{bot_id}_signals.db"
        
        self.db_path = Path(db_path)
        self._lock = threading.Lock()
        self._init_queue_table()
    
    def _init_queue_table(self) -> None:
        """Initialize signal queue table."""
        with sqlite3.connect(str(self.db_path), timeout=5.0) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS signal_queue (
                    signal_id TEXT PRIMARY KEY,
                    bot_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT,
                    strategy_signal TEXT NOT NULL,
                    bias TEXT NOT NULL,
                    generated_at TEXT NOT NULL,
                    signal_price REAL NOT NULL,
                    vwap REAL NOT NULL,
                    target_qty INTEGER NOT NULL,
                    note TEXT DEFAULT '',
                    delta_pct REAL DEFAULT 0.0,
                    batch_label TEXT,
                    status TEXT DEFAULT 'queued',
                    executed_at TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(signal_id)
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_signal_status ON signal_queue(status, bot_id, user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_signal_generated ON signal_queue(generated_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_signal_bot_user ON signal_queue(bot_id, user_id, status)")
            conn.commit()
    
    def enqueue_signal(
        self,
        symbol: str,
        side: Optional[str],
        strategy_signal: str,
        bias: str,
        generated_at: datetime,
        signal_price: float,
        vwap: float,
        target_qty: int,
        note: str = "",
        delta_pct: float = 0.0,
        batch_label: Optional[str] = None,
    ) -> str:
        """
        Add signal to queue.
        
        Args:
            symbol: Stock symbol
            side: BUY, SELL, or None
            strategy_signal: Strategy signal (BUY/SELL/HOLD)
            bias: Bias (BUY/SELL/NEUTRAL)
            generated_at: When signal was generated
            signal_price: Price at signal generation
            vwap: Volume-weighted average price
            target_qty: Target quantity
            note: Optional note
            delta_pct: Price change percentage
            batch_label: Optional batch label
            
        Returns:
            Signal ID
        """
        signal_id = f"{self.bot_id}_{symbol}_{generated_at.isoformat()}"
        
        with self._lock:
            with sqlite3.connect(str(self.db_path), timeout=5.0) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO signal_queue
                    (signal_id, bot_id, user_id, symbol, side, strategy_signal, bias,
                     generated_at, signal_price, vwap, target_qty, note, delta_pct,
                     batch_label, status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    signal_id,
                    self.bot_id,
                    self.user_id,
                    symbol,
                    side,
                    strategy_signal,
                    bias,
                    generated_at.isoformat(),
                    signal_price,
                    vwap,
                    target_qty,
                    note,
                    delta_pct,
                    batch_label,
                    'queued',
                    datetime.now(timezone.utc).isoformat(),
                ))
                conn.commit()
        
        log_line(f"[SignalQueue] Queued signal: {symbol} {side} @ {signal_price:.2f} (ID: {signal_id})")
        return signal_id
    
    def get_queued_signals(self, status: str = 'queued') -> List[Dict[str, Any]]:
        """
        Get all queued signals.
        
        Args:
            status: Filter by status (default: 'queued')
            
        Returns:
            List of signal dictionaries
        """
        with self._lock:
            with sqlite3.connect(str(self.db_path), timeout=5.0) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT signal_id, symbol, side, strategy_signal, bias,
                           generated_at, signal_price, vwap, target_qty, note,
                           delta_pct, batch_label, status, executed_at
                    FROM signal_queue
                    WHERE bot_id = ? AND user_id = ? AND status = ?
                    ORDER BY generated_at ASC
                """, (self.bot_id, self.user_id, status))
                
                rows = cursor.fetchall()
                signals = []
                for row in rows:
                    signals.append({
                        'signal_id': row[0],
                        'symbol': row[1],
                        'side': row[2],
                        'strategy_signal': row[3],
                        'bias': row[4],
                        'generated_at': datetime.fromisoformat(row[5]),
                        'signal_price': row[6],
                        'vwap': row[7],
                        'target_qty': row[8],
                        'note': row[9],
                        'delta_pct': row[10],
                        'batch_label': row[11],
                        'status': row[12],
                        'executed_at': datetime.fromisoformat(row[13]) if row[13] else None,
                    })
                return signals
    
    def mark_executed(self, signal_id: str, executed_at: Optional[datetime] = None) -> None:
        """
        Mark signal as executed.
        
        Args:
            signal_id: Signal ID
            executed_at: Execution timestamp (default: now)
        """
        if executed_at is None:
            executed_at = datetime.now(timezone.utc)
        
        with self._lock:
            with sqlite3.connect(str(self.db_path), timeout=5.0) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE signal_queue
                    SET status = 'executed', executed_at = ?
                    WHERE signal_id = ? AND bot_id = ? AND user_id = ?
                """, (executed_at.isoformat(), signal_id, self.bot_id, self.user_id))
                conn.commit()
        
        log_line(f"[SignalQueue] Marked signal {signal_id} as executed")
    
    def mark_failed(self, signal_id: str, reason: str = "") -> None:
        """
        Mark signal as failed.
        
        Args:
            signal_id: Signal ID
            reason: Failure reason
        """
        with self._lock:
            with sqlite3.connect(str(self.db_path), timeout=5.0) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE signal_queue
                    SET status = 'failed', note = note || ' | Failed: ' || ?
                    WHERE signal_id = ? AND bot_id = ? AND user_id = ?
                """, (reason, signal_id, self.bot_id, self.user_id))
                conn.commit()
        
        log_line(f"[SignalQueue] Marked signal {signal_id} as failed: {reason}")
    
    def remove_signal(self, signal_id: str) -> None:
        """
        Remove signal from queue.
        
        Args:
            signal_id: Signal ID to remove
        """
        with self._lock:
            with sqlite3.connect(str(self.db_path), timeout=5.0) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    DELETE FROM signal_queue
                    WHERE signal_id = ? AND bot_id = ? AND user_id = ?
                """, (signal_id, self.bot_id, self.user_id))
                conn.commit()
    
    def clear_old_signals(self, days: int = 7) -> int:
        """
        Clear signals older than specified days.
        
        Args:
            days: Keep signals newer than this many days
            
        Returns:
            Number of signals removed
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        
        with self._lock:
            with sqlite3.connect(str(self.db_path), timeout=5.0) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    DELETE FROM signal_queue
                    WHERE bot_id = ? AND user_id = ? 
                    AND (status = 'executed' OR status = 'failed')
                    AND executed_at < ?
                """, (self.bot_id, self.user_id, cutoff.isoformat()))
                removed = cursor.rowcount
                conn.commit()
        
        if removed > 0:
            log_line(f"[SignalQueue] Cleared {removed} old signal(s) older than {days} days")
        return removed
    
    def count_queued(self) -> int:
        """Get count of queued signals."""
        with self._lock:
            with sqlite3.connect(str(self.db_path), timeout=5.0) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT COUNT(*) FROM signal_queue
                    WHERE bot_id = ? AND user_id = ? AND status = 'queued'
                """, (self.bot_id, self.user_id))
                return cursor.fetchone()[0]


__all__ = ["SignalQueue"]

