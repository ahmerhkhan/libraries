from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import Tuple

from ..config import settings


def now_tz() -> datetime:
    # Get timezone from settings or use default
    tz = "Asia/Karachi"
    if settings is not None:
        tz = getattr(settings, "timezone", "Asia/Karachi")
    else:
        import os
        tz = os.getenv("PYTRADER_TZ", "Asia/Karachi")
    try:
        tzinfo = ZoneInfo(tz)
    except ZoneInfoNotFoundError:
        try:
            # tzdata ensures Olson database is available cross-platform (esp. Windows)
            import tzdata  # noqa: F401
            tzinfo = ZoneInfo(tz)
        except ZoneInfoNotFoundError:
            try:
                from dateutil import tz as dateutil_tz

                tzinfo = dateutil_tz.gettz(tz)
            except Exception:
                tzinfo = None
        if tzinfo is None:
            tzinfo = ZoneInfo("UTC")
    return datetime.now(tzinfo)


def is_market_open(at: datetime | None = None) -> bool:
    """
    Check if market is currently open.
    
    DEPRECATED: Use MarketHoursService instead for backend-integrated checks.
    This function now delegates to the service for consistency.
    
    Args:
        at: Datetime to check (default: current time). Only used if service unavailable.
    
    Returns:
        True if market is open
    """
    try:
        from .market_hours_service import get_market_hours_service
        service = get_market_hours_service()
        return service.is_market_open()
    except Exception:
        # Fallback to old logic if service unavailable
        t = at or now_tz()
        # Get market hours from settings or use defaults
        if settings is not None and hasattr(settings, 'market_hours'):
            open_hour = getattr(settings.market_hours, 'open_hour', 9)
            open_minute = getattr(settings.market_hours, 'open_minute', 0)
            close_hour = getattr(settings.market_hours, 'close_hour', 15)
            close_minute = getattr(settings.market_hours, 'close_minute', 30)
        else:
            open_hour, open_minute = 9, 0
            close_hour, close_minute = 15, 30
        open_t = time(open_hour, open_minute)
        close_t = time(close_hour, close_minute)
        return open_t <= t.time() <= close_t and t.weekday() < 5


def minutes_until_next_alignment(alignment_minutes: int | None = None) -> int:
    align = alignment_minutes
    if align is None:
        if settings is not None:
            align = getattr(settings, "alignment_minutes", 15)
        else:
            import os
            align = int(os.getenv("PYTRADER_ALIGN_MIN", "15"))
    t = now_tz()
    minute = (t.minute // align + 1) * align
    next_tick = t.replace(minute=0, second=0, microsecond=0) + timedelta(minutes=minute)
    delta = next_tick - t
    return max(0, int(delta.total_seconds() // 60))


def is_alignment_minute(alignment_minutes: int | None = None, at: datetime | None = None) -> bool:
    align = alignment_minutes
    if align is None:
        if settings is not None:
            align = getattr(settings, "alignment_minutes", 15)
        else:
            import os
            align = int(os.getenv("PYTRADER_ALIGN_MIN", "15"))
    t = at or now_tz()
    return t.minute % align == 0 and t.second < 5


def today_session_window(at: datetime | None = None) -> Tuple[datetime, datetime]:
    t = at or now_tz()
    # Get market hours from settings or use defaults
    if settings is not None and hasattr(settings, 'market_hours'):
        open_hour = getattr(settings.market_hours, 'open_hour', 9)
        open_minute = getattr(settings.market_hours, 'open_minute', 0)
        close_hour = getattr(settings.market_hours, 'close_hour', 15)
        close_minute = getattr(settings.market_hours, 'close_minute', 30)
    else:
        open_hour, open_minute = 9, 0
        close_hour, close_minute = 15, 30
    start = t.replace(hour=open_hour, minute=open_minute, second=0, microsecond=0)
    end = t.replace(hour=close_hour, minute=close_minute, second=0, microsecond=0)
    return start, end


def next_market_open(after: datetime | None = None) -> datetime:
    ref = after or now_tz()
    session_start, _ = today_session_window(ref)
    if ref < session_start and ref.weekday() < 5:
        return session_start

    candidate = session_start + timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate


