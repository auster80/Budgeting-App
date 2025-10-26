from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from budgeting_app.ai import ClassificationResult
from budgeting_app.app import BudgetApp


def _result(name: str, confidence: float) -> ClassificationResult:
    return ClassificationResult(category_name=name, confidence=confidence)


def test_merge_ai_suggestions_replaces_when_requested():
    existing = {
        "txn-1": _result("Groceries", 0.9),
        "txn-2": _result("Fuel", 0.8),
    }
    updates = {"txn-3": _result("Dining", 0.75)}

    merged = BudgetApp._merge_ai_suggestions(existing, updates, replace=True)

    assert merged == updates
    assert merged is not updates
    assert existing == {
        "txn-1": _result("Groceries", 0.9),
        "txn-2": _result("Fuel", 0.8),
    }


def test_merge_ai_suggestions_merges_without_replacing():
    existing = {
        "txn-1": _result("Groceries", 0.9),
        "txn-2": _result("Fuel", 0.8),
    }
    updates = {
        "txn-2": _result("Fuel", 0.85),
        "txn-3": _result("Dining", 0.75),
    }

    merged = BudgetApp._merge_ai_suggestions(existing, updates, replace=False)

    assert merged == {
        "txn-1": _result("Groceries", 0.9),
        "txn-2": _result("Fuel", 0.85),
        "txn-3": _result("Dining", 0.75),
    }
    # Original inputs are left unchanged
    assert existing["txn-2"].confidence == 0.8
    assert updates["txn-2"].confidence == 0.85
