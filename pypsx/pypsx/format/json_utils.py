"""
JSON conversion utilities for PyPSX library.

Provides functions to convert DataFrames to clean JSON format.
"""

import pandas as pd
import json
from datetime import datetime, date
from typing import Union, Dict, Any, Optional
from loguru import logger


def to_json(df: pd.DataFrame, orient: str = 'records') -> Union[Dict[str, Any], list]:
    """
    Convert DataFrame to clean JSON format.
    
    Args:
        df: DataFrame to convert
        orient: JSON orientation ('records', 'index', 'values', 'table')
        
    Returns:
        JSON data as dict or list
    """
    if df.empty:
        return [] if orient == 'records' else {}
    
    try:
        # Handle datetime serialization
        df_copy = df.copy()
        
        # Convert datetime columns to ISO format strings
        for col in df_copy.columns:
            if pd.api.types.is_datetime64_any_dtype(df_copy[col]):
                df_copy[col] = df_copy[col].dt.strftime('%Y-%m-%d %H:%M:%S')
        
        # Convert datetime index to ISO format strings
        if isinstance(df_copy.index, pd.DatetimeIndex):
            df_copy.index = df_copy.index.strftime('%Y-%m-%d %H:%M:%S')
        
        # Convert to JSON
        json_data = df_copy.to_json(orient=orient, date_format='iso')
        
        # Parse JSON string to return proper Python objects
        return json.loads(json_data)
        
    except Exception as e:
        logger.error(f"Error converting DataFrame to JSON: {e}")
        return [] if orient == 'records' else {}


def to_json_string(df: pd.DataFrame, orient: str = 'records', indent: int = 2) -> str:
    """
    Convert DataFrame to JSON string.
    
    Args:
        df: DataFrame to convert
        orient: JSON orientation
        indent: JSON indentation
        
    Returns:
        JSON string
    """
    try:
        json_data = to_json(df, orient)
        return json.dumps(json_data, indent=indent, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error converting DataFrame to JSON string: {e}")
        return "{}"


def format_json_for_api(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Format DataFrame as API response JSON.
    
    Args:
        df: DataFrame to format
        
    Returns:
        Formatted JSON response
    """
    try:
        # Convert to records format
        records = to_json(df, orient='records')
        
        # Create API response structure
        response = {
            'status': 'success',
            'data': records,
            'count': len(records),
            'timestamp': datetime.now().isoformat()
        }
        
        # Add metadata if DataFrame has attributes
        if hasattr(df, 'attrs'):
            response['metadata'] = df.attrs
        
        return response
        
    except Exception as e:
        logger.error(f"Error formatting DataFrame for API: {e}")
        return {
            'status': 'error',
            'message': str(e),
            'data': [],
            'count': 0,
            'timestamp': datetime.now().isoformat()
        }


def clean_json_data(data: Any) -> Any:
    """
    Clean JSON data by handling NaN values and other issues.
    
    Args:
        data: Data to clean
        
    Returns:
        Cleaned data
    """
    if isinstance(data, dict):
        return {k: clean_json_data(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [clean_json_data(item) for item in data]
    elif pd.isna(data):
        return None
    elif isinstance(data, (datetime, date)):
        return data.isoformat()
    else:
        return data
