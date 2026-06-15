# PyPSX Endpoints Reference

This document describes the data sources and field mappings for the PyPSX endpoints.

## Data Sources

### 1. Market Watch (`/market-watch`)
Primary source for live trading data.
- OHLCV data
- Current price & volume
- Price changes
- Index memberships

Fields:
- `CURRENT`: Current trading price
- `OPEN`, `HIGH`, `LOW`: Daily OHLC prices
- `CHANGE`, `%CHANGE`: Price change values
- `VOLUME`: Trading volume
- `INDICES`: List of indices the stock belongs to
- `SECTOR`: Business sector classification

### 2. Compliant Listings (`/trading-board/REG/main`)
Canonical source for official PSX listings.
- Base symbol truth
- Company information
- Market categorization

Fields:
- `SYMBOL`: Official PSX symbol
- `NAME`: Company name
- `SECTOR`: Business sector
- `SHARES`: Total shares
- `FREE_FLOAT`: Free float shares
- `CLEARING_TYPE`: Settlement type
- `MARKET_CAP_CATEGORY`: Market cap classification

### 3. Performers (`/performers`)
Source for top gainers, losers, and most active stocks.
- Limited to top N stocks in each category
- Live performance metrics

Fields:
- `SYMBOL`: Stock symbol
- `PRICE`: Current price
- `CHANGE`: Absolute price change
- `%CHANGE`: Percentage price change
- `VOLUME`: Trading volume

### 4. Indices (`/indices/[CODE]`)
Source for index data and constituents.
- Index values and changes
- Member stocks and weights

Fields:
- Index Level Data:
  * `CURRENT`: Current index value
  * `CHANGE`, `%CHANGE`: Index changes
  * `VOLUME`: Aggregate volume

- Constituent Data:
  * `SYMBOL`: Stock symbol
  * `NAME`: Company name
  * `WEIGHT`: Index weight percentage
  * `IDX_POINTS`: Points contribution

## Field Sources and Defaults

### Required Fields
These fields must always be present:
- `SYMBOL`: Base symbol from Compliant Listings
- `NAME`: Company name from Compliant Listings
- `SECTOR`: Business sector from Compliant Listings

### Optional Numeric Fields
Default to 0 if not available:
- `CURRENT`: Current price (Market Watch)
- `CHANGE`: Price change (Market Watch)
- `%CHANGE`: Percentage change (Market Watch)
- `VOLUME`: Trading volume (Market Watch)
- `FREE_FLOAT`: Free float shares (Compliant Listings)
- `SHARES`: Total shares (Compliant Listings)

### Optional String Fields
Default to empty string if not available:
- `INDICES`: Index memberships (Market Watch)
- `CLEARING_TYPE`: Settlement type (Compliant Listings)
- `MARKET_CAP_CATEGORY`: Market cap class (Compliant Listings)
- `COMPLIANCE_STATUS`: Compliance status

## Important Notes

1. **Price Data Availability**
   - Prices (`CURRENT`, `OPEN`, etc.) may be 0 when market is closed
   - Some stocks may not have recent trades
   - Always check `TRADING_STATUS` for context

2. **Index Memberships**
   - Not all stocks belong to indices
   - `INDICES` field may be empty string
   - Index membership comes from Market Watch data

3. **Corporate Actions**
   - Symbols may have suffixes (XD, XR, etc.)
   - Use `normalize_symbol()` to get base symbol
   - Check `MARKET_WATCH_ALIASES` for variants

4. **Data Consistency**
   - Compliant Listings is source of truth for symbols
   - Market Watch provides live trading data
   - Performers data is subset for top movers
   - Index data shows point-in-time membership