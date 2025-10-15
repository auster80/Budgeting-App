"""Application state and helpers that bridge the UI with domain models."""

from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from typing import Callable, Iterable, List, Optional

from .ai import TransactionClassifier
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
        self._classifier = TransactionClassifier()
        self._ai_log: List[str] = []

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
        )
        self._notify()
        return transaction

    def delete_transaction(self, transaction_id: str) -> None:
        self.ledger.transactions = [
            txn for txn in self.ledger.transactions if txn.transaction_id != transaction_id
        ]
        self.ledger.recalculate_actuals()
        self._notify()

    def set_transactions_category(
        self, transaction_ids: Iterable[str], category_id: str
    ) -> None:
        if category_id not in self.ledger.categories:
            raise KeyError(f"Unknown category id '{category_id}'")

        transaction_ids = list(transaction_ids)
        if not transaction_ids:
            return

        id_set = set(transaction_ids)
        updated = False
        for txn in self.ledger.transactions:
            if txn.transaction_id in id_set:
                txn.category_id = category_id
                updated = True

        if not updated:
            missing = ", ".join(sorted(id_set))
            raise KeyError(f"Unknown transaction id '{missing}'")

        self.ledger.recalculate_actuals()
        self._notify()

    def set_transaction_category(self, transaction_id: str, category_id: str) -> None:
        self.set_transactions_category([transaction_id], category_id)

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
                "account": txn.account_name or txn.account_id or "",
                "amount": f"{txn.amount:.2f}",
                "category": category_name,
                "occurred_on": txn.occurred_on,
            }

    # ------------------------------------------------------------------ #
    # AI assisted categorisation
    # ------------------------------------------------------------------ #
    def suggest_categories_for_unassigned(
        self,
        *,
        logger: Optional[Callable[[str], None]] = None,
        should_abort: Optional[Callable[[], bool]] = None,
    ) -> dict[str, str]:
        """Return AI category suggestions for unassigned transactions."""

        log = logger or self._append_ai_log
        if should_abort and should_abort():
            log("AI classification cancelled before starting.")
            return {}
        existing_names = [category.name for category in self.ledger.categories.values()]
        categorized_examples: list[tuple[Transaction, str]] = []
        for txn in self.ledger.transactions:
            if not txn.category_id:
                continue
            category = self.ledger.categories.get(txn.category_id)
            if not category:
                continue
            categorized_examples.append((txn, category.name))

        unassigned = [txn for txn in self.ledger.transactions if not txn.category_id]
        if not unassigned:
            log("No unassigned transactions to classify.")
            return {}

        log(
            f"Attempting to classify {len(unassigned)} unassigned "
            f"transaction{'s' if len(unassigned) != 1 else ''}."
        )

        suggestions: dict[str, str] = {}
        for txn in unassigned:
            if should_abort and should_abort():
                log("AI classification cancelled.")
                break
            txn_label = txn.description or txn.transaction_id or "(unnamed)"
            log(f"Requesting suggestion for '{txn_label}'.")

            def txn_logger(message: str, *, txn_id: str = txn.transaction_id) -> None:
                log(f"[{txn_id}] {message}")

            result = self._classifier.suggest_category(
                txn,
                existing_names,
                categorized_examples,
                logger=txn_logger,
            )
            if should_abort and should_abort():
                log("AI classification cancelled.")
                break
            if result is None:
                log(f"No suggestion produced for '{txn_label}'.")
                continue
            suggestions[txn.transaction_id] = result.category_name
            log(
                f"Accepted suggestion '{result.category_name}' for "
                f"transaction '{txn_label}'."
            )
        return suggestions

    def accept_ai_suggestion(self, transaction_id: str, category_name: str) -> bool:
        """Apply an AI suggestion and ensure the category exists.

        Returns ``True`` when the category had to be created.
        """

        category_id = None
        for cid, category in self.ledger.categories.items():
            if category.name.lower() == category_name.lower():
                category_id = cid
                break

        created = False
        if category_id is None:
            category = self.ledger.add_category(category_name, Decimal("0.00"))
            category_id = category.category_id
            created = True

        self.set_transaction_category(transaction_id, category_id)
        return created

    # ------------------------------------------------------------------ #
    # AI log helpers
    # ------------------------------------------------------------------ #
    def clear_ai_log(self) -> None:
        self._ai_log.clear()

    def get_ai_log(self) -> List[str]:
        return list(self._ai_log)

    def add_ai_log_entry(self, message: str) -> None:
        self._append_ai_log(message)

    def _append_ai_log(self, message: str) -> None:
        self._ai_log.append(message)
        # Keep the log to a sensible size for the UI widget.
        if len(self._ai_log) > 500:
            self._ai_log = self._ai_log[-500:]

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
            )
            if record.reference:
                existing_refs.add(record.reference)
            imported += 1

        if imported:
            self._notify()
        return imported
