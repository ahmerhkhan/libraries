# PyPSX SDK

API-first trading infrastructure for the Pakistan Stock Exchange.

## Installation

```bash
pip install pytrader
```

## Quick Start

Start with paper trading. It is the safety-first way to test your strategy, validate your order flow, and watch your dashboard update in real time before risking real capital.

```python
import os
from dotenv import load_dotenv
from pytrader import TradingClient

load_dotenv()

client = TradingClient(
    api_key=os.getenv("PYPSX_API_KEY_ID"),
    secret_key=os.getenv("PYPSX_API_SECRET_KEY"),
    paper=True,
)

account = client.get_account()
print(f"Connected! Current Balance: PKR {account.cash}")

order = client.place_manual_order(
    symbol="OGDC",
    side="BUY",
    quantity=10,
    order_type="MARKET",
)

print("Submitted:", order["order_id"], order["status"])
```

You can also load keys directly from environment variables:

```python
from pytrader import TradingClient

client = TradingClient.from_env(paper=True)
```

### Your First Trade

**Step 1:** Generate a paper key in the PyPSX dashboard.  
**Step 2:** Copy the script above into `my_bot.py`.  
**Step 3:** Set your own `PYPSX_API_KEY_ID` and `PYPSX_API_SECRET_KEY` in `.env`.  
**Step 4:** Run `python my_bot.py` while the market is open.  
**Step 5:** Watch orders, fills, and positions appear in the dashboard automatically.

## The Power of PyPSX

PyPSX gives algorithmic traders a clean Python interface for the Pakistan Stock Exchange without exposing them to exchange plumbing.

### Paper And Live Modes

The SDK automatically routes traffic based on one flag:

- `paper=True` sends requests to the paper trading environment at `https://paper-api.pypsx.pk`
- `paper=False` sends requests to the live trading environment at `https://api.pypsx.pk`

This keeps your code identical across testing and production. Change the credentials, switch the flag, and keep your trading logic the same.

### Real-Time Trading Experience

With PyPSX you can:

- Read positions, orders, and account state from Python
- Submit orders with a simple REST interface
- See fills reflected in the web dashboard without manual refresh
- Build bots around trading logic instead of exchange protocol handling

### Developer's Promise

PyPSX handles the operational complexity of PSX integration, including request authentication, endpoint routing, and exchange connectivity. You focus on signal generation, risk rules, and execution logic. We handle the FIX-side complexity behind the API.

## Authentication

### How To Get Your Keys

1. Sign in to the PyPSX dashboard.
2. Open `Settings`.
3. Select the account you want to trade.
4. Click `Generate Paper Key` or `Generate Live Key`.
5. Copy the `Public Key ID` and `Secret Key`.

### How The SDK Uses Them

Use the credentials directly in `TradingClient(...)`:

```python
from pytrader import TradingClient

client = TradingClient(
    api_key=os.getenv("PYPSX_API_KEY_ID"),
    secret_key=os.getenv("PYPSX_API_SECRET_KEY"),
    paper=True,
)
```

Under the hood, the SDK automatically sends:

```http
PYPSX-API-KEY-ID: <your-public-key-id>
PYPSX-API-SECRET-KEY: <your-secret-key>
```

If you are building against the API without the Python SDK, send those same headers yourself.

## API Reference

| Method | What it does | Returns |
| --- | --- | --- |
| `get_account_config()` | Fetches trading permissions and account-level configuration | `dict` |
| `get_portfolio_valuation()` | Returns the latest equity, cash, positions value, and pricing snapshot | `dict` |
| `get_positions()` | Returns open positions for the selected paper or live account | `list[dict]` |
| `get_orders(limit=...)` | Returns recent orders and their current state | `list[dict]` |
| `place_manual_order(...)` | Submits a market or priced order through the selected environment | `dict` |
| `get_symbols()` | Fetches available market symbols | `list[dict]` |
| `get_intraday(symbol, days=...)` | Retrieves recent intraday market data for a symbol | `list[dict]` |
| `get_historical(symbol, start=..., end=...)` | Retrieves historical bars for strategy research and analysis | `list[dict]` |
| `close()` | Closes the underlying HTTP client cleanly | `None` |

## Examples

### Paper Trading

```python
from pytrader import TradingClient

client = TradingClient(
    api_key=os.getenv("PYPSX_API_KEY_ID"),
    secret_key=os.getenv("PYPSX_API_SECRET_KEY"),
    paper=True,
)

valuation = client.get_portfolio_valuation()
positions = client.get_positions()
orders = client.get_orders(limit=25)

print("Equity:", valuation["equity"])
print("Positions:", len(positions))
print("Orders:", len(orders))
```

### Live Trading

```python
from pytrader import TradingClient

client = TradingClient(
    api_key="PK-LIVE-ABC123456789",
    secret_key="pypsx-secret-live-replace-me",
    paper=False,
)

order = client.place_manual_order(
    symbol="OGDC",
    side="BUY",
    quantity=100,
    order_type="MARKET",
)

print(order)
```

### Simple Bot Pattern

```python
from pytrader import TradingClient

SYMBOL = "OGDC"

client = TradingClient(
    api_key="PK-PAPER-123456",
    secret_key="pypsx-secret-paper-replace-me",
    paper=True,
)

positions = client.get_positions()
already_holding = any(
    position["symbol"] == SYMBOL and float(position["qty"]) > 0
    for position in positions
)

if not already_holding:
    client.place_manual_order(
        symbol=SYMBOL,
        side="BUY",
        quantity=10,
        order_type="MARKET",
    )
```

## Best Practices

- Use `.env` files or a secrets manager for credentials. Do not hardcode production keys into source control.
- Start every new strategy with `paper=True`.
- Treat paper trading as your pre-flight checklist before switching to live.
- Run execution scripts when the market is open so fills, liquidity, and dashboard feedback reflect real conditions.
- Add explicit guards in your code for position sizing, duplicate orders, and risk limits.
- Close clients cleanly with `client.close()` in longer-running scripts or services.

## Raw HTTP Example

If you are not using the SDK, this is the equivalent request format:

```bash
curl -X POST "https://paper-api.pypsx.pk/orders" \
  -H "Content-Type: application/json" \
  -H "PYPSX-API-KEY-ID: $PYPSX_API_KEY_ID" \
  -H "PYPSX-API-SECRET-KEY: $PYPSX_API_SECRET_KEY" \
  -d "{\"symbol\":\"OGDC\",\"side\":\"BUY\",\"quantity\":10,\"order_type\":\"MARKET\",\"mode\":\"PAPER\",\"commission_rate\":0.02}"
```

Set `commission_rate` only when you want to override the default fee behavior for a specific order. The value is a percentage, so `0.02` means `0.02%`.

## Additional Examples

- `examples/pytrader_client_example.py`
- `examples/example_bot.py`
