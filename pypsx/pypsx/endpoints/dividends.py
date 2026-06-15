"""
Dividends endpoint for PyPSX library.

⚠️ WARNING: This endpoint uses EXTERNAL data source (stockanalysis.com).
PSX (dps.psx.com.pk) does not provide a dedicated dividends endpoint.

This module scrapes dividend data from stockanalysis.com as a fallback.
For PSX-only compliance, this endpoint should not be used.
"""

import pandas as pd
from typing import Optional, Dict, Any, Union, List
from loguru import logger

from pypsx.core.fetch import get_html
from pypsx.core.utils import validate_symbol, beautify_dataframe
from pypsx.format.json_utils import to_json


def get_dividend_info(symbol: str, format: str = 'dataframe') -> Optional[Union[pd.DataFrame, Dict[str, Any]]]:
    """
    Get dividend summary information for a stock symbol.

    Scrapes key dividend metrics like dividend yield, annual dividend, ex-dividend date,
    payout frequency, payout ratio, and dividend growth.

    Args:
        symbol: Stock symbol (e.g., 'OGDC')
        format: Output format - 'dataframe' or 'json'

    Returns:
        DataFrame with dividend summary (one row) or JSON dict/list, None if failed
    """
    try:
        normalized_symbol = validate_symbol(symbol)
        logger.info(f"Fetching dividend summary for {normalized_symbol}")

        url = f"https://stockanalysis.com/quote/psx/{normalized_symbol}/dividend/"
        soup = get_html(url)
        if not soup:
            logger.error(f"Failed to fetch dividend page for {normalized_symbol}")
            return None

        labels = [
            "Dividend Yield",
            "Annual Dividend",
            "Ex-Dividend Date",
            "Payout Frequency",
            "Payout Ratio",
            "Dividend Growth",
        ]

        # The summary cards are rendered in a grid; select text and match labels
        info_cards: List[str] = []
        for div in soup.select('.grid div'):
            text = div.get_text(strip=True)
            if text:
                info_cards.append(text)

        summary: Dict[str, str] = {}
        # Map first occurrences of each label to its value
        for label in labels:
            for item in info_cards:
                if item.startswith(label):
                    summary[label] = item.replace(label, '').strip()
                    break

        if not summary:
            logger.warning(f"No dividend summary parsed for {normalized_symbol}")
            return None

        df = pd.DataFrame([summary])
        df = beautify_dataframe(df, normalized_symbol)

        if format == 'json':
            return to_json(df)
        return df

    except Exception as e:
        logger.error(f"Error fetching dividend summary for {symbol}: {e}")
        return None


def get_dividend_history(symbol: str, format: str = 'dataframe') -> Optional[Union[pd.DataFrame, Dict[str, Any]]]:
    """
    Get dividend history table for a stock symbol.

    Parses the dividend history rows including ex-dividend date, cash amount,
    record date, and pay date.

    Args:
        symbol: Stock symbol (e.g., 'OGDC')
        format: Output format - 'dataframe' or 'json'

    Returns:
        DataFrame of dividend history or JSON list, None if failed
    """
    try:
        normalized_symbol = validate_symbol(symbol)
        logger.info(f"Fetching dividend history for {normalized_symbol}")

        url = f"https://stockanalysis.com/quote/psx/{normalized_symbol}/dividend/"
        soup = get_html(url)
        if not soup:
            logger.error(f"Failed to fetch dividend page for {normalized_symbol}")
            return None

        headers = ["Ex-Dividend Date", "Cash Amount", "Record Date", "Pay Date"]

        rows: List[List[str]] = []
        table = soup.select_one('table')
        if table:
            for tr in table.select('tbody tr'):
                cells = [td.get_text(strip=True) for td in tr.select('td')]
                if cells:
                    rows.append(cells)

        if not rows:
            logger.warning(f"No dividend history found for {normalized_symbol}")
            return None

        df = pd.DataFrame(rows, columns=headers[:len(rows[0])])
        df = beautify_dataframe(df, normalized_symbol)

        if format == 'json':
            return to_json(df)
        return df

    except Exception as e:
        logger.error(f"Error fetching dividend history for {symbol}: {e}")
        return None


__all__ = [
    'get_dividend_info',
    'get_dividend_history',
]


