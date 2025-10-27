from __future__ import annotations

import csv
from decimal import Decimal
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from budgeting_app.csv_importer import CSVTransaction, read_credit_card_statement
from budgeting_app.models import BudgetLedger
from budgeting_app.viewmodels import BudgetViewModel


def _write_sample_credit_card_csv(path: Path) -> Path:
    content = """Datum,Omschrijving,Bedrag,Kaartnummer,Transactie ID
2024-03-01,Online Store,"300,00",CARD-123,CC1
2024-03-02,Refund,"-50,00",CARD-123,CC2
2024-03-03,Automatic Payment,"-200,00",CARD-123,CC3
2024-03-04,Coffee Shop,"20,00",CARD-123,CC4
"""
    target = path / "credit_card.csv"
    target.write_text(content, encoding="utf-8")
    return target


def test_read_credit_card_statement_accepts_us_formatted_dates(tmp_path: Path) -> None:
    csv_path = tmp_path / "credit_card_us.csv"
    csv_path.write_text(
        """Datum,Omschrijving,Bedrag
09/22/2025,Amazon,"4,91"
""",
        encoding="utf-8",
    )

    transactions = read_credit_card_statement(csv_path)

    assert len(transactions) == 1
    assert transactions[0].occurred_on == "2025-09-22"
    assert transactions[0].amount == Decimal("4.91")


def test_read_credit_card_statement_parses_rows(tmp_path: Path) -> None:
    csv_path = _write_sample_credit_card_csv(tmp_path)
    transactions = read_credit_card_statement(csv_path)

    assert len(transactions) == 4
    assert transactions[0].amount == Decimal("300.00")
    assert transactions[0].occurred_on == "2024-03-01"
    assert transactions[0].account_id == "CARD-123"
    assert transactions[1].amount == Decimal("-50.00")


def test_import_credit_card_statement_replaces_counterbookings(tmp_path: Path) -> None:
    csv_path = _write_sample_credit_card_csv(tmp_path)

    ledger = BudgetLedger()
    payment_category = ledger.add_category("Credit Card Payment", Decimal("0.00")).category_id
    existing = [
        ledger.record_transaction(
            description="Card charge",
            amount=Decimal("-300.00"),
            category_id=payment_category,
            occurred_on="2024-03-02",
            transaction_id="BANK-1",
        ),
        ledger.record_transaction(
            description="Card refund",
            amount=Decimal("50.00"),
            category_id=payment_category,
            occurred_on="2024-03-04",
            transaction_id="BANK-2",
        ),
        ledger.record_transaction(
            description="Card payment",
            amount=Decimal("200.00"),
            category_id=payment_category,
            occurred_on="2024-03-05",
            transaction_id="BANK-3",
        ),
        ledger.record_transaction(
            description="Coffee shop",
            amount=Decimal("-20.00"),
            category_id=payment_category,
            occurred_on="2024-03-06",
            transaction_id="BANK-4",
        ),
    ]

    viewmodel = BudgetViewModel()
    viewmodel.ledger = ledger

    confirm_calls: list[tuple[str, CSVTransaction]] = []

    def confirm_replacement(transaction, record: CSVTransaction) -> bool:
        confirm_calls.append((transaction.transaction_id, record))
        return True

    imported = viewmodel.import_credit_card_statement(
        csv_path,
        confirm_replacement=confirm_replacement,
    )

    assert imported == 4
    assert {call[0] for call in confirm_calls} == {txn.transaction_id for txn in existing}

    transaction_ids = {txn.transaction_id for txn in viewmodel.ledger.transactions}
    for txn in existing:
        assert txn.transaction_id not in transaction_ids

    by_reference = {txn.reference: txn for txn in viewmodel.ledger.transactions}
    assert by_reference["CC1"].amount == Decimal("-300.00")
    assert by_reference["CC4"].amount == Decimal("-20.00")
    assert by_reference["CC2"].amount == Decimal("50.00")
    assert by_reference["CC3"].amount == Decimal("200.00")

    transfer_category = next(
        category_id
        for category_id, category in viewmodel.ledger.categories.items()
        if category.name == viewmodel.ledger.TRANSFER_CATEGORY_NAME
    )
    assert by_reference["CC2"].category_id == transfer_category
    assert by_reference["CC3"].category_id == transfer_category
    assert by_reference["CC1"].category_id is None

    assert viewmodel.ledger.categories[payment_category].actual_amount == Decimal("0.00")
    assert len(viewmodel.ledger.transactions) == 4


