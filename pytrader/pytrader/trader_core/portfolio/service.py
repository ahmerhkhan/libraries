from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import DateTime, Float, Integer, String, create_engine, delete, select
from sqlalchemy.orm import Mapped, Session, declarative_base, mapped_column

from ...config import settings

Base = declarative_base()


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    symbol: Mapped[str] = mapped_column(String, nullable=False, index=True)
    side: Mapped[str] = mapped_column(String, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    cost: Mapped[float] = mapped_column(Float, nullable=False)
    pnl_realized: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    fees: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    slippage_bps: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)


class Position(Base):
    __tablename__ = "positions"

    symbol: Mapped[str] = mapped_column(String, primary_key=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    avg_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)


class EquityPoint(Base):
    __tablename__ = "equity"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    equity_value: Mapped[float] = mapped_column(Float, nullable=False)
    cash: Mapped[float] = mapped_column(Float, nullable=False)
    unrealized_pnl: Mapped[float] = mapped_column(Float, nullable=False)


def _ensure_data_dir(db_url: str) -> None:
    if db_url.startswith("sqlite"):
        path = db_url.split("///")[-1]
        directory = os.path.dirname(path)
        if directory and not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)


def get_engine(db_url: Optional[str] = None):
    uri = db_url or getattr(settings, "db_url", "sqlite:///data/trader.db")
    _ensure_data_dir(uri)
    return create_engine(uri, future=True)


def init_db(db_url: Optional[str] = None) -> None:
    engine = get_engine(db_url)
    Base.metadata.create_all(engine)


@dataclass
class PortfolioSummary:
    cash: float
    positions: List[Dict[str, Any]]
    unrealized_pnl: float
    realized_pnl: float
    equity: float
    last_updated: Optional[datetime]


