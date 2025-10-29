"""Domain models for the budgeting application."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from decimal import Decimal, getcontext
from typing import Dict, Iterable, List, Optional
from uuid import uuid4

from .text_utils import extract_company_name

getcontext().prec = 28  # Higher precision for money calculations.


def _to_decimal(value: float | int | str | Decimal) -> Decimal:
    """Convert user-provided numeric values into a Decimal."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _format_date(value: date | datetime | str) -> str:
    """Normalise date values to an ISO date string (YYYY-MM-DD)."""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


@dataclass(slots=True)
class BudgetCategory:
    """Represents a budgeting category (e.g., Housing, Food)."""

    name: str
    planned_amount: Decimal = Decimal("0.00")
    actual_amount: Decimal = Decimal("0.00")
    category_id: str = field(default_factory=lambda: uuid4().hex)
    header_id: str | None = None

    def apply_transaction(self, transaction: "Transaction") -> None:
        """Apply a transaction to this category's actual amount."""
        self.actual_amount += transaction.amount

    def to_dict(self) -> Dict[str, str]:
        """Serialise the category for JSON storage."""
        data = asdict(self)
        data["planned_amount"] = str(self.planned_amount)
        data["actual_amount"] = str(self.actual_amount)
        return data

    @classmethod
    def from_dict(cls, payload: Dict[str, str]) -> "BudgetCategory":
        """Create a category instance from serialised data."""
        return cls(
            name=payload["name"],
            planned_amount=_to_decimal(payload.get("planned_amount", "0")),
            actual_amount=_to_decimal(payload.get("actual_amount", "0")),
            category_id=payload.get("category_id", uuid4().hex),
            header_id=payload.get("header_id"),
        )


@dataclass(slots=True)
class CategoryHeader:
    """Represents a grouping header for related budgeting categories."""

    name: str
    header_id: str = field(default_factory=lambda: uuid4().hex)

    def to_dict(self) -> Dict[str, str]:
        data = asdict(self)
        return data

    @classmethod
    def from_dict(cls, payload: Dict[str, str]) -> "CategoryHeader":
        return cls(
            name=payload["name"],
            header_id=payload.get("header_id", uuid4().hex),
        )


@dataclass(slots=True)
class Transaction:
    """Represents an income or expense transaction."""

    description: str
    amount: Decimal
    occurred_on: str = field(default_factory=lambda: date.today().isoformat())
    category_id: str | None = None
    transaction_id: str = field(default_factory=lambda: uuid4().hex)
    account_id: str | None = None
    account_name: str | None = None
    counterparty: str | None = None
    reference: str | None = None
    company: str | None = None
    is_internal_transfer: bool = False
    transfer_partner_id: str | None = None

    def __post_init__(self) -> None:
        self.amount = _to_decimal(self.amount)
        self.occurred_on = _format_date(self.occurred_on)
        if self.company is None:
            self.company = extract_company_name(self.description)

    def to_dict(self) -> Dict[str, str]:
        """Serialise the transaction for JSON storage."""
        data = asdict(self)
        data["amount"] = str(self.amount)
        return data

    @classmethod
    def from_dict(cls, payload: Dict[str, str]) -> "Transaction":
        """Rehydrate a transaction from serialised data."""
        return cls(
            description=payload["description"],
            amount=_to_decimal(payload["amount"]),
            occurred_on=payload.get("occurred_on", date.today().isoformat()),
            category_id=payload.get("category_id"),
            transaction_id=payload.get("transaction_id", uuid4().hex),
            account_id=payload.get("account_id"),
            account_name=payload.get("account_name"),
            counterparty=payload.get("counterparty"),
            reference=payload.get("reference"),
            company=payload.get("company"),
            is_internal_transfer=payload.get("is_internal_transfer", False),
            transfer_partner_id=payload.get("transfer_partner_id"),
        )


