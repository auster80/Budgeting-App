"""CSV importing helpers for Rabobank-style exports."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Iterable, List, Optional

DATE_COLUMNS = ("Datum", "Rentedatum")
DESCRIPTION_COLUMNS = (
    "Naam tegenpartij",
    "Omschrijving-1",
    "Omschrijving-2",
    "Omschrijving-3",
)


@dataclass(slots=True)
class CSVTransaction:
    """Representation of a transaction parsed from the CSV file."""

    description: str
    amount: Decimal
    occurred_on: str
    account_id: str
    account_name: Optional[str]
    counterparty: Optional[str]
    reference: Optional[str]


def _parse_decimal(value: str) -> Decimal:
    cleaned = value.strip().replace("\u00a0", "")
    if not cleaned:
        return Decimal("0")
    # Rabobank exports use comma as decimal separator.
    normalized = cleaned.replace(".", "").replace(",", ".")
    return Decimal(normalized)


def _pick_date(row: dict[str, str]) -> str:
    for key in DATE_COLUMNS:
        value = row.get(key, "").strip()
        if value:
            try:
                return datetime.strptime(value, "%Y-%m-%d").date().isoformat()
            except ValueError:
                continue
    raise ValueError("Unable to determine transaction date")


def _build_description(row: dict[str, str]) -> str:
    parts: List[str] = []
    seen = set()
    for key in DESCRIPTION_COLUMNS:
        value = row.get(key, "").strip()
        if value and value not in seen:
            seen.add(value)
            parts.append(value)
    reference = row.get("Transactiereferentie", "").strip()
    if reference and reference not in seen:
        parts.append(reference)
    return " | ".join(parts) if parts else "Transaction"


def _account_name(row: dict[str, str]) -> Optional[str]:
    party = row.get("Naam initiërende partij") or row.get("Naam initi?rende partij")  # CSV may be mis-encoded
    if party:
        cleaned = party.strip()
        if cleaned and cleaned != row.get("Naam tegenpartij", "").strip():
            return cleaned
    return None


def _counterparty(row: dict[str, str]) -> Optional[str]:
    value = row.get("Naam tegenpartij", "").strip()
    return value or None


def _reference(row: dict[str, str]) -> Optional[str]:
    preferred = (
        row.get("Transactiereferentie")
        or row.get("Machtigingskenmerk")
        or row.get("Batch ID")
        or row.get("Volgnr")
    )
    value = (preferred or "").strip()
    return value or None


def _get_reader(path: Path) -> csv.DictReader:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            text = path.read_text(encoding=encoding)
            break
        except UnicodeDecodeError:
            continue
    else:  # pragma: no cover - should rarely happen
        raise UnicodeDecodeError("utf-8", b"", 0, 1, "Unable to decode CSV file")
    return csv.DictReader(io.StringIO(text))


def read_transactions_from_csv(path: str | Path) -> Iterable[CSVTransaction]:
    """Yield CSVTransaction objects from a Rabobank-style export."""
    csv_path = Path(path)
    reader = _get_reader(csv_path)
    for row in reader:
        account_id = row.get("IBAN/BBAN", "").strip()
        if not account_id:
            continue
        description = _build_description(row)
        amount = _parse_decimal(row.get("Bedrag", "0"))
        occurred_on = _pick_date(row)
        yield CSVTransaction(
            description=description,
            amount=amount,
            occurred_on=occurred_on,
            account_id=account_id,
            account_name=_account_name(row),
            counterparty=_counterparty(row),
            reference=_reference(row),
        )
