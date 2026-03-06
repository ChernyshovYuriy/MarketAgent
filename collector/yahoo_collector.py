"""
collector/yahoo_collector.py
Collects Canadian market headlines from Yahoo Finance RSS.
"""

import logging
from typing import List, Dict, Any

from .base_collector import BaseCollector

logger = logging.getLogger(__name__)


class YahooCollector(BaseCollector):
    SOURCE_NAME = "Yahoo"
    RELIABILITY = 0.6

    # Yahoo Finance RSS feeds for Canadian market
    FEEDS = [
        "https://finance.yahoo.com/rss/headline?s=^GSPTSE",  # TSX index
        "https://ca.finance.yahoo.com/rss/topfinstories",  # CA finance
        "https://finance.yahoo.com/rss/2.0/headline?s=%5EGSPTSE",
    ]

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        extra = config.get("rss_url")
        if extra and extra not in self.FEEDS:
            self.FEEDS = [extra] + self.FEEDS

    def collect(self) -> List[Dict[str, Any]]:
        items = []
        for feed_url in self.FEEDS:
            try:
                entries = self._parse_rss(feed_url)
                items.extend(entries)
                logger.debug("[Yahoo] Collected %d items from %s",
                             len(entries), feed_url)
            except Exception as exc:
                logger.error("[Yahoo] Error collecting from %s: %s", feed_url, exc)
        # Deduplicate by URL within this batch
        seen = set()
        unique = []
        for item in items:
            key = item.get("article_url", "")
            if key not in seen:
                seen.add(key)
                unique.append(item)
        logger.info("[Yahoo] Collected %d unique items", len(unique))
        return unique