def test_import_credit_card_statement_prompts_all_counterbooking_candidates(
    tmp_path: Path,
) -> None:
    csv_path = _write_sample_credit_card_csv(tmp_path)

    ledger = BudgetLedger()
    ledger.record_transaction(
        description="Potential match 1",
        amount=Decimal("-300.00"),
        category_id=None,
        occurred_on="2024-03-02",
        transaction_id="BANK-1",
    )
    ledger.record_transaction(
        description="Potential match 2",
        amount=Decimal("-300.00"),
        category_id=None,
        occurred_on="2024-03-04",
        transaction_id="BANK-2",
    )

    viewmodel = BudgetViewModel()
    viewmodel.ledger = ledger

    confirm_calls: list[tuple[str, str | None]] = []

    def confirm_replacement(transaction, record: CSVTransaction) -> bool:
        confirm_calls.append((transaction.transaction_id, record.reference))
        return False

    imported = viewmodel.import_credit_card_statement(
        csv_path,
        confirm_replacement=confirm_replacement,
    )

    assert imported == 4
    assert confirm_calls == [
        ("BANK-1", "CC1"),
        ("BANK-2", "CC1"),
    ]
    assert any(txn.transaction_id == "BANK-1" for txn in viewmodel.ledger.transactions)
    assert any(txn.transaction_id == "BANK-2" for txn in viewmodel.ledger.transactions)


def test_import_credit_card_statement_checks_additional_counterbookings_after_decline(
    tmp_path: Path,
) -> None:
    csv_path = _write_sample_credit_card_csv(tmp_path)

    ledger = BudgetLedger()
    first_match = ledger.record_transaction(
        description="Potential match 1",
        amount=Decimal("-300.00"),
        category_id=None,
        occurred_on="2024-03-02",
        transaction_id="BANK-1",
    )
    second_match = ledger.record_transaction(
        description="Potential match 2",
        amount=Decimal("-300.00"),
        category_id=None,
        occurred_on="2024-03-03",
        transaction_id="BANK-2",
    )

    viewmodel = BudgetViewModel()
    viewmodel.ledger = ledger

    confirmations: list[str] = []

    def confirm_replacement(transaction, record: CSVTransaction) -> bool:
        confirmations.append(transaction.transaction_id)
        return transaction.transaction_id == "BANK-2"

    imported = viewmodel.import_credit_card_statement(
        csv_path,
        confirm_replacement=confirm_replacement,
    )

    assert imported == 4
    assert confirmations == ["BANK-1", "BANK-2"]

    remaining_ids = {txn.transaction_id for txn in viewmodel.ledger.transactions}
    assert first_match.transaction_id in remaining_ids
    assert second_match.transaction_id not in remaining_ids


def test_import_credit_card_statement_matches_reference_from_other_account(
    tmp_path: Path,
) -> None:
    csv_path = _write_sample_credit_card_csv(tmp_path)

    ledger = BudgetLedger()
    ledger.record_transaction(
        description="Potential match",
        amount=Decimal("-300.00"),
        category_id=None,
        occurred_on="2024-03-02",
        transaction_id="BANK-1",
        account_id="NL00RABO0000000000",
        reference="CC1",
    )

    viewmodel = BudgetViewModel()
    viewmodel.ledger = ledger

    confirmed: list[str] = []

    def confirm_replacement(transaction, record: CSVTransaction) -> bool:
        confirmed.append(transaction.transaction_id)
        return True

    imported = viewmodel.import_credit_card_statement(
        csv_path,
        confirm_replacement=confirm_replacement,
    )

    assert imported == 4
    assert confirmed == ["BANK-1"]

    by_reference = {txn.reference: txn for txn in viewmodel.ledger.transactions}
    assert by_reference["CC1"].amount == Decimal("-300.00")
    assert "BANK-1" not in {txn.transaction_id for txn in viewmodel.ledger.transactions}


def test_import_credit_card_statement_without_matching_counterbooking(tmp_path: Path) -> None:
    csv_path = _write_sample_credit_card_csv(tmp_path)

    ledger = BudgetLedger()
    viewmodel = BudgetViewModel()
    viewmodel.ledger = ledger

    confirm_called = False

    def confirm_replacement(*_args, **_kwargs) -> bool:  # pragma: no cover - should not be called
        nonlocal confirm_called
        confirm_called = True
        return False

    imported = viewmodel.import_credit_card_statement(
        csv_path,
        confirm_replacement=confirm_replacement,
    )

    assert imported == 4
    assert confirm_called is False

    by_reference = {txn.reference: txn for txn in viewmodel.ledger.transactions}
    assert by_reference["CC1"].amount == Decimal("-300.00")
    assert by_reference["CC4"].amount == Decimal("-20.00")
    assert by_reference["CC2"].amount == Decimal("50.00")
    assert by_reference["CC3"].amount == Decimal("200.00")


