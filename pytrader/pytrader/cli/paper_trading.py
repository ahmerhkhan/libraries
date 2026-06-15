from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from ..strategy_loader import BUILTIN_STRATEGIES
from ..trader import Trader


def _parse_symbols(raw: str) -> List[str]:
    parts: List[str] = []
    for token in (segment.strip().upper() for segment in raw.replace(",", " ").split()):
        if token:
            parts.append(token)
    if not parts:
        raise argparse.ArgumentTypeError("At least one symbol must be provided.")
    return parts


def _load_strategy_config(config_arg: Optional[str]) -> Dict[str, Any]:
    if not config_arg:
        return {}

    config_arg = config_arg.strip()
    path = Path(config_arg)
    try:
        if path.exists() and path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise argparse.ArgumentTypeError(f"Unable to read config file: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(f"Invalid JSON in config file: {exc}") from exc

    try:
        return json.loads(config_arg)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(f"Invalid JSON config string: {exc}") from exc


def _build_strategy(name: str, config: Dict[str, Any]):
    key = name.lower().strip()
    strategy_cls = BUILTIN_STRATEGIES.get(key)
    if not strategy_cls:
        raise SystemExit(
            f"Unknown strategy '{name}'. "
            f"Available templates: {', '.join(sorted(BUILTIN_STRATEGIES.keys()))}"
        )
    try:
        return strategy_cls(**config)
    except TypeError as exc:
        raise SystemExit(f"Invalid configuration for '{name}': {exc}") from exc


def _resolve_log_path(base: Optional[str], suffix: str, bot_id: str) -> Path:
    if base:
        path = Path(base).expanduser()
    else:
        log_dir = Path("logs") / "paper_cli"
        log_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = log_dir / f"{bot_id}-{timestamp}-{suffix}"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pytrader-paper",
        description="Local terminal-only paper trading runner for PyPSX strategies.",
    )
    parser.add_argument(
        "--strategy",
        required=True,
        help="Strategy template name (e.g., sma_momentum, dual_sma_momentum, vwap_reversion).",
        choices=sorted(BUILTIN_STRATEGIES.keys()),
    )
    parser.add_argument(
        "--symbols",
        required=True,
        help="Comma or space separated list of PSX symbols (e.g., OGDC, HBL, MEBL).",
    )
    parser.add_argument(
        "--config",
        help="Strategy configuration as JSON string or path to JSON file.",
    )
    parser.add_argument(
        "--token",
        required=True,
        help="API token for PyPSX data access (kept locally, never sent to cloud).",
    )
    parser.add_argument(
        "--capital",
        type=float,
        default=1_000_000.0,
        help="Initial virtual cash for the portfolio (default: 1,000,000).",
    )
    parser.add_argument(
        "--position-notional",
        type=float,
        default=100_000.0,
        help="Target notional allocated per trade (default: 100,000).",
    )
    parser.add_argument(
        "--cycle-minutes",
        type=int,
        default=15,
        help="Polling cycle duration in minutes (default: 15).",
    )
    parser.add_argument(
        "--max-cycles",
        type=int,
        default=None,
        help="Optional limit on cycles to run before exiting (default: run indefinitely).",
    )
    parser.add_argument(
        "--bot-id",
        help="Optional identifier used for log filenames. Defaults to strategy name.",
    )
    parser.add_argument(
        "--metrics-path",
        help="Optional path for metrics CSV output. Defaults to logs/paper_cli/<bot>_metrics.csv.",
    )
    parser.add_argument(
        "--trades-path",
        help="Optional path for trades CSV output. Defaults to logs/paper_cli/<bot>_trades.csv.",
    )
    parser.add_argument(
        "--warm-start",
        action="store_true",
        help="Replay from market open using previously saved state (explicit opt-in).",
    )
    parser.add_argument(
        "--cold-start",
        action="store_true",
        help="(Deprecated) Force cold start. Cold start is now the default.",
    )
    parser.add_argument(
        "--detailed",
        action="store_true",
        help="Enable verbose per-cycle logging in the terminal.",
    )
    parser.add_argument(
        "--log-dir",
        help="Directory for additional log artifacts (default: logs/).",
    )
    return parser


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    symbols = _parse_symbols(args.symbols)
    config = _load_strategy_config(args.config)
    strategy = _build_strategy(args.strategy, config)

    bot_id = args.bot_id or f"paper-{args.strategy}"
    metrics_path = _resolve_log_path(args.metrics_path, "metrics.csv", bot_id)
    trades_path = _resolve_log_path(args.trades_path, "trades.csv", bot_id)

    trader = Trader(
        strategy=strategy,
        symbols=symbols,
        cycle_minutes=args.cycle_minutes,
        initial_cash=args.capital,
        position_notional=args.position_notional,
        bot_id=bot_id,
    )

    warm_start = args.warm_start
    if args.cold_start:
        warm_start = False

    try:
        log_dir = Path(args.log_dir).expanduser() if args.log_dir else Path("logs")
        log_dir.mkdir(parents=True, exist_ok=True)
        trader.run_paper_trading(
            token=args.token,
            warm_start=warm_start,
            max_cycles=args.max_cycles,
            metrics_path=metrics_path,
            trades_path=trades_path,
            log_dir=log_dir,
            detailed_logs=args.detailed,
        )
        return 0
    except KeyboardInterrupt:
        print("\nPaper trading stopped by user.")
        return 0
    except Exception as exc:  # pragma: no cover - CLI guardrail
        print(f"Paper trading failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())


