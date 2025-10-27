"""Application state and helpers that bridge the UI with domain models."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Sequence

from .ai import ClassificationResult, TransactionClassifier
from .csv_importer import (
    CSVTransaction,
    read_credit_card_statement,
    read_transactions_from_csv,
)
from .models import BudgetLedger, BudgetCategory, Transaction
from .storage import load_ledger, save_ledger

ChangeListener = Callable[[BudgetLedger], None]


@dataclass(slots=True)
class CSVImportPreview:
    """Summary of the differences between a CSV file and existing data."""

    source_path: Path
    new_transactions: List[CSVTransaction]
    duplicate_transactions: List[CSVTransaction]

    @property
    def new_count(self) -> int:
        return len(self.new_transactions)

    @property
    def duplicate_count(self) -> int:
        return len(self.duplicate_transactions)


class BudgetViewModel:
    """High-level application state that coordinates UI actions."""

    def __init__(self, *, data_file: str | None = None) -> None:
        self.data_file = data_file
        self.ledger: BudgetLedger = BudgetLedger()
        self._listeners: List[ChangeListener] = []
        self._classifier = TransactionClassifier()
        self._ai_log: List[str] = []
        self._latest_suggestions: dict[str, ClassificationResult] = {}

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

    def update_category(
        self,
        category_id: str,
        *,
        name: str | None = None,
        planned_amount: str | float | Decimal | None = None,
    ) -> BudgetCategory:
        category = self.ledger.update_category(
            category_id,
            name=name,
            planned_amount=planned_amount,
        )
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
        self.ledger.detect_internal_transfers()
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
        final_category_name = self.ledger.categories[category_id].name
        for txn in self.ledger.transactions:
            if txn.transaction_id in id_set:
                suggestion = self._latest_suggestions.pop(txn.transaction_id, None)
                try:
                    self._classifier.record_feedback(txn, suggestion, final_category_name)
                except Exception:
                    pass
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
                "company": txn.company or txn.counterparty or "",
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
        on_suggestion: Optional[
            Callable[[str, ClassificationResult], None]
        ] = None,
        preferred_order: Optional[Sequence[str]] = None,
    ) -> dict[str, ClassificationResult]:
        """Return AI category suggestions for unassigned transactions.

        When ``on_suggestion`` is provided the callback is invoked from the
        classification loop as soon as an individual suggestion becomes
        available, allowing the UI to update incrementally.
        """

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
        if preferred_order:
            remaining = {txn.transaction_id: txn for txn in unassigned if txn.transaction_id}
            ordered_unassigned: list[Transaction] = []
            for txn_id in preferred_order:
                txn = remaining.pop(txn_id, None)
                if txn:
                    ordered_unassigned.append(txn)
            if remaining:
                for txn in unassigned:
                    if txn.transaction_id and txn.transaction_id in remaining:
                        ordered_unassigned.append(txn)
                        remaining.pop(txn.transaction_id, None)
            if ordered_unassigned:
                unassigned = ordered_unassigned
        if not unassigned:
            log("No unassigned transactions to classify.")
            return {}

        log(
            f"Attempting to classify {len(unassigned)} unassigned "
            f"transaction{'s' if len(unassigned) != 1 else ''}."
        )

        self._latest_suggestions = {}
        suggestions: dict[str, ClassificationResult] = {}
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
            suggestions[txn.transaction_id] = result
            self._latest_suggestions[txn.transaction_id] = result
            if on_suggestion:
                on_suggestion(txn.transaction_id, result)
            log(
                "Recorded suggestion '{name}' (confidence {confidence:.0%}) for "
                "transaction '{txn_label}'.".format(
                    name=result.category_name,
                    confidence=result.confidence,
                    txn_label=txn_label,
                )
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
    def _import_key(
        self,
        *,
        reference: Optional[str],
        account_id: Optional[str],
        occurred_on: str,
        amount: Decimal,
        description: str,
    ) -> tuple[str, str, str, str, str]:
        if reference:
            return ("reference", reference.strip())
        account = (account_id or "").strip()
        return (
            "details",
            account,
            occurred_on,
            str(amount),
            description.strip().lower(),
        )

    def _existing_transaction_keys(self) -> set[tuple[str, str, str, str, str]]:
        keys: set[tuple[str, str, str, str, str]] = set()
        for txn in self.ledger.transactions:
            keys.add(
                self._import_key(
                    reference=txn.reference,
                    account_id=txn.account_id,
                    occurred_on=txn.occurred_on,
                    amount=txn.amount,
                    description=txn.description,
                )
            )
        return keys

    def _csv_transaction_key(self, record: CSVTransaction) -> tuple[str, str, str, str, str]:
        return self._import_key(
            reference=record.reference,
            account_id=record.account_id,
            occurred_on=record.occurred_on,
            amount=record.amount,
            description=record.description,
        )

    def create_csv_import_preview(
        self,
        path: str | Path,
        *,
        skip_existing: bool = True,
    ) -> CSVImportPreview:
        """Analyse a CSV file and determine which transactions would be imported."""

        csv_transactions = list(read_transactions_from_csv(path))
        if not csv_transactions:
            return CSVImportPreview(Path(path), [], [])

        existing_keys = self._existing_transaction_keys() if skip_existing else set()
        new_transactions: List[CSVTransaction] = []
        duplicates: List[CSVTransaction] = []

        for record in csv_transactions:
            key = self._csv_transaction_key(record)
            if skip_existing and key in existing_keys:
                duplicates.append(record)
                continue

            if skip_existing:
                existing_keys.add(key)
            new_transactions.append(record)

        return CSVImportPreview(Path(path), new_transactions, duplicates)

    def import_transactions_from_csv(
        self,
        source: str | Path | CSVImportPreview,
        *,
        category_by_account: Optional[dict[str, str]] = None,
        default_category_id: Optional[str] = None,
        skip_existing: bool = True,
    ) -> int:
        """Import transactions from a Rabobank CSV export."""
        category_by_account = category_by_account or {}
        if isinstance(source, CSVImportPreview):
            preview = source
        else:
            preview = self.create_csv_import_preview(
                source,
                skip_existing=skip_existing,
            )

        if not preview.new_transactions:
            return 0

        imported = 0
        for record in preview.new_transactions:
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
            imported += 1

        if imported:
            self._notify()
        return imported

    def _get_transfer_category_id(self) -> str:
        for category_id, category in self.ledger.categories.items():
            if category.name.lower() == self.ledger.TRANSFER_CATEGORY_NAME.lower():
                return category_id
        category = self.ledger.add_category(self.ledger.TRANSFER_CATEGORY_NAME, Decimal("0.00"))
        return category.category_id

    def import_credit_card_statement(
        self,
        path: str | Path,
        *,
        confirm_replacement: Callable[[Transaction, CSVTransaction], bool],
    ) -> int:
        """Import a credit-card statement and replace matching counterbookings."""

        statement_rows = read_credit_card_statement(path)
        if not statement_rows:
            return 0

        match_window = timedelta(days=3)
        counterbookings: list[tuple[Transaction, CSVTransaction]] = []
        candidate_pairs: set[tuple[str, int]] = set()
        quantize_amount = Decimal("0.01")

        default_card_account_id = statement_rows[0].account_id or "CREDIT-CARD"
        existing_transactions = list(self.ledger.transactions)
        for index, record in enumerate(statement_rows):
            statement_amount = record.amount.quantize(quantize_amount)
            if statement_amount == 0:
                continue
            ledger_amount = (-statement_amount).quantize(quantize_amount)
            expected_counter_amounts = {ledger_amount}
            if statement_amount < 0:
                expected_counter_amounts.add((-ledger_amount))
            record_date = date.fromisoformat(record.occurred_on)
            record_account_id = record.account_id or default_card_account_id
            for txn in existing_transactions:
                txn_amount = txn.amount.quantize(quantize_amount)
                if txn_amount == 0:
                    continue
                txn_account_id = (txn.account_id or "").strip()
                if (
                    record.reference
                    and txn.reference == record.reference
                    and txn_account_id in {record_account_id, default_card_account_id}
                ):
                    continue
                if txn_account_id in {record_account_id, default_card_account_id}:
                    continue
                if txn_amount not in expected_counter_amounts:
                    continue
                txn_date = date.fromisoformat(txn.occurred_on)
                if abs((txn_date - record_date).days) <= match_window.days:
                    pair_key = (txn.transaction_id, index)
                    if pair_key in candidate_pairs:
                        continue
                    counterbookings.append((txn, record))
                    candidate_pairs.add(pair_key)

        removed_ids: set[str] = set()
        for txn, record in counterbookings:
            if txn.transaction_id in removed_ids:
                continue
            if confirm_replacement(txn, record):
                removed_ids.add(txn.transaction_id)

        if removed_ids:
            self.ledger.transactions = [
                txn
                for txn in self.ledger.transactions
                if txn.transaction_id not in removed_ids
            ]
            self.ledger.detect_internal_transfers()
            self.ledger.recalculate_actuals()

        imported = 0
        transfer_category_id: Optional[str] = None
        positive_transactions: List[Transaction] = []

        existing_reference_amounts = {
            txn.reference: txn.amount.quantize(quantize_amount)
            for txn in self.ledger.transactions
            if txn.reference
        }

        default_account_id = default_card_account_id
        default_account_name = statement_rows[0].account_name or "Credit Card"

        for record in statement_rows:
            ledger_amount = (-record.amount).quantize(quantize_amount)
            if record.reference:
                existing_amount = existing_reference_amounts.get(record.reference)
                if existing_amount is not None and existing_amount == ledger_amount:
                    continue
            txn = self.ledger.record_transaction(
                description=record.description,
                amount=ledger_amount,
                category_id=None,
                occurred_on=record.occurred_on,
                account_id=record.account_id or default_account_id,
                account_name=record.account_name or default_account_name,
                counterparty=record.counterparty,
                reference=record.reference,
                company=record.company,
            )
            if record.reference:
                existing_reference_amounts[record.reference] = ledger_amount
            if ledger_amount > 0:
                if transfer_category_id is None:
                    transfer_category_id = self._get_transfer_category_id()
                positive_transactions.append(txn)
            imported += 1

        if transfer_category_id and positive_transactions:
            for txn in positive_transactions:
                txn.category_id = transfer_category_id
            self.ledger.recalculate_actuals()
        elif imported:
            self.ledger.recalculate_actuals()

        if imported or removed_ids:
            self._notify()
        return imported
