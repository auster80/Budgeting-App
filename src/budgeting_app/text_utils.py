"""Text processing helpers used across the budgeting application."""

from __future__ import annotations

import re

_CARD_DETAIL_PATTERNS = (
    re.compile(r"\bPas:.*", re.IGNORECASE),
    re.compile(r"\bTerminal:.*", re.IGNORECASE),
    re.compile(r"\bAppr\s*Cd:.*", re.IGNORECASE),
)


def _clean_segment(segment: str) -> str:
    """Normalise a candidate company segment extracted from a description."""

    cleaned = segment.strip(" -.,")
    if not cleaned:
        return ""
    for pattern in _CARD_DETAIL_PATTERNS:
        cleaned = pattern.sub("", cleaned)
    cleaned = cleaned.strip(" -.,")
    return cleaned


def extract_company_name(description: str | None) -> str | None:
    """Extract a human-friendly company name from a description string.

    Rabobank descriptions are composed of pipe-separated fragments where the
    first few entries typically contain the counterparty or merchant name.
    We iterate over the fragments until we find a non-empty segment that looks
    like a plausible company identifier and strip away card metadata.
    """

    if not description:
        return None

    for raw_segment in description.split("|"):
        segment = _clean_segment(raw_segment)
        if segment and any(char.isalpha() for char in segment):
            return segment
    return None

