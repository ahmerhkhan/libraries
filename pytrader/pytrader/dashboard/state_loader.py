"""
Session state loader for dashboard persistence.

Loads historical session data from disk to hydrate DashboardState,
enabling the frontend to restore trading history across bot restarts.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, List, Optional


class SessionStateLoader:
    """
    Loads historical session data to hydrate DashboardState.
    
    Reads session-scoped files (equity_history.jsonl, trades.csv, etc.)
    and returns a state dict that DashboardState can use to restore history.
    """
    
    def __init__(self, bot_id: str, log_dir: Path) -> None:
        self.bot_id = bot_id
        self.log_dir = Path(log_dir) / bot_id
    
    def load_latest_session(self) -> Dict[str, Any]:
        """
        Load the most recent session's data for dashboard hydration.
        
        Returns:
            Dict with keys: equity_history, trades, snapshot, session_info
        """
        # Check if sessions exist (session-scoped format)
        active_pointer = self.log_dir / "active_session.json"
        if active_pointer.exists():
            try:
                with active_pointer.open("r", encoding="utf-8") as f:
                    pointer = json.load(f)
                
                session_id = pointer.get("session_id")
                if session_id:
                    return self._load_session_data(session_id)
            
            except (json.JSONDecodeError, FileNotFoundError, KeyError):
                pass  # Fall through to fallback
        
        # Fallback: Try loading from root-level FileTelemetry files
        # (logs/bot_id/trades.csv instead of logs/bot_id/session_id/trades.csv)
        if self.log_dir.exists():
            return self._load_file_telemetry_data()
        
        return self._empty_state()
    
    def load_all_sessions(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Load multiple sessions for aggregated historical view.
        
        Args:
            limit: Maximum number of sessions to load (newest first)
        
        Returns:
            List of session data dicts
        """
        sessions_file = self.log_dir / "sessions.jsonl"
        if not sessions_file.exists():
            return []
        
        # Parse sessions.jsonl to get session IDs
        session_ids = []
        seen_ids = set()
        
        try:
            with sessions_file.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    
                    try:
                        data = json.loads(line)
                        sid = data.get("session_id")
                        
                        if sid and sid not in seen_ids:
                            session_ids.append((data.get("start_time", ""), sid))
                            seen_ids.add(sid)
                    
                    except json.JSONDecodeError:
                        continue
        
        except FileNotFoundError:
            return []
        
        # Sort by start_time, newest first
        session_ids.sort(reverse=True)
        session_ids = session_ids[:limit]
        
        # Load data for each session
        results = []
        for _, session_id in session_ids:
            session_data = self._load_session_data(session_id)
            if session_data.get("equity_history"):
                results.append(session_data)
        
        return results
    
    def _load_session_data(self, session_id: str) -> Dict[str, Any]:
        """Load all data files for a specific session."""
        session_dir = self.log_dir / session_id
        
        if not session_dir.exists():
            return self._empty_state()
        
        # Load session metadata
        session_info_path = session_dir / "session_info.json"
        session_info = {}
        if session_info_path.exists():
            try:
                with session_info_path.open("r", encoding="utf-8") as f:
                    session_info = json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                pass
        
        # Load equity history
        equity_history = self._load_equity_history(session_dir)
        
        # Load trades
        trades = self._load_trades(session_dir)
        
        # Load latest positions snapshot
        positions_snapshot = self._load_latest_positions(session_dir)
        
        # Build latest snapshot for dashboard
        latest_snapshot = self._build_latest_snapshot(
            equity_history,
            positions_snapshot,
            session_info
        )
        
        return {
            "session_id": session_id,
            "session_info": session_info,
            "equity_history": equity_history,
            "trades": trades,
            "snapshot": latest_snapshot,
        }
    
    def _load_equity_history(self, session_dir: Path) -> List[Dict[str, Any]]:
        """Load equity_history.jsonl file."""
        equity_file = session_dir / "equity_history.jsonl"
        if not equity_file.exists():
            return []
        
        history = []
        try:
            with equity_file.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    
                    try:
                        record = json.loads(line)
                        history.append(record)
                    except json.JSONDecodeError:
                        # Skip corrupted lines
                        continue
        
        except FileNotFoundError:
            return []
        
        return history
    
    def _load_trades(self, session_dir: Path) -> List[Dict[str, Any]]:
        """Load trades.csv file."""
        trades_file = session_dir / "trades.csv"
        if not trades_file.exists():
            return []
        
        trades = []
        try:
            with trades_file.open("r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    trades.append(dict(row))
        
        except (FileNotFoundError, csv.Error):
            return []
        
        return trades
    
    def _load_latest_positions(self, session_dir: Path) -> Dict[str, Any]:
        """Load the most recent positions snapshot from positions_snapshot.jsonl."""
        positions_file = session_dir / "positions_snapshot.jsonl"
        if not positions_file.exists():
            return {}
        
        latest = {}
        try:
            with positions_file.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    
                    try:
                        record = json.loads(line)
                        latest = record  # Keep overwriting with latest
                    except json.JSONDecodeError:
                        continue
        
        except FileNotFoundError:
            return {}
        
        return latest
    
    def _build_latest_snapshot(
        self,
        equity_history: List[Dict[str, Any]],
        positions_snapshot: Dict[str, Any],
        session_info: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Build a dashboard-compatible snapshot from loaded data."""
        # Get latest equity point
        latest_equity = equity_history[-1] if equity_history else {}
        
        timestamp = latest_equity.get("timestamp", "")
        equity = latest_equity.get("equity", 0.0)
        cash = latest_equity.get("cash", 0.0)
        positions_value = latest_equity.get("positions_value", 0.0)
        
        # Get positions and prices from positions snapshot
        positions = positions_snapshot.get("positions", [])
        prices = positions_snapshot.get("prices", {})
        
        snapshot = {
            "bot": {
                "id": self.bot_id,
                "symbols": session_info.get("symbols", []),
            },
            "status": "restored",  # Indicate this is loaded from disk
            "equity": equity,
            "cash": cash,
            "positions_value": positions_value,
            "positions": positions,
            "prices": prices,
            "metrics": {},  # Could load from metrics.csv if needed
            "recent_trades": [],  # Will be populated from trade history
            "last_cycle": {
                "timestamp": timestamp,
                "trades": [],
                "batches": [],
                "total_fees": 0.0,
                "avg_slippage_bps": 0.0,
            },
            "equity_history": equity_history,
            "updated_at": timestamp,
        }
        
        return snapshot
    
    def _load_file_telemetry_data(self) -> Dict[str, Any]:
        """
        Fallback: Load data from root-level FileTelemetry files.
        
        This handles the case where FileTelemetry writes to:
        - logs/bot_id/trades.csv
        - logs/bot_id/metrics.jsonl
        
        Instead of session-scoped subdirectories.
        """
        # Load trades from root-level trades.csv
        trades_file = self.log_dir / "trades.csv"
        trades = []
        if trades_file.exists():
            try:
                with trades_file.open("r", newline="", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        # Convert to dashboard format
                        trades.append({
                            "timestamp": row.get("timestamp", ""),
                            "symbol": row.get("symbol", ""),
                            "side": row.get("side", ""),
                            "quantity": row.get("quantity", 0),
                            "price": row.get("price", 0),
                            "pnl_realized": row.get("realized_pnl", 0),
                            "commission": 0,
                            "note": "",
                        })
            except (FileNotFoundError, csv.Error):
                pass
        
        # Load equity history from metrics.jsonl
        metrics_file = self.log_dir / "metrics.jsonl"
        equity_history = []
        if metrics_file.exists():
            try:
                with metrics_file.open("r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        
                        try:
                            record = json.loads(line)
                            # Extract equity history point
                            equity_history.append({
                                "timestamp": record.get("timestamp", ""),
                                "equity": record.get("equity", 0.0),
                                "cash": record.get("cash", 0.0),
                                "positions_value": record.get("positions_value", 0.0),
                            })
                        except json.JSONDecodeError:
                            continue
            except FileNotFoundError:
                pass
        
        # Build snapshot from latest data
        latest_equity = equity_history[-1] if equity_history else {}
        
        snapshot = {
            "bot": {"id": self.bot_id, "symbols": []},
            "status": "restored",
            "equity": latest_equity.get("equity", 0.0),
            "cash": latest_equity.get("cash", 0.0),
            "positions_value": latest_equity.get("positions_value", 0.0),
            "positions": [],  # Not available in FileTelemetry
            "prices": {},
            "metrics": {},
            "recent_trades": [],
            "last_cycle": {
                "timestamp": latest_equity.get("timestamp", ""),
                "trades": [],
                "batches": [],
                "total_fees": 0.0,
                "avg_slippage_bps": 0.0,
            },
            "equity_history": equity_history,
            "updated_at": latest_equity.get("timestamp", ""),
        }
        
        return {
            "session_id": "file_telemetry",
            "session_info": {},
            "equity_history": equity_history,
            "trades": trades,
            "snapshot": snapshot,
        }
    
    def _empty_state(self) -> Dict[str, Any]:
        """Return empty state for when no data exists."""
        return {
            "session_id": None,
            "session_info": {},
            "equity_history": [],
            "trades": [],
            "snapshot": {
                "bot": {"id": self.bot_id, "symbols": []},
                "status": "no_data",
                "equity": 0.0,
                "cash": 0.0,
                "positions_value": 0.0,
                "positions": [],
                "prices": {},
                "metrics": {},
                "recent_trades": [],
                "last_cycle": {
                    "timestamp": "",
                    "trades": [],
                    "batches": [],
                    "total_fees": 0.0,
                    "avg_slippage_bps": 0.0,
                },
                "equity_history": [],
                "updated_at": "",
            },
        }
