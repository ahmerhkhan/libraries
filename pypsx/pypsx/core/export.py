"""
Data export utilities for PyPSX.

Provides helpers to save pandas DataFrames to CSV/JSON/Parquet formats
with sensible defaults.
"""

from __future__ import annotations

import os
from typing import Optional

import pandas as pd


def _ensure_parent(path: str) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)


def save_dataframe(df: pd.DataFrame, path: str, format: str = "csv") -> str:
    """
    Save DataFrame to disk in the requested format.

    Args:
        df: pandas DataFrame to save
        path: output file path
        format: 'csv' | 'json' | 'parquet'

    Returns:
        The absolute file path of the saved file
    """
    if df is None or df.empty:
        raise ValueError("No data to save (empty DataFrame)")

    fmt = (format or "csv").lower()
    _ensure_parent(path)

    if fmt == "csv":
        df.to_csv(path, index=True)
    elif fmt == "json":
        # Orient records to ease downstream tool ingestion
        df.to_json(path, orient="records", date_format="iso")
    elif fmt == "parquet":
        try:
            df.to_parquet(path, index=True)
        except Exception as e:
            raise RuntimeError("Parquet export requires 'pyarrow' or 'fastparquet'") from e
    else:
        raise ValueError(f"Unsupported format: {format}")

    return os.path.abspath(path)


