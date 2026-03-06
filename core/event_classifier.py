"""
core/event_classifier.py
Classifies news events into typed catalysts with associated base scores.
"""

import logging
from typing import Tuple, List, Dict

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Keyword tables
# ---------------------------------------------------------------------------

POSITIVE_CATALYSTS: List[Tuple[str, str, float, List[str]]] = [
    # (label, event_type, base_score, keywords)
    ("Earnings Beat",
     "earnings_beat", 0.85,
     ["beat", "beats", "exceeds", "exceeded", "ahead of", "surpass",
      "record earnings", "record revenue", "record profit",
      "quarterly results", "q1 results", "q2 results", "q3 results",
      "q4 results", "annual results", "strong quarter"]),

    ("Guidance Increase",
     "guidance_increase", 0.80,
     ["raises guidance", "increased guidance", "raises outlook",
      "increased outlook", "upgrades guidance", "raises forecast",
      "positive outlook", "improved guidance", "upward revision"]),

    ("Major Contract",
     "major_contract", 0.75,
     ["major contract", "significant contract", "awarded contract",
      "contract win", "signed agreement", "strategic agreement",
      "multi-year contract", "supply agreement", "off-take agreement",
      "long-term agreement", "framework agreement"]),

    ("Strategic Partnership",
     "strategic_partnership", 0.70,
     ["strategic partnership", "joint venture", "collaboration agreement",
      "memorandum of understanding", "mou signed", "partnership agreement",
      "alliance", "co-development"]),

    ("Acquisition",
     "acquisition", 0.72,
     ["acquires", "acquisition of", "takeover", "merger", "merges",
      "business combination", "arrangement agreement", "to be acquired",
      "friendly takeover", "definitive agreement to acquire"]),

    ("Asset Sale",
     "asset_sale", 0.65,
     ["asset sale", "divests", "divestiture", "sells assets",
      "monetizes", "strategic sale", "disposes"]),

    ("Production Milestone",
     "production_milestone", 0.68,
     ["production milestone", "first production", "first oil",
      "first gold pour", "commercial production", "production record",
      "increases production", "production increase", "hits production",
      "construction complete", "commissioning"]),

    ("Regulatory Approval",
     "regulatory_approval", 0.78,
     ["health canada approval", "fda approval", "regulatory approval",
      "approved by", "receives approval", "receives clearance",
      "nds approved", "nds filing", "clinical approval",
      "environmental assessment approved"]),

    ("Positive Drilling Results",
     "drilling_results", 0.73,
     ["drill results", "drilling results", "positive drill",
      "high-grade intercept", "mineralisation", "mineralization",
      "significant intercept", "resource estimate", "maiden resource",
      "resource upgrade", "inferred resource"]),

    ("Analyst Upgrade",
     "analyst_upgrade", 0.65,
     ["analyst upgrade", "upgrades to buy", "raises target",
      "increases price target", "outperform", "overweight",
      "strong buy", "initiates coverage"]),

    ("Insider Buying",
     "insider_buying", 0.60,
     ["insider buying", "insider purchased", "director buys",
      "officer buys", "purchased shares", "open market purchase",
      "management buys"]),

    ("Sector Tailwind",
     "sector_tailwind", 0.55,
     ["sector upgrade", "sector outlook", "industry growth",
      "commodity price increase", "oil price", "gold price",
      "lithium price", "copper price", "demand surge"]),
]

NEUTRAL_EVENTS: List[Tuple[str, str, float, List[str]]] = [
    ("Corporate Update",
     "corporate_update", 0.30,
     ["corporate update", "operational update", "business update",
      "quarterly update", "monthly update", "progress update"]),

    ("Conference Presentation",
     "conference_appearance", 0.25,
     ["conference", "presentation", "investor day", "agm", "annual meeting",
      "webinar", "roadshow", "investor presentation"]),

    ("Minor Partnership",
     "minor_partnership", 0.28,
     ["letter of intent", "loi", "preliminary agreement",
      "non-binding", "exploratory discussion"]),

    ("General News",
     "general_news", 0.20,
     ["announces", "reports", "provides", "updates", "appoints",
      "names", "elects", "closes"]),
]

