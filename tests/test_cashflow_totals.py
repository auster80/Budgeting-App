"""Tests for income and expense aggregation helpers."""

from decimal import Decimal

from budgeting_app.models import BudgetLedger, Transaction
from budgeting_app.viewmodels import BudgetViewModel


def test_income_and_expense_totals_split_by_sign() -> None:
    viewmodel = BudgetViewModel()
    ledger = BudgetLedger()
    ledger.transactions = [
        Transaction(description="Salary", amount="5000"),
        Transaction(description="Refund", amount="50"),
        Transaction(description="Groceries", amount="-120"),
        Transaction(description="Rent", amount="-1800"),
    ]
    viewmodel.ledger = ledger

    income, expenses = viewmodel.income_and_expense_totals()

    assert income == Decimal("5050")
    assert expenses == Decimal("1920")


def test_income_and_expense_totals_ignore_transfers() -> None:
    viewmodel = BudgetViewModel()
    ledger = BudgetLedger()
    ledger.transactions = [
        Transaction(description="Savings", amount="1000", is_internal_transfer=True),
        Transaction(description="Savings offset", amount="-1000", is_internal_transfer=True),
        Transaction(description="Freelance", amount="200"),
        Transaction(description="Supplies", amount="-25"),
    ]
    viewmodel.ledger = ledger

    income, expenses = viewmodel.income_and_expense_totals()

    assert income == Decimal("200")
    assert expenses == Decimal("25")