def test_import_credit_card_statement_skips_existing_references(tmp_path: Path) -> None:
    csv_path = _write_sample_credit_card_csv(tmp_path)

    ledger = BudgetLedger()
    viewmodel = BudgetViewModel()
    viewmodel.ledger = ledger

    imported_first = viewmodel.import_credit_card_statement(
        csv_path,
        confirm_replacement=lambda *_args: True,
    )
    assert imported_first == 4

    confirm_called = False

    def confirm_replacement(*_args, **_kwargs) -> bool:  # pragma: no cover - should not be called
        nonlocal confirm_called
        confirm_called = True
        return False

    imported_second = viewmodel.import_credit_card_statement(
        csv_path,
        confirm_replacement=confirm_replacement,
    )

    assert imported_second == 0
    assert confirm_called is False


def test_import_credit_card_statement_only_matches_opposite_signs(tmp_path: Path) -> None:
    csv_path = _write_sample_credit_card_csv(tmp_path)

    ledger = BudgetLedger()
    existing = ledger.record_transaction(
        description="Existing same-sign transaction",
        amount=Decimal("300.00"),
        category_id=None,
        occurred_on="2024-03-02",
        transaction_id="BANK-SAME",
    )

    viewmodel = BudgetViewModel()
    viewmodel.ledger = ledger

    confirm_called = False

    def confirm_replacement(*_args, **_kwargs) -> bool:  # pragma: no cover - should not be called
        nonlocal confirm_called
        confirm_called = True
        return True

    imported = viewmodel.import_credit_card_statement(
        csv_path,
        confirm_replacement=confirm_replacement,
    )

    assert imported == 4
    assert confirm_called is False
    assert any(
        txn.transaction_id == existing.transaction_id
        for txn in viewmodel.ledger.transactions
    )


def test_import_credit_card_statement_ignores_same_account_transactions(
    tmp_path: Path,
) -> None:
    csv_path = _write_sample_credit_card_csv(tmp_path)

    ledger = BudgetLedger()
    existing = ledger.record_transaction(
        description="Existing credit card charge",
        amount=Decimal("-300.00"),
        category_id=None,
        occurred_on="2024-03-02",
        transaction_id="CARD-LEDGER",
        account_id="CARD-123",
    )

    viewmodel = BudgetViewModel()
    viewmodel.ledger = ledger

    confirm_called = False

    def confirm_replacement(*_args, **_kwargs) -> bool:  # pragma: no cover - should not be called
        nonlocal confirm_called
        confirm_called = True
        return True

    imported = viewmodel.import_credit_card_statement(
        csv_path,
        confirm_replacement=confirm_replacement,
    )

    assert imported == 4
    assert confirm_called is False
    assert any(
        txn.transaction_id == existing.transaction_id
        for txn in viewmodel.ledger.transactions
    )


def test_import_credit_card_statement_links_card_payment_counterbooking(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "amex_statement.csv"
    fieldnames = [
        "Datum",
        "Omschrijving",
        "Kaartlid",
        "Rekening #",
        "Bedrag",
        "Aanvullende informatie",
        "Vermeld op uw rekeningoverzicht als",
        "Adres",
        "Plaats",
        "Postcode",
        "Land",
        "Referentie",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow(
            {
                "Datum": "09/29/2025",
                "Omschrijving": "HARTELIJK BEDANKT VOOR UW BETALING",
                "Kaartlid": "MARTIN EDLAUER",
                "Rekening #": "-71009",
                "Bedrag": "-3883,15",
                "Aanvullende informatie": "",
                "Vermeld op uw rekeningoverzicht als": "",
                "Adres": "",
                "Plaats": "",
                "Postcode": "",
                "Land": "",
                "Referentie": "10000000010924999476800",
            }
        )

    ledger = BudgetLedger()
    payment_txn = ledger.record_transaction(
        description="Transfer to American Express Europe S.A.",
        amount=Decimal("-3883.15"),
        category_id=None,
        occurred_on="2025-09-30",
        transaction_id="BANK-AMEX",
        account_id="NL94RABO0338195653",
    )

    viewmodel = BudgetViewModel()
    viewmodel.ledger = ledger

    confirmed: list[tuple[str, str]] = []

    def confirm_replacement(transaction, record: CSVTransaction) -> bool:
        confirmed.append((transaction.transaction_id, record.reference or ""))
        return True

    imported = viewmodel.import_credit_card_statement(
        csv_path,
        confirm_replacement=confirm_replacement,
    )

    assert imported == 1
    assert confirmed == [(payment_txn.transaction_id, "10000000010924999476800")]

    remaining_ids = {txn.transaction_id for txn in viewmodel.ledger.transactions}
    assert payment_txn.transaction_id not in remaining_ids

    by_reference = {txn.reference: txn for txn in viewmodel.ledger.transactions}
    assert by_reference["10000000010924999476800"].amount == Decimal("3883.15")
