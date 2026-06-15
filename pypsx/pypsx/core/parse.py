"""
Common parsing utilities for PyPSX library.

Provides reusable functions for cleaning and converting data from PSX endpoints.
"""

import re
import json
from typing import Any, Optional, Union, List, Dict
from io import StringIO
import pandas as pd
from bs4 import BeautifulSoup, Tag
from loguru import logger


def clean_text(text: str) -> Optional[str]:
    """
    Clean text by stripping whitespace and handling empty/dash values.
    
    Args:
        text: Raw text string
        
    Returns:
        Cleaned text or None if empty/dash
    """
    if not text:
        return None
    
    cleaned = text.strip()
    if cleaned == '' or cleaned == '-':
        return None
    
    return cleaned


def parse_number(value: str) -> Optional[float]:
    """
    Convert string with commas to float.
    
    Args:
        value: String that may contain numbers with commas
        
    Returns:
        Float value or None if invalid
    """
    if not value:
        return None
    
    cleaned = clean_text(value)
    if not cleaned:
        return None
    
    # Remove commas and try to convert
    try:
        return float(cleaned.replace(',', ''))
    except ValueError:
        return None


def parse_percentage(value: str) -> Optional[float]:
    """
    Parse percentage string to float.
    
    Args:
        value: String containing percentage (e.g., "1.15%")
        
    Returns:
        Float value or None if invalid
    """
    if not value:
        return None
    
    cleaned = clean_text(value)
    if not cleaned:
        return None
    
    # Remove % symbol and convert
    if '%' in cleaned:
        try:
            return float(cleaned.replace('%', ''))
        except ValueError:
            return None
    
    return None


def parse_range(value: str) -> Optional[tuple]:
    """
    Parse range string to tuple of floats.
    
    Args:
        value: String containing range (e.g., "82 - 114")
        
    Returns:
        Tuple of (min, max) or None if invalid
    """
    if not value:
        return None
    
    cleaned = clean_text(value)
    if not cleaned:
        return None
    
    # Look for range pattern like "82 - 114" or "82-114"
    range_pattern = r'(\d+(?:,\d+)*(?:\.\d+)?)\s*-\s*(\d+(?:,\d+)*(?:\.\d+)?)'
    match = re.search(range_pattern, cleaned)
    
    if match:
        try:
            min_val = float(match.group(1).replace(',', ''))
            max_val = float(match.group(2).replace(',', ''))
            return (min_val, max_val)
        except ValueError:
            return None
    
    return None


def extract_table_data(soup: BeautifulSoup, table_selector: str = None) -> Optional[pd.DataFrame]:
    """
    Extract table data from BeautifulSoup object.
    
    Args:
        soup: BeautifulSoup object
        table_selector: CSS selector for table (optional)
        
    Returns:
        DataFrame with table data or None if not found
    """
    try:
        if table_selector:
            table = soup.select_one(table_selector)
        else:
            table = soup.find('table')
        
        if not table:
            return None
        
        # Convert table to DataFrame
        df = pd.read_html(StringIO(str(table)))[0]
        return df
        
    except Exception as e:
        logger.error(f"Error extracting table data: {e}")
        return None


def extract_stats_items(soup: BeautifulSoup, panel_selector: str = '.tabs__panel[data-name="REG"]') -> Dict[str, Any]:
    """
    Extract stats items from PSX company page.
    
    Args:
        soup: BeautifulSoup object
        panel_selector: CSS selector for stats panel
        
    Returns:
        Dictionary of stats items
    """
    stats = {}
    
    try:
        panel = soup.select_one(panel_selector)
        if not panel:
            return stats
        
        for item in panel.select('.stats_item'):
            label_elem = item.select_one('.stats_label')
            value_elem = item.select_one('.stats_value')
            
            if label_elem and value_elem:
                label = clean_text(label_elem.get_text())
                value = clean_text(value_elem.get_text())
                
                if label and value:
                    # Clean and convert value based on content
                    cleaned_value = _clean_value_by_type(label, value)
                    if cleaned_value is not None:
                        stats[label] = cleaned_value
        
        return stats
        
    except Exception as e:
        logger.error(f"Error extracting stats items: {e}")
        return {}


def _clean_value_by_type(label: str, value: str) -> Any:
    """
    Clean value based on its label type.
    
    Args:
        label: Field label
        value: Raw value string
        
    Returns:
        Cleaned value of appropriate type
    """
    # Try percentage first
    if '%' in value:
        return parse_percentage(value)
    
    # Try range
    if ' - ' in value or '-' in value:
        return parse_range(value)
    
    # Try number
    if any(char.isdigit() for char in value):
        return parse_number(value)
    
    # Return as string
    return clean_text(value)


 


def extract_json_data(response_text: str) -> Optional[Dict[str, Any]]:
    """
    Extract JSON data from response text.
    
    Args:
        response_text: Raw response text
        
    Returns:
        JSON data as dict or None if invalid
    """
    try:
        return json.loads(response_text)
    except json.JSONDecodeError:
        return None
