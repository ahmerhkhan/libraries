"""
Dynamic strategy loading utilities.

Supports loading strategies from:
- Built-in strategy names (e.g., 'sma_momentum')
- File paths (e.g., 'user_strategies/my_strategy.py')
- Class instances
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

# Import trader_core strategies - try relative import first (package install), then fallback
try:
    from .trader_core.strategies import (
        BaseStrategy,
        BollingerMeanReversionStrategy,
        DualSMAMomentumStrategy,
        MACDCrossoverStrategy,
        RSIMomentumStrategy,
        SMAMomentumStrategy,
        VWAPReversionStrategy,
    )
    from .trader_core.strategies.base import BaseStrategy as InternalBaseStrategy
except ImportError:
    # Fallback: try absolute import (for development/legacy)
    try:
        from trader_core.strategies import (
            BaseStrategy,
            BollingerMeanReversionStrategy,
            DualSMAMomentumStrategy,
            MACDCrossoverStrategy,
            RSIMomentumStrategy,
            SMAMomentumStrategy,
            VWAPReversionStrategy,
        )
        from trader_core.strategies.base import BaseStrategy as InternalBaseStrategy
    except ImportError:
        # Last resort: try adding parent to path
        import os
        parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if parent_dir not in sys.path:
            sys.path.insert(0, parent_dir)
        from trader_core.strategies import (
            BollingerMeanReversionStrategy,
            DualSMAMomentumStrategy,
            MACDCrossoverStrategy,
            RSIMomentumStrategy,
            SMAMomentumStrategy,
            VWAPReversionStrategy,
        )
        from trader_core.strategies.base import BaseStrategy as InternalBaseStrategy

from .strategy import Strategy


# Built-in strategy registry
BUILTIN_STRATEGIES: Dict[str, type] = {
    'sma_momentum': SMAMomentumStrategy,
    'dual_sma_momentum': DualSMAMomentumStrategy,
    'rsi_momentum': RSIMomentumStrategy,
    'macd_crossover': MACDCrossoverStrategy,
    'bollinger_mean_reversion': BollingerMeanReversionStrategy,
    'vwap_reversion': VWAPReversionStrategy,
}


def load_strategy(
    strategy_spec: Union[str, Strategy, InternalBaseStrategy],
    symbols: Optional[List[str]] = None,
    **kwargs: Any,
) -> Union[Strategy, InternalBaseStrategy]:
    """
    Load strategy from various formats.
    
    Args:
        strategy_spec: Strategy name, file path, class, or instance
        symbols: List of symbols (for Strategy class instantiation)
        **kwargs: Additional arguments for strategy instantiation
    
    Returns:
        Strategy instance
    
    Examples:
        # Built-in strategy
        strategy = load_strategy('sma_momentum', ma_period=20)
        
        # From file
        strategy = load_strategy('user_strategies/my_strategy.py')
        
        # From class
        strategy = load_strategy(MyStrategy, symbols=['OGDC'])
    """
    # If already an instance, return it
    if isinstance(strategy_spec, (Strategy, InternalBaseStrategy)):
        return strategy_spec
    
    # If it's a class, instantiate it
    if isinstance(strategy_spec, type):
        if issubclass(strategy_spec, Strategy):
            return strategy_spec(symbols=symbols or [], **kwargs)
        elif issubclass(strategy_spec, InternalBaseStrategy):
            return strategy_spec(**kwargs)
        else:
            raise ValueError("Strategy class must inherit from Strategy or BaseStrategy")
    
    # If it's a string, try to load it
    if isinstance(strategy_spec, str):
        # Check if it's a built-in strategy
        if strategy_spec.lower() in BUILTIN_STRATEGIES:
            strategy_class = BUILTIN_STRATEGIES[strategy_spec.lower()]
            return strategy_class(**kwargs)
        
        # Check if it's a file path
        strategy_path = Path(strategy_spec)
        if strategy_path.exists() and strategy_path.suffix == '.py':
            return load_strategy_from_file(strategy_path, symbols=symbols, **kwargs)
        
        # Try as module path (e.g., 'user_strategies.my_strategy.MyStrategy')
        if '.' in strategy_spec:
            return load_strategy_from_module(strategy_spec, symbols=symbols, **kwargs)
        
        raise ValueError(
            f"Strategy '{strategy_spec}' not found. "
            f"Available built-in strategies: {list(BUILTIN_STRATEGIES.keys())}"
        )
    
    raise ValueError(f"Invalid strategy specification: {type(strategy_spec)}")


def load_strategy_from_file(
    file_path: Path,
    symbols: Optional[List[str]] = None,
    class_name: Optional[str] = None,
    **kwargs: Any,
) -> Union[Strategy, InternalBaseStrategy]:
    """
    Load strategy from a Python file.
    
    Args:
        file_path: Path to Python file
        symbols: List of symbols (for Strategy class)
        class_name: Name of strategy class (if None, auto-detect)
        **kwargs: Additional arguments for strategy instantiation
    
    Returns:
        Strategy instance
    """
    file_path = Path(file_path).resolve()
    
    if not file_path.exists():
        raise FileNotFoundError(f"Strategy file not found: {file_path}")
    
    # Load module
    spec = importlib.util.spec_from_file_location("strategy_module", file_path)
    if spec is None or spec.loader is None:
        raise ValueError(f"Could not load strategy from {file_path}")
    
    module = importlib.util.module_from_spec(spec)
    sys.modules["strategy_module"] = module
    spec.loader.exec_module(module)
    
    # Find strategy class
    if class_name:
        if not hasattr(module, class_name):
            raise ValueError(f"Class '{class_name}' not found in {file_path}")
        strategy_class = getattr(module, class_name)
    else:
        # Auto-detect: find class that inherits from Strategy or BaseStrategy
        strategy_class = None
        for name in dir(module):
            obj = getattr(module, name)
            if (isinstance(obj, type) and
                (issubclass(obj, Strategy) or issubclass(obj, InternalBaseStrategy)) and
                obj not in (Strategy, InternalBaseStrategy)):
                if strategy_class is not None:
                    raise ValueError(
                        f"Multiple strategy classes found in {file_path}. "
                        f"Specify class_name parameter."
                    )
                strategy_class = obj
        
        if strategy_class is None:
            raise ValueError(
                f"No strategy class found in {file_path}. "
                f"Define a class that inherits from Strategy or BaseStrategy."
            )
    
    # Instantiate
    if issubclass(strategy_class, Strategy):
        return strategy_class(symbols=symbols or [], **kwargs)
    else:
        return strategy_class(**kwargs)


def load_strategy_from_module(
    module_path: str,
    symbols: Optional[List[str]] = None,
    **kwargs: Any,
) -> Union[Strategy, InternalBaseStrategy]:
    """
    Load strategy from module path (e.g., 'user_strategies.my_strategy.MyStrategy').
    
    Args:
        module_path: Dot-separated module path
        symbols: List of symbols (for Strategy class)
        **kwargs: Additional arguments for strategy instantiation
    
    Returns:
        Strategy instance
    """
    parts = module_path.split('.')
    if len(parts) < 2:
        raise ValueError(f"Invalid module path: {module_path}")
    
    class_name = parts[-1]
    module_name = '.'.join(parts[:-1])
    
    module = importlib.import_module(module_name)
    strategy_class = getattr(module, class_name)
    
    if issubclass(strategy_class, Strategy):
        return strategy_class(symbols=symbols or [], **kwargs)
    else:
        return strategy_class(**kwargs)


def register_strategy(name: str, strategy_class: type) -> None:
    """
    Register a custom strategy for reuse.
    
    Args:
        name: Strategy name
        strategy_class: Strategy class
    """
    if not isinstance(strategy_class, type):
        raise ValueError("strategy_class must be a class")
    
    if not (issubclass(strategy_class, Strategy) or issubclass(strategy_class, InternalBaseStrategy)):
        raise ValueError("strategy_class must inherit from Strategy or BaseStrategy")
    
    BUILTIN_STRATEGIES[name.lower()] = strategy_class


def list_strategies() -> List[str]:
    """List all available built-in strategies."""
    return list(BUILTIN_STRATEGIES.keys())


__all__ = [
    "load_strategy",
    "load_strategy_from_file",
    "load_strategy_from_module",
    "register_strategy",
    "list_strategies",
    "BUILTIN_STRATEGIES",
]

