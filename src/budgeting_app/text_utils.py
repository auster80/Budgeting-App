"""Text processing helpers used across the budgeting application."""

from __future__ import annotations


def extract_company_name(description: str) -> str | None:
    """Return the leading segment of a description as the company name."""

    if not description:
        return None

    primary, *_ = description.split("|", 1)
    company = primary.strip()
    return company or None