class PortfolioService:
    """Persistent portfolio ledger shared by backtest and live engines."""

    def __init__(
        self, 
        db_url: Optional[str] = None, 
        *, 
        initial_cash: Optional[float] = None,
        unlimited_cash: bool = False,
        allow_short: bool = False,
        api_client: Optional[Any] = None,  # NEW: Optional API client for backend sync
        bot_id: Optional[str] = None,     # NEW: Bot ID for backend sync
    ) -> None:
        self.db_url = db_url or getattr(settings, "db_url", "sqlite:///data/trader.db")
        _ensure_data_dir(self.db_url)
        self.engine = create_engine(self.db_url, future=True)
        Base.metadata.create_all(self.engine)

        default_cash = float(initial_cash) if initial_cash is not None else float(getattr(settings, "default_cash", 1_000_000.0))
        self.initial_cash = default_cash
        self.unlimited_cash = unlimited_cash  # For backtests: allow unlimited virtual cash
        self.allow_short = allow_short  # Allow short selling (negative positions)
        
        # Store API client for ongoing sync (optional)
        self._api_client = api_client
        self._bot_id = bot_id

        # BACKEND-DRIVEN WARM START
        # If API client provided, sync from backend (authoritative source)
        # Otherwise, use local state (backtesting, standalone mode)
        if api_client and bot_id:
            try:
                self._sync_from_backend()
            except Exception as exc:
                import logging
                logging.warning(
                    f"Failed to sync from backend for bot {bot_id}: {exc}. "
                    f"Falling back to local state. This may cause state divergence."
                )
                # Fall through to local initialization
                self._init_from_local()
        else:
            # No API client - standalone mode (backtesting, etc.)
            self._init_from_local()

    def _init_from_local(self) -> None:
        """Initialize from local SQLite (fallback or standalone mode)."""
        with Session(self.engine, expire_on_commit=False) as session:
            last = session.execute(select(EquityPoint).order_by(EquityPoint.ts.desc())).scalars().first()
            if last is None:
                # Cold start: No existing data, create initial equity point
                initial_ts = datetime.now(timezone.utc) - timedelta(days=3650)
                session.add(
                    EquityPoint(
                        ts=initial_ts,
                        equity_value=self.initial_cash,
                        cash=self.initial_cash,
                        unrealized_pnl=0.0,
                    )
                )
                session.commit()
            # Warm start: Resume from last known state
            # Do NOT reset equity - preserve trading history across restarts

    def _sync_from_backend(self) -> None:
        """
        Sync portfolio state from backend (authoritative source).
        
        This is called on SDK startup to ensure local state matches backend.
        Backend is ALWAYS the source of truth.
        """
        import logging
        logger = logging.getLogger(__name__)
        
        if not self._api_client or not self._bot_id:
            raise ValueError("API client and bot_id required for backend sync")
        
        try:
            # Call backend /state endpoint
            response = self._api_client.get(f"/bots/{self._bot_id}/state")
            state = response.json() if hasattr(response, 'json') else response
            
            logger.info(f"Syncing from backend for bot {self._bot_id}")
            logger.debug(f"Backend state: equity={state.get('equity')}, cash={state.get('cash')}, positions={len(state.get('positions', []))}")
            
            # Clear local state to avoid mixing
            self._clear_local_state()
            
            # Restore from backend state
            backend_cash = float(state.get('cash', 0.0))
            backend_equity = float(state.get('equity', 0.0))
            backend_positions = state.get('positions', [])
            
            # Initialize equity point from backend
            with Session(self.engine, expire_on_commit=False) as session:
                # Create equity point to match backend
                session.add(
                    EquityPoint(
                        ts=datetime.now(timezone.utc),
                        equity_value=backend_equity,
                        cash=backend_cash,
                        unrealized_pnl=backend_equity - backend_cash,
                    )
                )
                
                # Restore positions from backend
                for pos_data in backend_positions:
                    symbol = pos_data.get('symbol')
                    qty = float(pos_data.get('qty', 0))
                    avg_cost = float(pos_data.get('avg_cost', 0))
                    
                    if qty == 0:
                        continue  # Skip zero positions
                    
                    # Check if position exists
                    existing = session.execute(
                        select(Position).where(Position.symbol == symbol)
                    ).scalars().first()
                    
                    if existing:
                        existing.qty = qty
                        existing.avg_price = avg_cost
                    else:
                        session.add(Position(symbol=symbol, qty=qty, avg_price=avg_cost))
                
                session.commit()
            
            logger.info(f"Successfully synced from backend: equity={backend_equity}, cash={backend_cash}, {len(backend_positions)} positions")
            
        except Exception as exc:
            logger.error(f"Backend sync failed: {exc}", exc_info=True)
            raise

    def _clear_local_state(self) -> None:
        """Clear local SQLite state to prepare for backend sync."""
        with Session(self.engine, expire_on_commit=False) as session:
            # Clear all positions
            session.execute(delete(Position))
            # Clear equity history (we'll create one fresh equity point)
            session.execute(delete(EquityPoint))
            session.commit()


    # Convenience helpers used by some parts of the SDK / strategies.
    # These simply delegate to record_trade while keeping all validation
    # and ledger logic in a single place.
    def buy(
        self,
        ts: datetime,
        symbol: str,
        quantity: int,
        price: float,
        *,
        fees: float = 0.0,
        slippage_bps: float = 0.0,
        debug: bool = False,
    ) -> Trade:
        return self.record_trade(
            ts=ts,
            symbol=symbol,
            side="BUY",
            quantity=quantity,
            price=price,
            fees=fees,
            slippage_bps=slippage_bps,
            debug=debug,
        )

    def sell(
        self,
        ts: datetime,
        symbol: str,
        quantity: int,
        price: float,
        *,
        fees: float = 0.0,
        slippage_bps: float = 0.0,
        debug: bool = False,
    ) -> Trade:
        return self.record_trade(
            ts=ts,
            symbol=symbol,
            side="SELL",
            quantity=quantity,
            price=price,
            fees=fees,
            slippage_bps=slippage_bps,
            debug=debug,
        )

    def _get_cash(self, session: Session) -> float:
        last = session.execute(select(EquityPoint).order_by(EquityPoint.ts.desc())).scalars().first()
        default_cash = self.initial_cash
        if last:
            cash = float(last.cash)
            return default_cash if cash < 0 else cash
        return default_cash

    def _set_cash(self, session: Session, new_cash: float) -> None:
        last = session.execute(select(EquityPoint).order_by(EquityPoint.ts.desc())).scalars().first()
        if last:
            last.cash = float(new_cash)
            session.add(last)
        else:
            session.add(
                EquityPoint(
                    ts=datetime.now(timezone.utc),
                    equity_value=float(new_cash),
                    cash=float(new_cash),
                    unrealized_pnl=0.0,
                )
            )

    def get_positions(self, session: Optional[Session] = None) -> List[Position]:
        if session is None:
            with Session(self.engine, expire_on_commit=False) as s:
                return list(s.execute(select(Position)).scalars().all())
        return list(session.execute(select(Position)).scalars().all())

    def calculate_affordable_quantity(
        self,
        price: float,
        *,
        fees_per_share: float = 0.0,
        fees_pct_notional: float = 0.0,
        slippage_bps: float = 0.0,
        available_cash: Optional[float] = None,
    ) -> int:
        """
        Calculate the maximum affordable quantity for a BUY order considering fees and slippage.
        
        Args:
            price: Base price per share
            fees_per_share: Fixed fee per share
            fees_pct_notional: Percentage fee on notional value
            slippage_bps: Slippage in basis points (positive for BUY increases cost)
            available_cash: Available cash (if None, uses current cash from portfolio)
            
        Returns:
            Maximum affordable quantity (0 if insufficient cash, or very large number if unlimited_cash is enabled)
        """
        # For backtests with unlimited cash, return a very large number to allow any trade
        if self.unlimited_cash:
            return 1_000_000_000  # Effectively unlimited
        
        if available_cash is None:
            with Session(self.engine, expire_on_commit=False) as session:
                available_cash = self._get_cash(session)
        
        if available_cash <= 0:
            return 0
        
        # Apply slippage to price
        slippage_multiplier = 1 + slippage_bps / 10_000
        adjusted_price = price * slippage_multiplier
        
        # For a quantity q, total cost = q * adjusted_price + q * fees_per_share + q * adjusted_price * fees_pct_notional
        # = q * adjusted_price * (1 + fees_pct_notional) + q * fees_per_share
        # = q * (adjusted_price * (1 + fees_pct_notional) + fees_per_share)
        # So: q = available_cash / (adjusted_price * (1 + fees_pct_notional) + fees_per_share)
        
        cost_per_share = adjusted_price * (1 + fees_pct_notional) + fees_per_share
        
        if cost_per_share <= 0:
            return 0
        
        max_qty = int(available_cash / cost_per_share)
        return max(0, max_qty)

    def record_trade(
        self,
        ts: datetime,
        symbol: str,
        side: str,
        quantity: int,
        price: float,
        *,
        fees: float = 0.0,
        slippage_bps: float = 0.0,
        debug: bool = False,
    ) -> Trade:
        side = side.upper()
        cost = -price * quantity if side == "BUY" else price * quantity
        realized_pnl = 0.0

        with Session(self.engine, expire_on_commit=False) as session:
            cash = self._get_cash(session)
            total_cost = abs(cost) + fees if side == "BUY" else 0.0
            
            if debug:
                print(f"[DEBUG] Before trade: cash={cash:.2f}, side={side}, qty={quantity}, price={price:.2f}, fees={fees:.2f}, total_cost={total_cost:.2f}")
            
            if side == "BUY":
                # Check if we have enough cash for the trade including fees
                # cost is negative for BUY, so cash + cost - fees = cash - (price * qty) - fees
                required_cash = abs(cost) + fees
                # For backtests with unlimited cash, skip cash validation entirely
                # When unlimited_cash is True, we allow all trades to proceed regardless of cash balance
                if not self.unlimited_cash and cash < required_cash:
                    # Calculate what we can actually afford
                    # We need to account for slippage-adjusted price and fees
                    slippage_multiplier = 1 + abs(slippage_bps) / 10_000
                    adjusted_price = price * slippage_multiplier
                    # Estimate fees per share and percentage
                    # This is approximate - actual fees depend on quantity
                    estimated_fees_per_share = fees / max(quantity, 1)
                    estimated_fees_pct = fees / max(abs(cost), 1e-6) if abs(cost) > 0 else 0.0
                    
                    # Calculate affordable quantity
                    cost_per_share = adjusted_price * (1 + estimated_fees_pct) + estimated_fees_per_share
                    if cost_per_share > 0:
                        max_affordable_qty = int(cash / cost_per_share)
                    else:
                        max_affordable_qty = 0
                    
                    # Check if we're just slightly short (less than 1% of trade value) and can do partial fill
                    shortage = required_cash - cash
                    trade_value = price * quantity
                    if shortage < trade_value * 0.01 and max_affordable_qty > 0:
                        if debug:
                            pass  # Debug mode - could add logging here if needed
                        quantity = max_affordable_qty
                        cost = -price * quantity
                        # Recalculate fees for new quantity (approximate)
                        fees = quantity * estimated_fees_per_share + abs(cost) * estimated_fees_pct
                    else:
                        raise ValueError(f"Insufficient cash for BUY: need {required_cash:.2f}, have {cash:.2f}")

            pos = session.get(Position, symbol)
            if pos is None:
                pos = Position(symbol=symbol, quantity=0, avg_cost=0.0)
                session.add(pos)

            if side == "BUY":
                new_qty = pos.quantity + quantity
                if new_qty == 0:
                    # Closing a short position exactly
                    realized_pnl = (pos.avg_cost - price) * abs(pos.quantity)  # Profit when covering short at lower price
                    pos.quantity = 0
                    pos.avg_cost = 0.0
                elif new_qty > 0:
                    # Long position or covering short to go long
                    if pos.quantity < 0:
                        # Covering short position (partially or fully)
                        cover_qty = min(quantity, abs(pos.quantity))
                        realized_pnl = (pos.avg_cost - price) * cover_qty  # Profit when covering at lower price
                        remaining_qty = quantity - cover_qty
                        if remaining_qty > 0:
                            # Going long after covering
                            pos.avg_cost = price
                            pos.quantity = remaining_qty
                        else:
                            # Fully covered, no long position
                            pos.quantity = new_qty
                            pos.avg_cost = 0.0 if new_qty == 0 else price
                    else:
                        # Adding to long position
                        pos.avg_cost = (pos.avg_cost * pos.quantity + price * quantity) / new_qty
                        pos.quantity = new_qty
                        realized_pnl = 0.0  # No realized PnL when adding to position
                else:
                    # Still short after buying (shouldn't happen normally, but handle it)
                    pos.quantity = new_qty
                    pos.avg_cost = price
                    realized_pnl = 0.0
            else:  # SELL
                if pos.quantity > 0:
                    # Selling from long position
                    sell_qty = min(quantity, pos.quantity)
                    realized_pnl = (price - pos.avg_cost) * sell_qty
                    pos.quantity -= sell_qty
                    if pos.quantity == 0:
                        pos.avg_cost = 0.0
                elif pos.quantity < 0:
                    # Adding to short position
                    realized_pnl = 0.0  # No realized PnL when adding to short
                    old_qty_abs = abs(pos.quantity)
                    pos.quantity = pos.quantity - quantity  # More negative
                    new_qty_abs = abs(pos.quantity)
                    # Weighted average: (old_avg * old_qty + new_price * new_qty) / total_qty
                    pos.avg_cost = (pos.avg_cost * old_qty_abs + price * quantity) / new_qty_abs if new_qty_abs > 0 else price
                else:
                    # No position - shorting
                    if not self.allow_short:
                        raise ValueError("No position to sell and short selling is not allowed")
                    # Opening short position
                    pos.quantity = -quantity
                    pos.avg_cost = price
                    realized_pnl = 0.0  # No realized PnL when opening short

            trade = Trade(
                ts=ts,
                symbol=symbol,
                side=side,
                quantity=quantity,
                price=price,
                cost=cost,
                pnl_realized=realized_pnl,
                fees=fees,
                slippage_bps=slippage_bps,
            )
            session.add(trade)
            new_cash = cash + cost - fees
            self._set_cash(session, new_cash)
            
            if debug:
                print(f"[DEBUG] After trade: cash={new_cash:.2f}, equity={session.execute(select(EquityPoint).order_by(EquityPoint.ts.desc())).scalars().first().equity_value:.2f}")
            
            session.commit()
            
            # Assert that cash never goes negative (unless unlimited cash mode or margin trading is enabled)
            if not self.unlimited_cash and new_cash < -1e-6:  # Allow tiny rounding errors
                raise ValueError(f"Cash balance went negative: {new_cash:.2f}")
            
            return trade

    def revalue_and_snapshot(self, ts: datetime, prices: Dict[str, float]) -> EquityPoint:
        with Session(self.engine, expire_on_commit=False) as session:
            positions = self.get_positions(session)
            unreal = 0.0
            for p in positions:
                price = float(prices.get(p.symbol, p.avg_cost))
                unreal += (price - p.avg_cost) * p.quantity

            cash = self._get_cash(session)
            equity = cash + sum(float(prices.get(p.symbol, p.avg_cost)) * p.quantity for p in positions)
            ep = EquityPoint(ts=ts, equity_value=equity, cash=cash, unrealized_pnl=unreal)
            session.add(ep)
            session.commit()
            return ep

    def get_summary(self, prices: Optional[Dict[str, float]] = None) -> PortfolioSummary:
        with Session(self.engine, expire_on_commit=False) as session:
            positions = self.get_positions(session)
            last = session.execute(select(EquityPoint).order_by(EquityPoint.ts.desc())).scalars().first()

            default_cash = self.initial_cash
            if last:
                cash = float(last.cash)
                equity = float(last.equity_value)
                unreal = float(last.unrealized_pnl)
            else:
                cash = default_cash
                equity = default_cash
                unreal = 0.0

            if cash < 0:
                cash = default_cash

            realized = sum(t.pnl_realized for t in session.execute(select(Trade)).scalars().all())

            # Build position view with enriched data
            pos_view = []
            for p in positions:
                if p.quantity == 0:
                    continue
                    
                avg_cost = float(p.avg_cost)
                current_price = avg_cost  # Default to avg_cost
                
                # If prices provided, use current market price
                if prices and p.symbol in prices:
                    current_price = float(prices[p.symbol])
                
                pos_view.append({
                    "symbol": p.symbol,
                    "qty": p.quantity,
                    "avg_cost": avg_cost,
                    "current_price": current_price,  # Include current price for frontend
                })

            return PortfolioSummary(
                cash=cash,
                positions=pos_view,
                unrealized_pnl=unreal,
                realized_pnl=realized,
                equity=equity,
                last_updated=last.ts if last else None,
            )

    def get_equity_curve(self, limit: int = 200) -> List[Dict[str, float]]:
        with Session(self.engine, expire_on_commit=False) as session:
            rows = session.execute(select(EquityPoint).order_by(EquityPoint.ts.desc()).limit(limit)).scalars().all()
            rows = list(reversed(rows))
            return [
                {
                    "ts": ep.ts.isoformat(),
                    "equity": ep.equity_value,
                    "cash": ep.cash,
                    "unrealized_pnl": ep.unrealized_pnl,
                }
                for ep in rows
            ]

    def get_trades(self, limit: int = 100, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        with Session(self.engine, expire_on_commit=False) as session:
            query = select(Trade).order_by(Trade.ts.desc())
            if symbol:
                query = query.where(Trade.symbol == symbol)
            trades = session.execute(query.limit(limit)).scalars().all()
            rows = [
                {
                    "id": t.id,
                    "ts": t.ts.isoformat(),
                    "symbol": t.symbol,
                    "side": t.side,
                    "quantity": t.quantity,
                    "price": t.price,
                    "cost": t.cost,
                    "pnl_realized": t.pnl_realized,
                    "fees": t.fees,
                    "commission": t.fees,
                    "slippage_bps": t.slippage_bps,
                }
                for t in trades
            ]
            return rows

    def apply_cash_adjustment(self, delta: float) -> None:
        with Session(self.engine, expire_on_commit=False) as session:
            cash = self._get_cash(session)
            self._set_cash(session, cash + delta)
            session.commit()

    def overwrite_cash(self, new_cash: float, *, ts: Optional[datetime] = None) -> None:
        """
        Overwrite cash balance to an absolute value.

        This keeps the latest unrealized PnL component unchanged and shifts equity by
        the delta between old_cash and new_cash. That avoids wiping equity/PnL history
        when cash is injected mid-session.
        """
        now = ts or datetime.now(timezone.utc)
        new_cash_value = float(new_cash)

        with Session(self.engine, expire_on_commit=False) as session:
            last = session.execute(select(EquityPoint).order_by(EquityPoint.ts.desc())).scalars().first()
            if last:
                old_cash = float(last.cash)
                delta = new_cash_value - old_cash
                new_equity = float(last.equity_value) + delta
                unreal = float(last.unrealized_pnl)
            else:
                new_equity = new_cash_value
                unreal = 0.0

            session.add(
                EquityPoint(
                    ts=now,
                    equity_value=new_equity,
                    cash=new_cash_value,
                    unrealized_pnl=unreal,
                )
            )
            session.commit()


__all__ = [
    "PortfolioService",
    "PortfolioSummary",
    "Trade",
    "Position",
    "EquityPoint",
    "init_db",
    "get_engine",
]
