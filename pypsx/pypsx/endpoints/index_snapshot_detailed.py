"""
Detailed index snapshot endpoint for PyPSX library.

Fetches comprehensive index data from PSX main page including detailed stats,
price information, and all available metrics for specific indices.
"""

import pandas as pd
from typing import Optional, Dict, Any, Union
from loguru import logger
import requests
from bs4 import BeautifulSoup

from pypsx.core.utils import beautify_dataframe
from pypsx.format.json_utils import to_json


def get_index_snapshot_detailed(index_name: str = "KSE100", format: str = 'dataframe') -> Optional[Union[pd.DataFrame, Dict[str, Any]]]:
    """
    Get detailed index snapshot data with comprehensive metrics.
    
    Fetches detailed index data from https://dps.psx.com.pk main page
    including price, change, date, and all available stats items.
    
    Args:
        index_name: Index name (e.g., "KSE100", "KMI30", "KSE30")
        format: Output format - 'dataframe' or 'json'
        
    Returns:
        DataFrame with detailed index data or JSON dict, None if failed
        
    Example:
        >>> import pypsx
        >>> df = pypsx.get_index_snapshot_detailed("KSE100")
        >>> print(df)
        
        Output (pandas DataFrame):
        | METRIC | VALUE | LOW | HIGH | CURRENT |
        |---------|-------|-----|------|---------|
        | Price | 162163.81 | 161766.61 | 163570.83 | 162163.81 |
        | Change | -1140.32 | - | - | - |
        | Date | Oct 27, 2025 | - | - | - |
        | Volume | 123456789 | - | - | - |
    """
    try:
        logger.info(f"Fetching detailed index snapshot for {index_name}")
        
        # Build URL
        url = "https://dps.psx.com.pk"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1"
        }
        
        # Fetch HTML content
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Find the specific index panel
        panel = soup.select_one(f'.tabs__panel.marketIndices__details[data-name="{index_name}"]')
        if panel is None:
            logger.error(f"No data found for index: {index_name}")
            return None
        
        # Extract detailed data
        data = _extract_index_data(panel, index_name)
        if not data:
            logger.warning(f"No data extracted for index {index_name}")
            return None
        
        # Create DataFrame
        df = _create_index_dataframe(data, index_name)
        if df is None or df.empty:
            logger.warning(f"Failed to create DataFrame for index {index_name}")
            return None
        
        # Beautify DataFrame
        df = beautify_dataframe(df)
        
        logger.info(f"Successfully fetched detailed index snapshot for {index_name}: {len(df)} metrics")
        
        # Return based on format
        if format == 'json':
            return to_json(df)
        else:
            return df
            
    except requests.exceptions.RequestException as e:
        logger.error(f"Request failed for index {index_name}: {e}")
        return None
    except Exception as e:
        logger.error(f"Error fetching detailed index snapshot for {index_name}: {e}")
        return None


def get_all_indices_snapshot_detailed(format: str = 'dataframe') -> Optional[Union[pd.DataFrame, Dict[str, Any]]]:
    """
    Get detailed snapshot data for all available indices.
    
    Args:
        format: Output format - 'dataframe' or 'json'
        
    Returns:
        DataFrame with all indices detailed data or JSON dict, None if failed
    """
    try:
        logger.info("Fetching detailed snapshot for all indices")
        
        # Common PSX indices
        indices = ["KSE100", "KMI30", "KSE30", "KSEALLSHR", "KMIALLSHR"]
        
        all_data = []
        
        for index_name in indices:
            try:
                index_data = get_index_snapshot_detailed(index_name, 'dataframe')
                if index_data is not None and not index_data.empty:
                    # Add index name to each row
                    index_data['INDEX'] = index_name
                    all_data.append(index_data)
            except Exception as e:
                logger.warning(f"Failed to get data for {index_name}: {e}")
                continue
        
        if not all_data:
            logger.warning("No detailed index data retrieved")
            return None
        
        # Combine all data
        combined_df = pd.concat(all_data, ignore_index=True)
        if 'INDEX' in combined_df.columns and 'METRIC' in combined_df.columns:
            combined_df = combined_df.set_index(['INDEX', 'METRIC'])
        else:
            logger.warning("Missing required columns for multi-index setup")
        
        logger.info(f"Successfully fetched detailed snapshot for {len(all_data)} indices")
        
        # Return based on format
        if format == 'json':
            return to_json(combined_df)
        else:
            return combined_df
            
    except Exception as e:
        logger.error(f"Error fetching detailed snapshot for all indices: {e}")
        return None


