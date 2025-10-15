"""Domain models for the budgeting application."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from decimal import Decimal, getcontext
from typing import Dict, Iterable, List, Optional
from uuid import uuid4

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

    def __post_init__(self) -> None:
        self.amount = _to_decimal(self.amount)
        self.occurred_on = _format_date(self.occurred_on)

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
        )


@dataclass(slots=True)
class BudgetLedger:
    """Container for the user's budget categories and transactions."""

    categories: Dict[str, BudgetCategory] = field(default_factory=dict)
    transactions: List[Transaction] = field(default_factory=list)

    def add_category(
        self,
        name: str,
        planned_amount: float | int | str | Decimal = Decimal("0.00"),
        *,
        category_id: Optional[str] = None,
    ) -> BudgetCategory:
        """Create and register a new budget category."""
        category = BudgetCategory(
            name=name,
            planned_amount=_to_decimal(planned_amount),
            category_id=category_id or uuid4().hex,
        )
        self.categories[category.category_id] = category
        return category

    def remove_category(self, category_id: str) -> None:
        """Remove a category and its associated transactions."""
        self.categories.pop(category_id, None)
        self.transactions = [
            txn for txn in self.transactions if txn.category_id != category_id
        ]

    def update_category(
        self,
        category_id: str,
        *,
        name: str | None = None,
        planned_amount: float | int | str | Decimal | None = None,
    ) -> BudgetCategory:
        """Update an existing category's details."""
        if category_id not in self.categories:
            raise KeyError(f"Unknown category id '{category_id}'")

        category = self.categories[category_id]
        if name is not None:
            category.name = name
        if planned_amount is not None:
            category.planned_amount = _to_decimal(planned_amount)
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
        )
        self.transactions.append(transaction)
        if category_id:
            if category_id not in self.categories:
                raise KeyError(f"Unknown category id '{category_id}'")
            self.categories[category_id].apply_transaction(transaction)
        return transaction

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
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Iterable[Dict[str, str]]]) -> "BudgetLedger":
        """Rehydrate a ledger from serialised data."""
        ledger = cls()
        for category_data in payload.get("categories", []):
            category = BudgetCategory.from_dict(category_data)
            ledger.categories[category.category_id] = category
        for txn_data in payload.get("transactions", []):
            transaction = Transaction.from_dict(txn_data)
            ledger.transactions.append(transaction)
        ledger.recalculate_actuals()
        return ledger