NEGATIVE_EVENTS: List[Tuple[str, str, float, List[str]]] = [
    ("Equity Dilution",
     "equity_dilution", -0.70,
     ["private placement", "bought deal", "public offering",
      "equity offering", "share issuance", "issues shares",
      "dilution", "financing announced", "brokered placement",
      "non-brokered placement"]),

    ("Discounted Financing",
     "discounted_financing", -0.75,
     ["discounted", "at a discount", "below market",
      "hard dollar warrants", "warrant exercise", "units at"]),

    ("Guidance Cut",
     "guidance_cut", -0.80,
     ["cuts guidance", "lowers guidance", "reduces guidance",
      "guidance cut", "lowered outlook", "reduced outlook",
      "negative outlook", "below expectations"]),

    ("Earnings Miss",
     "earnings_miss", -0.75,
     ["earnings miss", "missed expectations", "below estimates",
      "disappointing results", "quarterly loss", "wider loss",
      "lower than expected"]),

    ("Insider Selling",
     "insider_selling", -0.50,
     ["insider selling", "director sells", "officer sells",
      "sold shares", "disposed of shares"]),

    ("Bankruptcy Risk",
     "bankruptcy_risk", -0.95,
     ["bankruptcy", "insolvency", "ccaa protection",
      "creditor protection", "receivership", "default",
      "missed payment", "debt restructuring"]),

    ("Compliance Issue",
     "compliance_issue", -0.80,
     ["cease trade order", "cto", "regulatory sanction",
      "securities violation", "enforcement action",
      "compliance failure", "trading halt", "regulatory investigation"]),

    ("Going Concern",
     "going_concern", -0.90,
     ["going concern", "doubt about", "ability to continue",
      "material uncertainty", "substantial doubt"]),
]

# Promotion red-flag keywords
PROMOTION_FLAGS = [
    "this is not a solicitation", "paid advertisement",
    "sponsored content", "compensated", "promotion",
    "disclaimer: we were paid", "stock promotion",
]


class EventClassifier:
    def __init__(self):
        self._all_rules = (
                [(label, etype, score, kws, "positive")
                 for label, etype, score, kws in POSITIVE_CATALYSTS] +
                [(label, etype, score, kws, "neutral")
                 for label, etype, score, kws in NEUTRAL_EVENTS] +
                [(label, etype, score, kws, "negative")
                 for label, etype, score, kws in NEGATIVE_EVENTS]
        )

    def classify(self, headline: str, text: str = "") -> Dict:
        """
        Returns:
            event_type: str
            catalyst_score: float  (0..1 for scoring formula)
            sentiment_bias: str    (positive/neutral/negative)
            label: str             (human-readable label)
            risk_flags: list[str]
        """
        combined = (headline + " " + (text or "")).lower()
        best_score = 0.0
        best_type = "general_news"
        best_label = "General News"
        best_sentiment = "neutral"
        matched_rules = []

        for label, etype, score, kws, sentiment in self._all_rules:
            hits = [kw for kw in kws if kw.lower() in combined]
            if hits:
                matched_rules.append((abs(score), label, etype, score, sentiment))

        if matched_rules:
            matched_rules.sort(key=lambda x: x[0], reverse=True)
            _, best_label, best_type, best_score, best_sentiment = matched_rules[0]

        # Promotion check
        risk_flags = []
        for flag in PROMOTION_FLAGS:
            if flag.lower() in combined:
                risk_flags.append("promotion_flag")
                break

        # Dilution penalty flag
        if best_type in ("equity_dilution", "discounted_financing"):
            risk_flags.append("dilution")

        if best_type in ("bankruptcy_risk", "going_concern"):
            risk_flags.append("high_risk")

        # Normalize catalyst_score to 0..1
        catalyst_score = max(0.0, min(1.0, abs(best_score)))
        if best_sentiment == "negative":
            catalyst_score = 0.0  # Negative events get 0 catalyst score

        return {
            "event_type": best_type,
            "catalyst_score": catalyst_score,
            "sentiment_bias": best_sentiment,
            "label": best_label,
            "risk_flags": risk_flags,
            "raw_score": best_score,
        }
