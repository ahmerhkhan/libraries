"""Collection of built-in strategies for the PyTrader SDK."""

from .base import BaseStrategy
from .mean_reversion import (
    BollingerMeanReversionStrategy,
    VWAPReversionStrategy,
)
from .momentum import (
    DualSMAMomentumStrategy,
    MACDCrossoverStrategy,
    RSIMomentumStrategy,
    SMAMomentumStrategy,
)
from .testbots import (
    BuyingOnDownStrategy,
    BuyingOnUpStrategy,
    MLLayerMomentumStrategy,
    TestBotsMomentumStrategy,
)

__all__ = [
    "BaseStrategy",
    "SMAMomentumStrategy",
    "DualSMAMomentumStrategy",
    "RSIMomentumStrategy",
    "MACDCrossoverStrategy",
    "BollingerMeanReversionStrategy",
    "VWAPReversionStrategy",
    "TestBotsMomentumStrategy",
    "BuyingOnUpStrategy",
    "BuyingOnDownStrategy",
    "MLLayerMomentumStrategy",
]