def _extract_index_data(panel, index_name: str) -> Dict[str, Any]:
    """
    Extract detailed data from index panel.
    
    Args:
        panel: BeautifulSoup panel element
        index_name: Index name
        
    Returns:
        Dictionary with extracted data
    """
    data = {"Index": index_name}
    
    try:
        # Price + Change
        price_tag = panel.select_one(".marketIndices__price")
        if price_tag:
            price_text = price_tag.get_text(" ", strip=True)
            price_parts = price_text.split(" ")
            if price_parts:
                data["Price"] = price_parts[0]
                if len(price_parts) > 1:
                    data["Change"] = " ".join(price_parts[1:])
        
        # Date Time
        dt = panel.select_one(".marketIndices__date")
        if dt:
            data["Date"] = dt.get_text(strip=True)
        
        # Stats items
        for item in panel.select(".stats_item"):
            label = item.select_one(".stats_label")
            value = item.select_one(".stats_value")
            
            if label and value:
                label_text = label.get_text(strip=True)
                value_text = value.get_text(" ", strip=True)
                data[label_text] = value_text
                
                # Check for numRange data attributes
                num_range = item.select_one(".numRange")
                if num_range:
                    for attr in ["data-low", "data-high", "data-current"]:
                        if num_range.has_attr(attr):
                            attr_name = attr.replace('data-', '')
                            data[f"{label_text} {attr_name}"] = num_range[attr]
                
                # Try to extract range data from the value text itself
                if "—" in value_text or "-" in value_text:
                    range_data = _extract_range_from_text(value_text)
                    if range_data:
                        data[f"{label_text} low"] = range_data.get('low')
                        data[f"{label_text} high"] = range_data.get('high')
                        data[f"{label_text} current"] = range_data.get('current')
        
        # Additional data extraction
        _extract_additional_data(panel, data)
        
        return data
        
    except Exception as e:
        logger.error(f"Error extracting data from panel: {e}")
        return {}


def _extract_range_from_text(text: str) -> Optional[Dict[str, Any]]:
    """
    Extract range data from text containing ranges.
    
    Args:
        text: Text containing range information
        
    Returns:
        Dictionary with low, high, current values or None if not found
    """
    try:
        import re
        
        # Remove commas and clean text
        cleaned_text = text.replace(',', '').strip()
        
        # Try different range patterns
        patterns = [
            r'(\d+(?:\.\d+)?)\s*—\s*(\d+(?:\.\d+)?)',  # "159805.34 — 163380.67"
            r'(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)',   # "159805.34 - 163380.67"
            r'(\d+(?:\.\d+)?)\s*to\s*(\d+(?:\.\d+)?)',  # "159805.34 to 163380.67"
        ]
        
        for pattern in patterns:
            match = re.search(pattern, cleaned_text)
            if match:
                try:
                    low_val = float(match.group(1))
                    high_val = float(match.group(2))
                    
                    # Try to extract current value from the text
                    current_val = None
                    # Look for a third number that might be the current value
                    numbers = re.findall(r'\d+(?:\.\d+)?', cleaned_text)
                    if len(numbers) >= 3:
                        try:
                            current_val = float(numbers[2])
                        except (ValueError, IndexError):
                            pass
                    
                    return {
                        'low': low_val,
                        'high': high_val,
                        'current': current_val
                    }
                except (ValueError, IndexError):
                    continue
        
        return None
        
    except Exception as e:
        logger.warning(f"Error extracting range from text '{text}': {e}")
        return None


