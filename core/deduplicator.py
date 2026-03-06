"""
core/deduplicator.py
Removes duplicate events using URL hashing, headline hashing,
and lightweight TF-IDF cosine similarity.
"""

import re
import math
import hashlib
import logging
from collections import defaultdict
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

COSINE_THRESHOLD = 0.90


def _tokenize(text: str) -> List[str]:
    """Simple whitespace + punctuation tokenizer."""
    return re.findall(r"[a-z]{3,}", text.lower())


def _tfidf_vector(tokens: List[str]) -> Dict[str, float]:
    tf: Dict[str, int] = defaultdict(int)
    for t in tokens:
        tf[t] += 1
    n = len(tokens) or 1
    return {term: count / n for term, count in tf.items()}


def _cosine(v1: Dict[str, float], v2: Dict[str, float]) -> float:
    common = set(v1) & set(v2)
    if not common:
        return 0.0
    dot = sum(v1[t] * v2[t] for t in common)
    mag1 = math.sqrt(sum(x * x for x in v1.values()))
    mag2 = math.sqrt(sum(x * x for x in v2.values()))
    if mag1 == 0 or mag2 == 0:
        return 0.0
    return dot / (mag1 * mag2)


class Deduplicator:
    def __init__(self, db=None, cosine_threshold: float = COSINE_THRESHOLD):
        self.db = db
        self.cosine_threshold = cosine_threshold
        # In-memory caches (supplementary to DB)
        self._url_hashes: set = set()
        self._headline_hashes: set = set()
        self._recent_vectors: List[Dict[str, float]] = []
        self._max_vectors = 500  # Keep last N vectors in memory

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def is_duplicate(self, event: Dict[str, Any]) -> bool:
        """
        Returns True if this event has been seen before.
        Checks: URL hash → headline hash → cosine similarity.
        """
        url = event.get("article_url", "") or event.get("url", "")
        headline = event.get("headline", "")

        # 1. URL hash
        if url:
            uh = _hash(url)
            if self._check_hash(uh):
                logger.debug("Duplicate (URL): %s", url[:60])
                return True

        # 2. Headline hash
        if headline:
            hh = _hash(headline.lower().strip())
            if self._check_hash(hh):
                logger.debug("Duplicate (headline): %s", headline[:60])
                return True

        # 3. Semantic similarity
        if headline and self._is_semantically_duplicate(headline):
            logger.debug("Duplicate (semantic): %s", headline[:60])
            return True

        return False

    def mark_seen(self, event: Dict[str, Any]):
        """Record this event so future duplicates are caught."""
        url = event.get("article_url", "") or event.get("url", "")
        headline = event.get("headline", "")

        if url:
            uh = _hash(url)
            self._store_hash(uh, "url")
        if headline:
            hh = _hash(headline.lower().strip())
            self._store_hash(hh, "headline")
            vec = _tfidf_vector(_tokenize(headline))
            self._recent_vectors.append(vec)
            if len(self._recent_vectors) > self._max_vectors:
                self._recent_vectors.pop(0)

    def filter_batch(self, events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Filter a batch of raw events, returning only non-duplicates.
        Also deduplicates within the batch itself.
        """
        seen_in_batch: set = set()
        result = []
        for event in events:
            url = event.get("article_url", "") or event.get("url", "")
            headline = event.get("headline", "")
            batch_key = _hash(url + headline)
            if batch_key in seen_in_batch:
                continue
            if self.is_duplicate(event):
                continue
            seen_in_batch.add(batch_key)
            result.append(event)
            self.mark_seen(event)
        logger.debug("Deduplicator: %d → %d events", len(events), len(result))
        return result

    # ------------------------------------------------------------------ #
    #  Internals                                                           #
    # ------------------------------------------------------------------ #

    def _check_hash(self, h: str) -> bool:
        if h in self._url_hashes or h in self._headline_hashes:
            return True
        if self.db and self.db.has_hash(h):
            return True
        return False

    def _store_hash(self, h: str, hash_type: str):
        if hash_type == "url":
            self._url_hashes.add(h)
        else:
            self._headline_hashes.add(h)
        if self.db:
            self.db.add_hash(h, hash_type)

    def _is_semantically_duplicate(self, headline: str) -> bool:
        vec = _tfidf_vector(_tokenize(headline))
        # Require at least 4 meaningful tokens to apply semantic dedup.
        # Single/few-token vectors produce unreliable cosine scores.
        if len(vec) < 4:
            return False
        for prev_vec in self._recent_vectors[-100:]:  # Check last 100
            if len(prev_vec) < 4:
                continue
            if _cosine(vec, prev_vec) >= self.cosine_threshold:
                return True
        return False


def _hash(s: str) -> str:
    return hashlib.md5(s.encode()).hexdigest()
