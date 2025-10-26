from decimal import Decimal
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from budgeting_app.models import BudgetLedger


def _get_transfer_category(ledger: BudgetLedger):
    return next(
        (
            category
            for category in ledger.categories.values()
            if category.name == ledger.TRANSFER_CATEGORY_NAME
        ),
        None,
    )


def test_detects_transfer_between_accounts():
    ledger = BudgetLedger()

    debit = ledger.record_transaction(
        description="Transfer to savings",
        amount=Decimal("-150.00"),
        category_id=None,
        occurred_on="2024-01-01",
        transaction_id="REF-001",
        account_id="ACC-001",
        account_name="Main",
        counterparty="Savings",
        reference="REF-001",
    )

    credit = ledger.record_transaction(
        description="Transfer from main",
        amount=Decimal("150.00"),
        category_id=None,
        occurred_on="2024-01-01",
        transaction_id="REF-001-REV",
        account_id="ACC-002",
        account_name="Savings",
        counterparty="Main",
        reference="REF-001",
    )

    transfer_category = _get_transfer_category(ledger)
    assert transfer_category is not None
    assert debit.is_internal_transfer is True
    assert credit.is_internal_transfer is True
    assert debit.transfer_partner_id == credit.transaction_id
    assert credit.transfer_partner_id == debit.transaction_id
    assert debit.category_id == transfer_category.category_id
    assert credit.category_id == transfer_category.category_id
    assert transfer_category.actual_amount == Decimal("0.00")


def test_transfer_flags_cleared_when_pair_missing():
    ledger = BudgetLedger()
    debit = ledger.record_transaction(
        description="Transfer to savings",
        amount=Decimal("-150.00"),
        category_id=None,
        occurred_on="2024-01-01",
        transaction_id="REF-002",
        account_id="ACC-001",
        account_name="Main",
        counterparty="Savings",
        reference="REF-002",
    )

    ledger.record_transaction(
        description="Transfer from main",
        amount=Decimal("150.00"),
        category_id=None,
        occurred_on="2024-01-01",
        transaction_id="REF-002-REV",
        account_id="ACC-002",
        account_name="Savings",
        counterparty="Main",
        reference="REF-002",
    )

    # Remove the credit leg and trigger detection.
    ledger.transactions = [debit]
    ledger.detect_internal_transfers()
    ledger.recalculate_actuals()

    assert debit.is_internal_transfer is False
    assert debit.transfer_partner_id is None
    assert debit.category_id is None
