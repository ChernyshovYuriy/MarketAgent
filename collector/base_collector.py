"""
collector/base_collector.py
Abstract base with retry / backoff and shared RSS parsing helpers.
"""

import time
import logging
import hashlib
import re
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

import requests
try:
    import feedparser
except ImportError:  # pragma: no cover
    feedparser = None  # type: ignore  -- installed via requirements.txt

logger = logging.getLogger(__name__)


class BaseCollector(ABC):
    SOURCE_NAME: str = "Unknown"
    RELIABILITY: float = 0.5

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.timeout = config.get("timeout_seconds", 10)
        self.retry_attempts = config.get("retry_attempts", 3)
        self.retry_backoff_base = config.get("retry_backoff_base", 2)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (compatible; CAMarketAgent/1.0; "
                "+https://github.com/ca-market-agent)"
            )
        })

    @abstractmethod
    def collect(self) -> List[Dict[str, Any]]:
        """Return a list of raw event dicts."""

    # ------------------------------------------------------------------ #
    #  HTTP helpers                                                        #
    # ------------------------------------------------------------------ #

    def _get(self, url: str, **kwargs) -> Optional[requests.Response]:
        for attempt in range(self.retry_attempts):
            try:
                resp = self.session.get(
                    url, timeout=self.timeout, **kwargs
                )
                resp.raise_for_status()
                return resp
            except requests.RequestException as exc:
                wait = self.retry_backoff_base ** attempt
                logger.warning(
                    "[%s] GET %s failed (attempt %d/%d): %s. Retrying in %ss",
                    self.SOURCE_NAME, url, attempt + 1,
                    self.retry_attempts, exc, wait
                )
                if attempt < self.retry_attempts - 1:
                    time.sleep(wait)
        logger.error("[%s] All retries exhausted for %s", self.SOURCE_NAME, url)
        return None

    def _parse_rss(self, url: str) -> List[Dict]:
        """Fetch and parse an RSS feed; return list of entry dicts."""
        resp = self._get(url)
        if resp is None:
            return []
        if feedparser is None:
            raise RuntimeError("feedparser is not installed. Run: pip install feedparser")
        feed = feedparser.parse(resp.content)
        entries = []
        for entry in feed.entries:
            pub = entry.get("published_parsed") or entry.get("updated_parsed")
            if pub:
                ts = datetime(*pub[:6], tzinfo=timezone.utc).isoformat()
            else:
                ts = datetime.now(timezone.utc).isoformat()
            entries.append({
                "headline": entry.get("title", "").strip(),
                "publication_time": ts,
                "source": self.SOURCE_NAME,
                "article_url": entry.get("link", ""),
                "article_text": self._strip_html(
                    entry.get("summary", "") or ""
                ),
                "source_reliability": self.RELIABILITY,
            })
        return entries

    # ------------------------------------------------------------------ #
    #  Utility                                                             #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _strip_html(text: str) -> str:
        return re.sub(r"<[^>]+>", " ", text).strip()

    @staticmethod
    def make_id(url: str, headline: str) -> str:
        raw = f"{url}||{headline}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    @staticmethod
    def headline_hash(headline: str) -> str:
        return hashlib.md5(headline.lower().strip().encode()).hexdigest()

    @staticmethod
    def url_hash(url: str) -> str:
        return hashlib.md5(url.strip().encode()).hexdigest()
