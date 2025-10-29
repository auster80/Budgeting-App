"""CSV importing helpers for Rabobank-style exports."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date, datetime
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


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _infer_credit_card_month_first(rows: list[dict[str, str]]) -> bool:
    day_first_votes = 0
    month_first_votes = 0
    ambiguous: list[tuple[date, date]] = []
    first_values: set[int] = set()
    second_values: set[int] = set()

    for row in rows:
        raw = (row.get("Datum") or "").strip()
        if not raw:
            continue
        normalized = raw.replace(".", "-").replace("/", "-")
        parts = normalized.split("-")
        if len(parts) != 3 or not parts[2]:
            continue
        first_part, second_part, year_part = parts

        try:
            first_num = int(first_part)
            second_num = int(second_part)
        except ValueError:
            continue

        try:
            year_num = int(year_part)
        except ValueError:
            continue
        if year_num < 100:
            year_num += 2000 if year_num < 70 else 1900

        day_first = _safe_date(year_num, second_num, first_num)
        month_first = _safe_date(year_num, first_num, second_num)

        if day_first and not month_first:
            day_first_votes += 1
            continue
        if month_first and not day_first:
            month_first_votes += 1
            continue
        if day_first and month_first:
            ambiguous.append((day_first, month_first))
            first_values.add(first_num)
            second_values.add(second_num)

    if month_first_votes and not day_first_votes:
        return True
    if day_first_votes and not month_first_votes:
        return False

    if ambiguous:
        first_constant = len(first_values) == 1
        second_constant = len(second_values) == 1
        if first_constant and not second_constant:
            return True
        if second_constant and not first_constant:
            return False
        day_dates = [d for d, _ in ambiguous]
        month_dates = [m for _, m in ambiguous]
        if len(day_dates) > 1 and len(month_dates) > 1:
            day_range = (max(day_dates) - min(day_dates)).days
            month_range = (max(month_dates) - min(month_dates)).days
            if month_range < day_range:
                return True
            if day_range < month_range:
                return False

    return False


def _parse_credit_card_date(value: str, *, prefer_month_first: bool | None = None) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("Credit card transaction is missing a date")

    normalized = cleaned.replace(".", "-").replace("/", "-")
    parts = normalized.split("-")
    if len(parts) == 3 and parts[2]:
        first, second, year_part = parts
        try:
            first_num = int(first)
            second_num = int(second)
        except ValueError:
            first_num = second_num = -1

        try:
            year_num = int(year_part)
        except ValueError:
            year_num = None
        else:
            if year_num < 100:
                year_num += 2000 if year_num < 70 else 1900

        if year_num:
            if prefer_month_first is True:
                order = [(first_num, second_num), (second_num, first_num)]
            elif prefer_month_first is False:
                order = [(second_num, first_num), (first_num, second_num)]
            else:
                order = [(second_num, first_num), (first_num, second_num)]

            for month, day in order:
                candidate = _safe_date(year_num, month, day)
                if candidate:
                    return candidate.isoformat()

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

    rows: List[dict[str, str]] = [
        row for row in reader if any((value or "").strip() for value in row.values())
    ]
    prefer_month_first = _infer_credit_card_month_first(rows)

    transactions: List[CSVTransaction] = []
    for row in rows:
        amount = _parse_decimal(row.get("Bedrag", "0"))
        description = row.get("Omschrijving", "").strip() or "Credit card transaction"
        occurred_on = _parse_credit_card_date(
            row.get("Datum", ""), prefer_month_first=prefer_month_first
        )
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
