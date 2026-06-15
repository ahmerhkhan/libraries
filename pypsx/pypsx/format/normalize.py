"""
Data normalization module for PyPSX library.

DEPRECATED: This module is deprecated. Use core.parsers instead.

This module is kept for backward compatibility only.
All new code should use core.parsers.parse_*() functions.

Migration guide:
- normalize_market_watch_html() → core.parsers.parse_market_watch_html()
- normalize_trading_board_html() → core.parsers.parse_trading_board_html()
- normalize_performers_html() → core.parsers.parse_performers_html()
- normalize_timeseries_eod_json() → core.parsers.parse_timeseries_eod_json()
- normalize_timeseries_intraday_json() → core.parsers.parse_timeseries_intraday_json()
- normalize_sector_summary_html() → core.parsers.parse_sector_summary_html()
- normalize_index_constituents_html() → core.parsers.parse_index_constituents_html()
"""

from pypsx.core.parsers import (
    parse_market_watch_html as normalize_market_watch_html,
    parse_trading_board_html as normalize_trading_board_html,
    parse_performers_html as normalize_performers_html,
    parse_performers_json as normalize_performers_json,
    parse_timeseries_eod_json as normalize_timeseries_eod_json,
    parse_timeseries_intraday_json as normalize_timeseries_intraday_json,
    parse_sector_summary_html as normalize_sector_summary_html,
    parse_index_constituents_html as normalize_index_constituents_html,
)

__all__ = [
    "normalize_market_watch_html",
    "normalize_trading_board_html",
    "normalize_performers_html",
    "normalize_performers_json",
    "normalize_timeseries_eod_json",
    "normalize_timeseries_intraday_json",
    "normalize_sector_summary_html",
    "normalize_index_constituents_html",
]
