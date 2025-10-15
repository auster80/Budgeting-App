"""Persistence helpers for the budgeting application."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import BudgetLedger

DEFAULT_DATA_FILE = Path("budget_data.json")


def load_ledger(data_path: str | Path | None = None) -> BudgetLedger:
    """Load budget data from disk; return an empty ledger when the file is missing."""
    path = Path(data_path) if data_path else DEFAULT_DATA_FILE
    if not path.exists():
        return BudgetLedger()
    with path.open("r", encoding="utf-8") as handle:
        payload: dict[str, Any] = json.load(handle)
    return BudgetLedger.from_dict(payload)


def save_ledger(ledger: BudgetLedger, data_path: str | Path | None = None) -> None:
    """Persist budget data to disk as JSON."""
    path = Path(data_path) if data_path else DEFAULT_DATA_FILE
    with path.open("w", encoding="utf-8") as handle:
        json.dump(ledger.to_dict(), handle, indent=2)
