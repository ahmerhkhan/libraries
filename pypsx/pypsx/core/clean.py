"""
Lightweight cleaning helpers for PyPSX.

Provide reusable functions to clean numeric and index-membership columns before
coercion. Centralizing this reduces duplication and prevents accidental
pd.to_numeric coercion on unclean strings which was producing NaNs.
"""
from typing import Any
import pandas as pd


def clean_numeric_series(series: pd.Series, is_percent: bool = False, as_int: bool = False, default=0) -> pd.Series:
    """Clean a pandas Series containing numeric-like strings.

    - converts to str
    - strips commas and whitespace
    - removes percent sign when is_percent=True
    - replaces common invalid tokens with a default
    - converts to numeric and fills missing with default

    Returns a numeric Series (float by default, int if as_int=True).
    """
    if series is None:
        return pd.Series([], dtype=int if as_int else float)

    s = series.astype(str)
    s = s.str.replace(',', '')
    s = s.str.strip()
    if is_percent:
        s = s.str.replace('%', '')

    s = s.replace({'nan': str(default), 'None': str(default), 'NaN': str(default), '': str(default)})

    if as_int:
        return pd.to_numeric(s, errors='coerce').fillna(default).astype('int64')
    else:
        return pd.to_numeric(s, errors='coerce').fillna(float(default))


def clean_indices_series(series: pd.Series) -> pd.Series:
    """Ensure INDEX/LISTED_IN-like series are strings, never NaN.

    Converts values to str and replaces common NaN tokens with empty string.
    """
    if series is None:
        return pd.Series([], dtype=object)
    s = series.astype(str)
    s = s.replace({'nan': '', 'None': '', 'NaN': '', '<NA>': ''})
    s = s.fillna('')
    return s