@dataclass(slots=True)
class BudgetLedger:
    """Container for the user's budget categories and transactions."""

    TRANSFER_CATEGORY_NAME = "Transfers"

    categories: Dict[str, BudgetCategory] = field(default_factory=dict)
    transactions: List[Transaction] = field(default_factory=list)
    category_headers: Dict[str, CategoryHeader] = field(default_factory=dict)

    def add_category(
        self,
        name: str,
        planned_amount: float | int | str | Decimal = Decimal("0.00"),
        *,
        category_id: Optional[str] = None,
        header_id: Optional[str] = None,
    ) -> BudgetCategory:
        """Create and register a new budget category."""

        if header_id and header_id not in self.category_headers:
            raise KeyError(f"Unknown header id '{header_id}'")
        category = BudgetCategory(
            name=name,
            planned_amount=_to_decimal(planned_amount),
            category_id=category_id or uuid4().hex,
            header_id=header_id,
        )
        self.categories[category.category_id] = category
        return category

    def update_category(
        self,
        category_id: str,
        *,
        name: str | None = None,
        planned_amount: float | int | str | Decimal | None = None,
        header_id: Optional[str] = None,
    ) -> BudgetCategory:
        """Update the editable fields of an existing budget category."""

        if category_id not in self.categories:
            raise KeyError(f"Unknown category id '{category_id}'")

        category = self.categories[category_id]
        if name is not None:
            category.name = name
        if planned_amount is not None:
            category.planned_amount = _to_decimal(planned_amount)
        if header_id is not None:
            if header_id and header_id not in self.category_headers:
                raise KeyError(f"Unknown header id '{header_id}'")
            category.header_id = header_id
        return category

    def remove_category(self, category_id: str) -> None:
        """Remove a category and its associated transactions."""
        self.categories.pop(category_id, None)
        self.transactions = [
            txn for txn in self.transactions if txn.category_id != category_id
        ]

    def add_header(
        self,
        name: str,
        *,
        header_id: Optional[str] = None,
    ) -> CategoryHeader:
        header = CategoryHeader(name=name, header_id=header_id or uuid4().hex)
        self.category_headers[header.header_id] = header
        return header

    def update_header(self, header_id: str, *, name: str | None = None) -> CategoryHeader:
        if header_id not in self.category_headers:
            raise KeyError(f"Unknown header id '{header_id}'")
        header = self.category_headers[header_id]
        if name is not None:
            header.name = name
        return header

    def remove_header(self, header_id: str) -> None:
        if header_id not in self.category_headers:
            return
        self.category_headers.pop(header_id, None)
        for category in self.categories.values():
            if category.header_id == header_id:
                category.header_id = None

    def set_category_header(self, category_id: str, header_id: Optional[str]) -> BudgetCategory:
        if category_id not in self.categories:
            raise KeyError(f"Unknown category id '{category_id}'")
        if header_id and header_id not in self.category_headers:
            raise KeyError(f"Unknown header id '{header_id}'")
        category = self.categories[category_id]
        category.header_id = header_id
        return category

    def record_transaction(
        self,
        *,
        description: str,
        amount: float | int | str | Decimal,
        category_id: str | None,
        occurred_on: date | datetime | str | None = None,
        transaction_id: Optional[str] = None,
        account_id: Optional[str] = None,
        account_name: Optional[str] = None,
        counterparty: Optional[str] = None,
        reference: Optional[str] = None,
        company: Optional[str] = None,
    ) -> Transaction:
        """Add a transaction and update its category totals."""
        if category_id and category_id not in self.categories:
            raise KeyError(f"Unknown category id '{category_id}'")

        transaction = Transaction(
            description=description,
            amount=amount,
            category_id=category_id,
            occurred_on=occurred_on or date.today(),
            transaction_id=transaction_id or uuid4().hex,
            account_id=account_id,
            account_name=account_name,
            counterparty=counterparty,
            reference=reference,
            company=company,
        )
        self.transactions.append(transaction)
        if category_id:
            if category_id not in self.categories:
                raise KeyError(f"Unknown category id '{category_id}'")
            self.categories[category_id].apply_transaction(transaction)
        if self.detect_internal_transfers():
            self.recalculate_actuals()
        return transaction

    # ------------------------------------------------------------------ #
    # Internal transfer helpers
    # ------------------------------------------------------------------ #

    def _get_transfer_category_id(self) -> Optional[str]:
        for category_id, category in self.categories.items():
            if category.name.lower() == self.TRANSFER_CATEGORY_NAME.lower():
                return category_id
        return None

    def _ensure_transfer_category(self) -> str:
        transfer_id = self._get_transfer_category_id()
        if transfer_id is not None:
            return transfer_id
        category = self.add_category(self.TRANSFER_CATEGORY_NAME, Decimal("0.00"))
        return category.category_id

    def _mark_transfer_pair(
        self, first: Transaction, second: Transaction, *, category_id: str
    ) -> bool:
        changed = False
        for current, partner in ((first, second), (second, first)):
            if not current.is_internal_transfer:
                current.is_internal_transfer = True
                changed = True
            if current.transfer_partner_id != partner.transaction_id:
                current.transfer_partner_id = partner.transaction_id
                changed = True
            if current.category_id != category_id:
                current.category_id = category_id
                changed = True
        return changed

    def detect_internal_transfers(self) -> bool:
        """Re-evaluate the ledger for internal transfers.

        Returns ``True`` when any transaction or category assignment changed.
        """

        changed = False
        transfer_category_id = self._get_transfer_category_id()

        # Reset existing transfer markers; category will be re-applied if a
        # valid pair is detected again.
        for txn in self.transactions:
            if txn.is_internal_transfer:
                txn.is_internal_transfer = False
                changed = True
            if txn.transfer_partner_id is not None:
                txn.transfer_partner_id = None
                changed = True
            if transfer_category_id and txn.category_id == transfer_category_id:
                txn.category_id = None
                changed = True

        if not self.transactions:
            return changed

        from collections import defaultdict

        groups: Dict[tuple[str, Decimal], List[Transaction]] = defaultdict(list)
        for txn in self.transactions:
            if not txn.reference or not txn.account_id or txn.amount == 0:
                continue
            key = (txn.reference.strip().lower(), abs(txn.amount))
            groups[key].append(txn)

        for transactions in groups.values():
            positives = [t for t in transactions if t.amount > 0]
            negatives = [t for t in transactions if t.amount < 0]
            if not positives or not negatives:
                continue
            used_negatives: set[str] = set()
            used_positives: set[str] = set()
            transfer_id: Optional[str] = None
            for pos in positives:
                if pos.account_id is None or pos.transaction_id in used_positives:
                    continue
                for neg in negatives:
                    if neg.account_id == pos.account_id:
                        continue
                    if neg.transaction_id in used_negatives:
                        continue
                    if transfer_id is None:
                        transfer_id = self._ensure_transfer_category()
                    if self._mark_transfer_pair(pos, neg, category_id=transfer_id):
                        changed = True
                    used_negatives.add(neg.transaction_id)
                    used_positives.add(pos.transaction_id)
                    break

        return changed

    def recalculate_actuals(self) -> None:
        """Recompute category actual totals from the transactions list."""
        for category in self.categories.values():
            category.actual_amount = Decimal("0.00")

        for transaction in self.transactions:
            if transaction.category_id and transaction.category_id in self.categories:
                self.categories[transaction.category_id].apply_transaction(transaction)

    def to_dict(self) -> Dict[str, Iterable[Dict[str, str]]]:
        """Serialise the ledger for storage."""
        return {
            "categories": [category.to_dict() for category in self.categories.values()],
            "transactions": [txn.to_dict() for txn in self.transactions],
            "category_headers": [
                header.to_dict() for header in self.category_headers.values()
            ],
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Iterable[Dict[str, str]]]) -> "BudgetLedger":
        """Rehydrate a ledger from serialised data."""
        ledger = cls()
        for header_data in payload.get("category_headers", []):
            header = CategoryHeader.from_dict(header_data)
            ledger.category_headers[header.header_id] = header
        for category_data in payload.get("categories", []):
            category = BudgetCategory.from_dict(category_data)
            ledger.categories[category.category_id] = category
        for txn_data in payload.get("transactions", []):
            transaction = Transaction.from_dict(txn_data)
            ledger.transactions.append(transaction)
        ledger.detect_internal_transfers()
        ledger.recalculate_actuals()
        return ledger
