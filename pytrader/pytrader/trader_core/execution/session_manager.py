"""
Session lifecycle management for trading sessions.

This module provides session-aware persistence, enabling the dashboard to
restore historical trading data across bot restarts.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class TradingSession:
    """Represents a single trading session with metadata."""
    
    session_id: str
    bot_id: str
    start_time: datetime
    end_time: Optional[datetime]
    mode: str  # "backtest" | "paper-live" | "live-warm"
    initial_cash: float
    symbols: List[str]
    config: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict."""
        data = asdict(self)
        data["start_time"] = self.start_time.isoformat()
        if self.end_time:
            data["end_time"] = self.end_time.isoformat()
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TradingSession:
        """Create from dict loaded from JSON."""
        data = dict(data)  # Don't modify original
        data["start_time"] = datetime.fromisoformat(data["start_time"])
        if data.get("end_time"):
            data["end_time"] = datetime.fromisoformat(data["end_time"])
        return cls(**data)


class SessionManager:
    """
    Manages trading session lifecycle and persistence.
    
    Responsibilities:
    - Create new session on bot startup
    - Record session metadata to sessions.jsonl
    - Update active_session.json with current session ID
    - Provide session directory paths for telemetry
    """
    
    def __init__(self, bot_id: str, log_dir: Path) -> None:
        self.bot_id = bot_id
        self.log_dir = Path(log_dir) / bot_id
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        self.sessions_file = self.log_dir / "sessions.jsonl"
        self.active_pointer = self.log_dir / "active_session.json"
        self.current_session: Optional[TradingSession] = None
    
    def start_session(
        self,
        mode: str,
        initial_cash: float,
        symbols: List[str],
        config: Optional[Dict[str, Any]] = None,
    ) -> TradingSession:
        """
        Start a new trading session.
        
        Args:
            mode: Trading mode ("backtest", "paper-live", "live-warm")
            initial_cash: Starting capital
            symbols: List of symbols being traded
            config: Optional engine configuration snapshot
        
        Returns:
            The created TradingSession
        """
        # Generate session ID (timestamp-based for human readability)
        now = datetime.now(timezone.utc)
        timestamp_str = now.strftime("%Y%m%d_%H%M%S")
        short_id = str(uuid.uuid4())[:8]
        session_id = f"{timestamp_str}_{short_id}"
        
        # Create session object
        session = TradingSession(
            session_id=session_id,
            bot_id=self.bot_id,
            start_time=now,
            end_time=None,
            mode=mode,
            initial_cash=initial_cash,
            symbols=symbols,
            config=config or {},
        )
        
        # Create session directory
        session_dir = self.get_session_dir(session_id)
        session_dir.mkdir(parents=True, exist_ok=True)
        print(f"[SessionManager] Created session directory: {session_dir}")
        
        # Write session info to dedicated file
        session_info = session_dir / "session_info.json"
        with session_info.open("w", encoding="utf-8") as f:
            json.dump(session.to_dict(), f, indent=2)
        print(f"[SessionManager] Wrote session info: {session_info}")
        
        # Append to sessions registry
        with self.sessions_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(session.to_dict()))
            f.write("\n")
        print(f"[SessionManager] Appended to sessions registry: {self.sessions_file}")
        
        # Update active session pointer
        with self.active_pointer.open("w", encoding="utf-8") as f:
            json.dump({"session_id": session_id, "updated_at": now.isoformat()}, f, indent=2)
        print(f"[SessionManager] Updated active session pointer: {self.active_pointer}")
        
        self.current_session = session
        return session
    
    def end_session(self) -> None:
        """Mark the current session as ended."""
        if not self.current_session:
            return
        
        now = datetime.now(timezone.utc)
        self.current_session.end_time = now
        
        # Update session info file
        session_dir = self.get_session_dir(self.current_session.session_id)
        session_info = session_dir / "session_info.json"
        with session_info.open("w", encoding="utf-8") as f:
            json.dump(self.current_session.to_dict(), f, indent=2)
        
        # Re-append to sessions.jsonl with end_time (creating historical log)
        with self.sessions_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(self.current_session.to_dict()))
            f.write("\n")
    
    def get_active_session(self) -> Optional[TradingSession]:
        """
        Get the currently active session.
        
        Returns:
            Current session if one exists, None otherwise
        """
        if self.current_session:
            return self.current_session
        
        if not self.active_pointer.exists():
            return None
        
        try:
            with self.active_pointer.open("r", encoding="utf-8") as f:
                pointer = json.load(f)
            
            session_id = pointer.get("session_id")
            if not session_id:
                return None
            
            # Load session info
            session_dir = self.get_session_dir(session_id)
            session_info = session_dir / "session_info.json"
            
            if not session_info.exists():
                return None
            
            with session_info.open("r", encoding="utf-8") as f:
                data = json.load(f)
            
            self.current_session = TradingSession.from_dict(data)
            return self.current_session
        
        except (json.JSONDecodeError, KeyError, FileNotFoundError):
            return None
    
    def get_all_sessions(self) -> List[TradingSession]:
        """
        Get all sessions for this bot from the sessions registry.
        
        Returns:
            List of all TradingSession objects, newest first
        """
        if not self.sessions_file.exists():
            return []
        
        sessions: List[TradingSession] = []
        seen_ids: set = set()
        
        try:
            with self.sessions_file.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    
                    try:
                        data = json.loads(line)
                        session = TradingSession.from_dict(data)
                        
                        # Keep only the latest entry for each session_id
                        # (handles updates with end_time)
                        if session.session_id in seen_ids:
                            # Replace existing entry
                            sessions = [s for s in sessions if s.session_id != session.session_id]
                        
                        sessions.append(session)
                        seen_ids.add(session.session_id)
                    
                    except (json.JSONDecodeError, KeyError, TypeError):
                        # Skip corrupted lines
                        continue
        
        except FileNotFoundError:
            return []
        
        # Sort by start_time, newest first
        sessions.sort(key=lambda s: s.start_time, reverse=True)
        return sessions
    
    def get_session_dir(self, session_id: str) -> Path:
        """
        Get the directory path for a specific session.
        
        Args:
            session_id: The session identifier
        
        Returns:
            Path to the session directory
        """
        return self.log_dir / session_id
    
    def get_latest_session(self) -> Optional[TradingSession]:
        """
        Get the most recent session (even if ended).
        
        Returns:
            Latest TradingSession or None
        """
        sessions = self.get_all_sessions()
        return sessions[0] if sessions else None
