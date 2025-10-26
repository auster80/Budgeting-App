"""CSV importing helpers for Rabobank-style exports."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Iterable, List, Optional

from .text_utils import extract_company_name

DATE_COLUMNS = ("Datum", "Rentedatum")
DESCRIPTION_COLUMNS = (
    "Naam tegenpartij",
    "Omschrijving-1",
    "Omschrijving-2",
    "Omschrijving-3",
)

CREDIT_CARD_REQUIRED_COLUMNS = ("Datum", "Omschrijving", "Bedrag")
CREDIT_CARD_ACCOUNT_COLUMNS = (
    "Kaartnummer",
    "Pasnummer",
    "Creditcardnummer",
    "Card Number",
)
CREDIT_CARD_REFERENCE_COLUMNS = (
    "Transactie ID",
    "Transactie-ID",
    "Referentie",
    "Documentnummer",
    "Volgnr",
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
    company: Optional[str] = None


def _parse_decimal(value: str) -> Decimal:
    cleaned = value.strip().replace("\u00a0", "")
    if not cleaned:
        return Decimal("0")
    # Rabobank exports use comma as decimal separator.
    normalized = cleaned.replace(".", "").replace(",", ".")
    return Decimal(normalized)


def _parse_credit_card_date(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("Credit card transaction is missing a date")
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y", "%m-%d-%Y"):
        try:
            return datetime.strptime(cleaned, fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"Unsupported credit card date format: '{value}'")


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
            company=extract_company_name(description),
        )


def _credit_card_account(row: dict[str, str]) -> Optional[str]:
    for column in CREDIT_CARD_ACCOUNT_COLUMNS:
        value = row.get(column, "").strip()
        if value:
            return value
    return None


def _credit_card_reference(row: dict[str, str]) -> Optional[str]:
    for column in CREDIT_CARD_REFERENCE_COLUMNS:
        value = row.get(column, "").strip()
        if value:
            return value
    return None


def read_credit_card_statement(path: str | Path) -> List[CSVTransaction]:
    """Parse credit-card specific CSV exports into CSVTransaction records."""

    csv_path = Path(path)
    reader = _get_reader(csv_path)

    fieldnames = reader.fieldnames or []
    missing = [column for column in CREDIT_CARD_REQUIRED_COLUMNS if column not in fieldnames]
    if missing:
        raise ValueError(
            "Credit card CSV is missing required columns: " + ", ".join(missing)
        )

    transactions: List[CSVTransaction] = []
    for row in reader:
        if not any((value or "").strip() for value in row.values()):
            continue
        amount = _parse_decimal(row.get("Bedrag", "0"))
        description = row.get("Omschrijving", "").strip() or "Credit card transaction"
        occurred_on = _parse_credit_card_date(row.get("Datum", ""))
        reference = _credit_card_reference(row)
        account_id = _credit_card_account(row)
        account_name = row.get("Kaartnaam", "").strip() or "Credit Card"
        counterparty = row.get("Winkel", "").strip() or row.get("Handelaar", "").strip()

        transactions.append(
            CSVTransaction(
                description=description,
                amount=amount,
                occurred_on=occurred_on,
                account_id=account_id or "CREDIT-CARD",
                account_name=account_name,
                counterparty=counterparty or None,
                reference=reference,
                company=extract_company_name(description),
            )
        )

    return transactions
