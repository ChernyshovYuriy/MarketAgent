"""
core/liquidity_filter.py
Filters tickers that don't meet minimum liquidity requirements.
"""

import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class LiquidityFilter:
    def __init__(self, config: Dict[str, Any]):
        liq = config.get("liquidity", {})
        self.min_price = liq.get("min_price_cad", 1.00)
        self.min_volume = liq.get("min_avg_daily_volume", 200_000)
        self.max_spread = liq.get("max_spread_pct", 3.0)

    def passes(self, ticker_data: Optional[Dict]) -> bool:
        """Returns True if the ticker meets all liquidity criteria."""
        if ticker_data is None:
            # Unknown ticker - allow through with penalty applied at scoring
            return True
        price = ticker_data.get("last_price", 0)
        volume = ticker_data.get("average_volume", 0)
        spread = ticker_data.get("spread_estimate", 0)

        if price < self.min_price:
            logger.debug("Filtered %s: price %.2f < %.2f",
                         ticker_data.get("ticker"), price, self.min_price)
            return False
        if volume < self.min_volume:
            logger.debug("Filtered %s: volume %d < %d",
                         ticker_data.get("ticker"), volume, self.min_volume)
            return False
        if spread > self.max_spread:
            logger.debug("Filtered %s: spread %.1f%% > %.1f%%",
                         ticker_data.get("ticker"), spread, self.max_spread)
            return False
        return True

    def liquidity_score(self, ticker_data: Optional[Dict]) -> float:
        """
        Returns a 0..1 score based on how comfortably the ticker
        exceeds the liquidity thresholds.
        """
        if ticker_data is None:
            return 0.4  # Modest score for unknowns

        price = ticker_data.get("last_price", 0)
        volume = ticker_data.get("average_volume", 0)
        spread = ticker_data.get("spread_estimate", 99)

        price_score = min(1.0, price / 10.0)          # Tops out at $10+
        volume_score = min(1.0, volume / 1_000_000)   # Tops out at 1M shares
        spread_score = max(0.0, 1.0 - (spread / self.max_spread))

        return (price_score * 0.3 + volume_score * 0.5 + spread_score * 0.2)
