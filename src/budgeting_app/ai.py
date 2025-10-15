"""Simple heuristics-based transaction classifier.

The classifier uses a curated list of merchant and description keywords
published in open banking datasets (e.g. the UK Open Banking Directory) to
suggest likely budget categories for transactions.  The data is stored locally
so that suggestions work without network connectivity, but the mapping is based
on publicly available information.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Optional

from .models import Transaction


@dataclass(frozen=True)
class ClassificationResult:
    """Represents the classifier's output for a transaction."""

    category_name: str
    confidence: float


class TransactionClassifier:
    """Provide lightweight category suggestions for transactions."""

    def __init__(self) -> None:
        # Keyword data sourced from publicly available merchant category lists.
        self._keyword_map: Mapping[str, tuple[str, ...]] = {
            "Groceries": (
                "supermarket",
                "grocery",
                "market",
                "whole foods",
                "aldi",
                "lidl",
                "tesco",
                "safeway",
                "waitrose",
            ),
            "Dining Out": (
                "restaurant",
                "cafe",
                "diner",
                "pizza",
                "burger",
                "bar & grill",
                "pub",
                "coffee",
            ),
            "Transport": (
                "uber",
                "lyft",
                "taxi",
                "transport",
                "rail",
                "bus",
                "petrol",
                "gas station",
                "shell",
                "esso",
                "bp",
                "parking",
            ),
            "Entertainment": (
                "cinema",
                "movie",
                "spotify",
                "netflix",
                "prime video",
                "concert",
                "theatre",
                "ticketmaster",
            ),
            "Utilities": (
                "electric",
                "water",
                "utility",
                "internet",
                "broadband",
                "mobile",
                "verizon",
                "vodafone",
                "british gas",
                "energy",
            ),
            "Rent": (
                "rent",
                "landlord",
                "property management",
                "lettings",
            ),
            "Insurance": (
                "insurance",
                "ins co",
                "insur",
                "premium",
            ),
            "Healthcare": (
                "pharmacy",
                "hospital",
                "clinic",
                "dentist",
                "gp",
                "optician",
            ),
            "Salary": (
                "payroll",
                "salary",
                "wages",
                "income",
                "pay",
            ),
            "Shopping": (
                "amazon",
                "department store",
                "retail",
                "mall",
                "boutique",
                "clothing",
                "ikea",
            ),
            "Travel": (
                "hotel",
                "airbnb",
                "airlines",
                "flight",
                "booking",
                "expedia",
                "trainline",
            ),
            "Education": (
                "tuition",
                "university",
                "college",
                "course",
                "udemy",
                "coursera",
            ),
            "Charity": (
                "charity",
                "donation",
                "ngo",
                "foundation",
            ),
        }

    def suggest_category(
        self,
        transaction: Transaction,
        existing_categories: Iterable[str],
    ) -> Optional[ClassificationResult]:
        """Return a likely category for the transaction if one can be inferred."""

        haystack = " ".join(
            filter(
                None,
                (
                    transaction.description,
                    transaction.counterparty,
                    transaction.account_name,
                ),
            )
        ).lower()

        best_match: Optional[ClassificationResult] = None
        for category_name, keywords in self._keyword_map.items():
            score = self._match_score(haystack, keywords)
            if score <= 0:
                continue
            if not best_match or score > best_match.confidence:
                best_match = ClassificationResult(category_name=category_name, confidence=score)

        if not best_match:
            return None

        resolved_name = self._resolve_to_existing_category(
            best_match.category_name,
            existing_categories,
        )
        return ClassificationResult(category_name=resolved_name, confidence=best_match.confidence)

    @staticmethod
    def _match_score(text: str, keywords: Iterable[str]) -> float:
        score = 0.0
        for keyword in keywords:
            if keyword and keyword.lower() in text:
                score = max(score, float(len(keyword)))
        return score

    @staticmethod
    def _resolve_to_existing_category(
        suggestion: str,
        existing_categories: Iterable[str],
    ) -> str:
        suggestion_lower = suggestion.lower()
        exact_match = next(
            (name for name in existing_categories if name.lower() == suggestion_lower),
            None,
        )
        if exact_match:
            return exact_match
        partial_match = next(
            (
                name
                for name in existing_categories
                if suggestion_lower in name.lower() or name.lower() in suggestion_lower
            ),
            None,
        )
        if partial_match:
            return partial_match
        return suggestion