def _extract_additional_data(panel, data: Dict[str, Any]) -> None:
    """
    Extract additional data from the panel.
    
    Args:
        panel: BeautifulSoup panel element
        data: Data dictionary to update
    """
    try:
        # Look for any additional metrics or data points
        for element in panel.select(".marketIndices__metric, .index__stat, .metric__item"):
            label_elem = element.select_one(".label, .metric__label")
            value_elem = element.select_one(".value, .metric__value")
            
            if label_elem and value_elem:
                label = label_elem.get_text(strip=True)
                value = value_elem.get_text(strip=True)
                if label and value:
                    data[label] = value
        
        # Look for any tables with additional data
        tables = panel.select("table")
        for table in tables:
            rows = table.select("tr")
            for row in rows:
                cells = row.select("td")
                if len(cells) >= 2:
                    label = cells[0].get_text(strip=True)
                    value = cells[1].get_text(strip=True)
                    if label and value:
                        data[label] = value
                        
    except Exception as e:
        logger.warning(f"Error extracting additional data: {e}")


def _create_index_dataframe(data: Dict[str, Any], index_name: str) -> Optional[pd.DataFrame]:
    """
    Create DataFrame from extracted index data.
    
    Args:
        data: Extracted data dictionary
        index_name: Index name
        
    Returns:
        DataFrame with index data
    """
    try:
        if not data:
            return None
        
        # Create list of records
        records = []
        
        for key, value in data.items():
            if key == "Index":
                continue
                
            # Parse value to extract different components
            record = {
                'METRIC': key,
                'VALUE': value,
                'LOW': None,
                'HIGH': None,
                'CURRENT': None
            }
            
            # Check if this metric has range data
            for range_key in data.keys():
                if range_key.startswith(f"{key} "):
                    range_type = range_key.split(" ")[-1]
                    if range_type in ['low', 'high', 'current']:
                        record[range_type.upper()] = data[range_key]
            
            records.append(record)
        
        if not records:
            return None
        
        # Create DataFrame
        df = pd.DataFrame(records)
        df = df.set_index('METRIC')
        
        return df
        
    except Exception as e:
        logger.error(f"Error creating DataFrame: {e}")
        return None


def get_index_comparison(indices: list = None, format: str = 'dataframe') -> Optional[Union[pd.DataFrame, Dict[str, Any]]]:
    """
    Get comparison data for multiple indices.
    
    Args:
        indices: List of indices to compare (default: ["KSE100", "KMI30", "KSE30"])
        format: Output format - 'dataframe' or 'json'
        
    Returns:
        DataFrame with comparison data or JSON dict, None if failed
    """
    try:
        if indices is None:
            indices = ["KSE100", "KMI30", "KSE30"]
        
        logger.info(f"Getting comparison data for indices: {indices}")
        
        comparison_data = []
        
        for index_name in indices:
            try:
                index_data = get_index_snapshot_detailed(index_name, 'dataframe')
                if index_data is not None and not index_data.empty:
                    # Get key metrics
                    metrics = {}
                    for metric in index_data.index:
                        metrics[metric] = index_data.loc[metric, 'VALUE']
                    
                    metrics['INDEX'] = index_name
                    comparison_data.append(metrics)
                    
            except Exception as e:
                logger.warning(f"Failed to get comparison data for {index_name}: {e}")
                continue
        
        if not comparison_data:
            logger.warning("No comparison data retrieved")
            return None
        
        # Create comparison DataFrame
        df = pd.DataFrame(comparison_data)
        df = df.set_index('INDEX')
        
        logger.info(f"Successfully created comparison for {len(df)} indices")
        
        # Return based on format
        if format == 'json':
            return to_json(df)
        else:
            return df
            
    except Exception as e:
        logger.error(f"Error creating index comparison: {e}")
        return None
