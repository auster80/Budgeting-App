"""ChatGPT-powered transaction classification helpers."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Callable, Iterable, List, Optional, Sequence, Tuple

from .models import Transaction

try:  # pragma: no cover - optional dependency error classes vary by version
    from openai import OpenAI
    from openai import APIError as _APIError  # type: ignore
    from openai import OpenAIError as _OpenAIError  # type: ignore
except Exception:  # pragma: no cover - OpenAI not available during type checking
    OpenAI = None  # type: ignore

    class _OpenAIError(Exception):
        """Fallback error when the OpenAI SDK is unavailable."""

    class _APIError(_OpenAIError):
        """Fallback error for compatibility with SDK signatures."""


@dataclass(frozen=True)
class ClassificationResult:
    """Represents the classifier's output for a transaction."""

    category_name: str
    confidence: float


class TransactionClassifier:
    """Generate transaction category suggestions using ChatGPT."""

    def __init__(
        self,
        *,
        model: str = "gpt-4o-mini",
        temperature: float = 0.2,
        max_feedback_examples: int = 12,
    ) -> None:
        self.model = model
        self.temperature = temperature
        self.max_feedback_examples = max_feedback_examples
        self._memory: dict[str, ClassificationResult] = {}
        api_key = os.getenv("OPENAI_API_KEY")
        self._client = OpenAI(api_key=api_key) if api_key and OpenAI else None

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def suggest_category(
        self,
        transaction: Transaction,
        existing_categories: Iterable[str],
        categorized_examples: Sequence[Tuple[Transaction, str]],
        *,
        logger: Optional[Callable[[str], None]] = None,
    ) -> Optional[ClassificationResult]:
        """Return a likely category for the transaction if one can be inferred."""

        categories = list(existing_categories)
        examples = list(categorized_examples)
        if logger:
            txn_label = transaction.description or transaction.transaction_id or "(unnamed)"
            logger(f"Classifying transaction '{txn_label}'.")
        if not categories and not examples:
            if logger:
                logger(
                    "Skipping classification: no existing categories or labelled examples available."
                )
            return None

        self._update_memory(examples)

        normalised_key = self._normalise_transaction(transaction)
        if normalised_key and normalised_key in self._memory:
            if logger:
                logger("Using memoised classification for recurring transaction.")
            return self._memory[normalised_key]

        if not self._client:
            # No API client configured; we can still benefit from memoised feedback.
            if logger:
                logger(
                    "OpenAI client is not configured; using heuristic fallback classifier."
                )
            fallback = self._heuristic_classification(
                transaction,
                categories,
                examples,
                normalised_key=normalised_key,
                logger=logger,
            )
            if fallback and logger:
                logger(
                    "Heuristic engine suggested category '{name}' with confidence "
                    "{confidence:.2f}.".format(
                        name=fallback.category_name, confidence=fallback.confidence
                    )
                )
            return fallback

        prompt = self._build_prompt(transaction, categories, examples)
        try:
            if logger:
                logger(f"Requesting classification from model '{self.model}'.")
            response = self._client.chat.completions.create(  # type: ignore[call-arg]
                model=self.model,
                temperature=self.temperature,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You categorise personal finance transactions for a budgeting app. "
                            "Return concise JSON only. Prefer categories that already exist "
                            "and be consistent with prior assignments."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
            )
        except (_APIError, _OpenAIError) as exc:  # pragma: no cover - network failure path
            if logger:
                logger(f"OpenAI API error: {exc}")
            return self._heuristic_classification(
                transaction,
                categories,
                examples,
                normalised_key=normalised_key,
                logger=logger,
            )

        content = self._extract_message_content(response)
        if not content:
            if logger:
                logger("Model response did not contain any content.")
            return self._heuristic_classification(
                transaction,
                categories,
                examples,
                normalised_key=normalised_key,
                logger=logger,
            )

        result = self._parse_response(content)
        if result and normalised_key:
            self._memory[normalised_key] = result
        if not result:
            if logger:
                logger("Failed to parse a valid classification result from the model response.")
            return self._heuristic_classification(
                transaction,
                categories,
                examples,
                normalised_key=normalised_key,
                logger=logger,
            )
        if logger:
            logger(
                "Model suggested category '{name}' with confidence {confidence:.2f}.".format(
                    name=result.category_name, confidence=result.confidence
                )
            )
        return result

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _extract_message_content(response: object) -> str:
        """Extract the assistant message content from an OpenAI response."""

        try:
            choices = getattr(response, "choices")
            if not choices:
                return ""
            message = choices[0].message
            return getattr(message, "content", "") or ""
        except AttributeError:  # pragma: no cover - defensive programming
            return ""

    def _update_memory(self, examples: Sequence[Tuple[Transaction, str]]) -> None:
        """Seed the classifier memory with known user-labelled transactions."""

        for txn, category_name in examples[-self.max_feedback_examples :]:
            key = self._normalise_transaction(txn)
            if key and category_name:
                self._memory[key] = ClassificationResult(category_name, 0.99)

    def _heuristic_classification(
        self,
        transaction: Transaction,
        existing_categories: Sequence[str],
        examples: Sequence[Tuple[Transaction, str]],
        *,
        normalised_key: str | None,
        logger: Optional[Callable[[str], None]] = None,
    ) -> Optional[ClassificationResult]:
        """Best-effort categorisation when ChatGPT is unavailable or unreliable."""

        result = self._match_from_examples(transaction, examples)
        if result:
            if normalised_key:
                self._memory[normalised_key] = result
            if logger:
                logger("Reused label from prior similar transaction.")
            return result

        result = self._match_from_keywords(transaction, existing_categories)
        if result:
            if normalised_key:
                self._memory[normalised_key] = result
            if logger:
                logger("Derived category from keyword heuristics.")
            return result

        if logger:
            logger("Heuristic engine could not determine a category.")
        return None

    def _match_from_examples(
        self, transaction: Transaction, examples: Sequence[Tuple[Transaction, str]]
    ) -> Optional[ClassificationResult]:
        """Look for similar, previously categorised transactions."""

        if not examples:
            return None

        transaction_tokens = self._tokenise_transaction(transaction)
        if not transaction_tokens:
            return None

        for example_txn, category_name in reversed(examples[-self.max_feedback_examples :]):
            example_tokens = self._tokenise_transaction(example_txn)
            if not example_tokens:
                continue
            if transaction_tokens & example_tokens:
                confidence = 0.85 if transaction.description == example_txn.description else 0.7
                return ClassificationResult(category_name, confidence)
        return None

    def _match_from_keywords(
        self, transaction: Transaction, existing_categories: Sequence[str]
    ) -> Optional[ClassificationResult]:
        """Apply keyword heuristics derived from publicly available data."""

        keyword_map: dict[str, str] = {
            "grocery": "Groceries",
            "supermarket": "Groceries",
            "aldi": "Groceries",
            "lidl": "Groceries",
            "tesco": "Groceries",
            "rent": "Rent",
            "mortgage": "Housing",
            "uber": "Transport",
            "lyft": "Transport",
            "taxi": "Transport",
            "fuel": "Auto & Transport",
            "petrol": "Auto & Transport",
            "shell": "Auto & Transport",
            "bp": "Auto & Transport",
            "starbucks": "Dining",
            "coffee": "Dining",
            "restaurant": "Dining",
            "dining": "Dining",
            "salary": "Income",
            "payroll": "Income",
            "bonus": "Income",
            "electric": "Utilities",
            "internet": "Utilities",
            "broadband": "Utilities",
            "water": "Utilities",
            "insurance": "Insurance",
            "pharmacy": "Healthcare",
            "chemist": "Healthcare",
            "gym": "Health & Fitness",
            "fitness": "Health & Fitness",
        }

        resolved_keywords = {key: self._resolve_category_name(value, existing_categories) for key, value in keyword_map.items()}

        text = " ".join(
            part
            for part in [
                transaction.description,
                transaction.counterparty,
                transaction.reference,
            ]
            if part
        ).lower()
        if not text:
            return None

        for keyword, category_name in resolved_keywords.items():
            if keyword in text:
                return ClassificationResult(category_name, 0.6)
        return None

    def _resolve_category_name(
        self, suggestion: str, existing_categories: Sequence[str]
    ) -> str:
        """Adjust a heuristic suggestion to match an existing category name."""

        suggestion_lower = suggestion.lower()
        for name in existing_categories:
            if name.lower() == suggestion_lower:
                return name
        for name in existing_categories:
            lowered = name.lower()
            if suggestion_lower in lowered or lowered in suggestion_lower:
                return name
        return suggestion

    @staticmethod
    def _tokenise_transaction(transaction: Transaction) -> set[str]:
        """Create a set of lowercase keywords representing a transaction."""

        text = " ".join(
            part
            for part in [
                transaction.description,
                transaction.counterparty,
                transaction.account_name,
                transaction.reference,
            ]
            if part
        ).lower()
        if not text:
            return set()
        tokens = re.split(r"[^a-z0-9]+", text)
        return {token for token in tokens if token}

    def _build_prompt(
        self,
        transaction: Transaction,
        existing_categories: List[str],
        examples: Sequence[Tuple[Transaction, str]],
    ) -> str:
        """Create a prompt that guides ChatGPT to classify the transaction."""

        category_section = (
            ", ".join(sorted({name for name in existing_categories if name}))
            if existing_categories
            else "(no existing categories)"
        )

        example_lines = []
        for txn, category_name in examples[-self.max_feedback_examples :]:
            parts = [
                f"Description: {txn.description or '-'}",
                f"Amount: {txn.amount}",
            ]
            if txn.counterparty:
                parts.append(f"Counterparty: {txn.counterparty}")
            if txn.account_name or txn.account_id:
                account = txn.account_name or txn.account_id
                parts.append(f"Account: {account}")
            if txn.reference:
                parts.append(f"Reference: {txn.reference}")
            parts.append(f"Category: {category_name}")
            example_lines.append("; ".join(parts))

        examples_section = "\n".join(example_lines) if example_lines else "(no prior examples)"

        txn_parts = [
            f"Description: {transaction.description or '-'}",
            f"Amount: {transaction.amount}",
        ]
        if transaction.counterparty:
            txn_parts.append(f"Counterparty: {transaction.counterparty}")
        if transaction.account_name or transaction.account_id:
            account = transaction.account_name or transaction.account_id
            txn_parts.append(f"Account: {account}")
        if transaction.reference:
            txn_parts.append(f"Reference: {transaction.reference}")
        txn_parts.append(f"Occurred On: {transaction.occurred_on}")
        transaction_section = "; ".join(txn_parts)

        return (
            "The budgeting app currently has the following categories: "
            f"{category_section}.\n"
            "Here are previously labelled transactions (use them as few-shot learning examples):\n"
            f"{examples_section}\n\n"
            "Classify the following transaction. If no category fits, suggest a concise new one.\n"
            f"Transaction: {transaction_section}\n\n"
            "Respond with strictly valid JSON: {\"category\": \"<name>\", \"confidence\": <number between 0 and 1>}"
        )

    @staticmethod
    def _parse_response(message: str) -> Optional[ClassificationResult]:
        """Parse the JSON payload returned by ChatGPT."""

        payload = TransactionClassifier._extract_json_object(message)
        if not payload:
            return None

        category = str(payload.get("category", "")).strip()
        if not category:
            return None

        try:
            confidence = float(payload.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
        confidence = max(0.0, min(1.0, confidence))
        return ClassificationResult(category_name=category, confidence=confidence)

    @staticmethod
    def _extract_json_object(message: str) -> Optional[dict]:
        """Extract the first JSON object embedded in a string."""

        match = re.search(r"\{.*\}", message, re.DOTALL)
        if not match:
            return None
        candidate = match.group(0)
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _normalise_transaction(transaction: Transaction) -> str:
        """Create a stable key for matching recurring transactions."""

        parts = [
            transaction.description,
            transaction.counterparty,
            transaction.account_name or transaction.account_id,
            transaction.reference,
        ]
        text = " ".join(part for part in parts if part)
        normalised = re.sub(r"\s+", " ", text.strip().lower())
        return normalised

