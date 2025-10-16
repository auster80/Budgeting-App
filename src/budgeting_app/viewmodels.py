"""Application state and helpers that bridge the UI with domain models."""

from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from typing import Callable, Iterable, List, Optional

from .csv_importer import CSVTransaction, read_transactions_from_csv
from .models import BudgetLedger, BudgetCategory, Transaction
from .storage import load_ledger, save_ledger

ChangeListener = Callable[[BudgetLedger], None]


class BudgetViewModel:
    """High-level application state that coordinates UI actions."""

    def __init__(self, *, data_file: str | None = None) -> None:
        self.data_file = data_file
        self.ledger: BudgetLedger = BudgetLedger()
        self._listeners: List[ChangeListener] = []

    # ------------------------------------------------------------------ #
    # Persistence
    # ------------------------------------------------------------------ #
    def load(self) -> None:
        self.ledger = load_ledger(self.data_file)
        self._notify()

    def save(self) -> None:
        save_ledger(self.ledger, self.data_file)

    # ------------------------------------------------------------------ #
    # Listener registration
    # ------------------------------------------------------------------ #
    def add_listener(self, callback: ChangeListener) -> None:
        self._listeners.append(callback)

    def _notify(self) -> None:
        for listener in self._listeners:
            listener(self.ledger)

    # ------------------------------------------------------------------ #
    # Category operations
    # ------------------------------------------------------------------ #
    def add_category(self, name: str, planned_amount: str | float | Decimal) -> BudgetCategory:
        category = self.ledger.add_category(name, planned_amount)
        self._notify()
        return category

    def delete_category(self, category_id: str) -> None:
        self.ledger.remove_category(category_id)
        self._notify()

    def categories_for_table(self) -> Iterable[dict[str, str]]:
        """Return category data shaped for display tables."""
        for category in self.ledger.categories.values():
            yield {
                "category_id": category.category_id,
                "name": category.name,
                "planned": f"{category.planned_amount:.2f}",
                "actual": f"{category.actual_amount:.2f}",
                "difference": f"{(category.planned_amount - category.actual_amount):.2f}",
            }

    # ------------------------------------------------------------------ #
    # Transaction operations
    # ------------------------------------------------------------------ #
    def add_transaction(
        self,
        *,
        description: str,
        amount: str | float | Decimal,
        category_id: Optional[str],
        occurred_on: str,
        account_id: Optional[str] = None,
        account_name: Optional[str] = None,
        counterparty: Optional[str] = None,
        reference: Optional[str] = None,
        company: Optional[str] = None,
    ) -> Transaction:
        transaction = self.ledger.record_transaction(
            description=description,
            amount=amount,
            category_id=category_id,
            occurred_on=occurred_on,
            account_id=account_id,
            account_name=account_name,
            counterparty=counterparty,
            reference=reference,
            company=company,
        )
        self._notify()
        return transaction

    def delete_transaction(self, transaction_id: str) -> None:
        self.ledger.transactions = [
            txn for txn in self.ledger.transactions if txn.transaction_id != transaction_id
        ]
        self.ledger.recalculate_actuals()
        self._notify()

    def set_transaction_category(self, transaction_id: str, category_id: str) -> None:
        if category_id not in self.ledger.categories:
            raise KeyError(f"Unknown category id '{category_id}'")
        for txn in self.ledger.transactions:
            if txn.transaction_id == transaction_id:
                txn.category_id = category_id
                self.ledger.recalculate_actuals()
                self._notify()
                return
        raise KeyError(f"Unknown transaction id '{transaction_id}'")

    def transactions_for_table(self) -> Iterable[dict[str, str]]:
        """Return transaction data shaped for display tables."""
        categories = self.ledger.categories
        for txn in self.ledger.transactions:
            category_name = (
                categories.get(txn.category_id, BudgetCategory(name="Unassigned")).name
                if txn.category_id
                else "Unassigned"
            )
            yield {
                "transaction_id": txn.transaction_id,
                "description": txn.description,
                "company": txn.company or txn.counterparty or "",
                "account": txn.account_name or txn.account_id or "",
                "amount": f"{txn.amount:.2f}",
                "category": category_name,
                "occurred_on": txn.occurred_on,
            }

    # ------------------------------------------------------------------ #
    # Utility helpers
    # ------------------------------------------------------------------ #
    def as_dict(self) -> dict[str, list[dict[str, str]]]:
        return asdict(self.ledger)

    # ------------------------------------------------------------------ #
    # Import helpers
    # ------------------------------------------------------------------ #
    def import_transactions_from_csv(
        self,
        path: str | Path,
        *,
        category_by_account: Optional[dict[str, str]] = None,
        default_category_id: Optional[str] = None,
        skip_existing: bool = True,
    ) -> int:
        """Import transactions from a Rabobank CSV export."""
        category_by_account = category_by_account or {}
        csv_transactions = list(read_transactions_from_csv(path))
        if not csv_transactions:
            return 0

        existing_refs = {
            txn.reference
            for txn in self.ledger.transactions
            if txn.reference is not None
        } if skip_existing else set()

        imported = 0
        for record in csv_transactions:
            if skip_existing and record.reference and record.reference in existing_refs:
                continue
            category_id = category_by_account.get(record.account_id, default_category_id)
            self.ledger.record_transaction(
                description=record.description,
                amount=record.amount,
                category_id=category_id,
                occurred_on=record.occurred_on,
                transaction_id=record.reference,
                account_id=record.account_id,
                account_name=record.account_name,
                counterparty=record.counterparty,
                reference=record.reference,
                company=record.company,
            )
            if record.reference:
                existing_refs.add(record.reference)
            imported += 1

        if imported:
            self._notify()
        return imported
