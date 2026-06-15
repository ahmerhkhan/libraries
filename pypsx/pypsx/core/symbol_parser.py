"""
Symbol parsing utility for PyPSX library.

Extracts clean symbols from PSX HTML tables by parsing hyperlinks,
following the pattern described in CHANGE.md.

The clean symbol is always in the hyperlink, not in the text that may contain tags.
"""

from typing import Dict, List, Optional
from bs4 import BeautifulSoup, Tag, NavigableString
import re


def parse_symbol_from_td(td_element: Tag) -> Dict[str, any]:
    """
    Extract clean symbol and tags from a table cell (td) element.
    
    According to CHANGE.md, the best extraction methods are:
    1. Parent <td> tag: Get the value of the `data-search` attribute
    2. Hyperlink <a> tag: Get the text content inside the <a> tag
    3. Hyperlink href: Extract the last part of the href path
    
    Args:
        td_element: BeautifulSoup Tag element representing a <td> cell
        
    Returns:
        Dictionary with:
        - 'symbol': Clean symbol string (e.g., 'JATM', 'OGDC')
        - 'tags': List of tag strings (e.g., ['XD'], ['NC'], ['DC'], or [])
        
    Example:
        >>> from bs4 import BeautifulSoup
        >>> html = '<td data-search="JATM"><a href="/company/JATM"><strong>JATM</strong></a><div class="tag">NC</div></td>'
        >>> soup = BeautifulSoup(html, 'html.parser')
        >>> td = soup.find('td')
        >>> result = parse_symbol_from_td(td)
        >>> print(result)
        {'symbol': 'JATM', 'tags': ['NC']}
    """
    if not isinstance(td_element, Tag):
        return {'symbol': '', 'tags': []}
    
    symbol = ''
    tags = []
    
    # Method 1: Try data-search attribute (most reliable, usually clean)
    if td_element.get('data-search'):
        symbol = str(td_element['data-search']).strip().upper()
    
    # Method 2: PRIORITIZE href attribute path (symbols in href don't have suffixes)
    # This is the preferred method as symbols in hyperlinks are clean without XD/XR/NC suffixes
    if not symbol:
        symbol_link = td_element.find('a', href=True)
        if symbol_link:
            href = symbol_link.get('href', '')
            # Extract symbol from path like /company/JATM or /company/OGDC
            match = re.search(r'/company/([A-Z0-9]+)', href, re.IGNORECASE)
            if match:
                symbol = match.group(1).upper()
    
    # Method 3: Try hyperlink text content (may contain suffixes, so lower priority)
    if not symbol:
        symbol_link = td_element.find('a', class_='tbl__symbol')
        if symbol_link:
            # Get text from <strong> inside the link, or just the link text
            strong_tag = symbol_link.find('strong')
            if strong_tag:
                symbol = strong_tag.get_text(strip=True).upper()
            else:
                symbol = symbol_link.get_text(strip=True).upper()
            # Strip any suffixes that might be in the text
            symbol = re.sub(r'(XD|XR|NC|DC)$', '', symbol, flags=re.IGNORECASE).strip()
    
    # Fallback: Extract from cell text (least reliable, may have suffixes)
    if not symbol:
        cell_text = td_element.get_text(strip=True)
        # Try to extract symbol (alphanumeric, typically 2-6 chars)
        match = re.match(r'^([A-Z0-9]{2,6})', cell_text, re.IGNORECASE)
        if match:
            symbol = match.group(1).upper()
    
    # Extract tags from <div class="tag"> elements
    tag_divs = td_element.find_all('div', class_='tag')
    for tag_div in tag_divs:
        tag_text = tag_div.get_text(strip=True)
        if tag_text:
            tags.append(tag_text.upper())
    
    # Also check for tags in the text (like "XD", "NC", "DC" after symbol)
    if not tags:
        cell_text = td_element.get_text()
        # Look for common tags in the text
        tag_pattern = r'\b(XD|NC|DC|XR)\b'
        found_tags = re.findall(tag_pattern, cell_text, re.IGNORECASE)
        tags = [t.upper() for t in found_tags]
    
    return {
        'symbol': symbol,
        'tags': tags
    }


def parse_symbols_from_table(soup: BeautifulSoup, table_selector: Optional[str] = None) -> List[Dict[str, any]]:
    """
    Extract symbols and tags from all rows in a table.
    
    Args:
        soup: BeautifulSoup object containing the HTML
        table_selector: Optional CSS selector for the table (default: first table)
        
    Returns:
        List of dictionaries, each with 'symbol' and 'tags' keys
    """
    if table_selector:
        table = soup.select_one(table_selector)
    else:
        table = soup.find('table')
    
    if not table:
        return []
    
    results = []
    rows = table.find_all('tr')
    
    for row in rows[1:]:  # Skip header row
        # Find first td (symbol column)
        first_td = row.find('td')
        if first_td:
            result = parse_symbol_from_td(first_td)
            if result['symbol']:  # Only add if we found a symbol
                results.append(result)
    
    return results


def extract_symbol_from_href(href: str) -> Optional[str]:
    """
    Extract symbol from a company href path.
    
    Args:
        href: URL path like '/company/JATM' or 'https://dps.psx.com.pk/company/OGDC'
        
    Returns:
        Symbol string or None if not found
    """
    match = re.search(r'/company/([A-Z0-9]+)', href, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    return None

