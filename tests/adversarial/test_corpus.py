"""Tests for the adversarial injection corpus — structural validation.

Verifies that every corpus case is well-formed (required fields present,
expected_blocked is a boolean, category is a known value). The corpus
itself is a specification document; the actual blocking tests live in
tests/gates/test_gate_safety.py.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

CORPUS_PATH = Path(__file__).parent / "injection_corpus.jsonl"
VALID_CATEGORIES = {
    "prompt_injection",
    "token_forgery",
    "scope_escalation",
    "data_exfiltration",
    "cache_poisoning",
}

_CASES = [json.loads(line) for line in CORPUS_PATH.read_text().splitlines() if line.strip()]


@pytest.mark.parametrize("case", _CASES, ids=[c["id"] for c in _CASES])
def test_corpus_case_schema(case: dict) -> None:
    """Each corpus case must have all required fields with correct types."""
    assert "id" in case, "Missing 'id'"
    assert "category" in case, f"{case['id']}: missing 'category'"
    assert "description" in case, f"{case['id']}: missing 'description'"
    assert "input" in case, f"{case['id']}: missing 'input'"
    assert "expected_blocked" in case, f"{case['id']}: missing 'expected_blocked'"
    assert isinstance(case["expected_blocked"], bool), f"{case['id']}: expected_blocked must be bool"
    assert case["category"] in VALID_CATEGORIES, (
        f"{case['id']}: unknown category '{case['category']}'"
    )


def test_corpus_has_minimum_cases():
    assert len(_CASES) >= 30, f"Corpus has only {len(_CASES)} cases — need at least 30"


def test_corpus_ids_unique():
    ids = [c["id"] for c in _CASES]
    assert len(ids) == len(set(ids)), "Duplicate case IDs in corpus"


def test_corpus_covers_all_categories():
    seen = {c["category"] for c in _CASES}
    assert seen == VALID_CATEGORIES, f"Missing categories: {VALID_CATEGORIES - seen}"


def test_corpus_blocked_cases_exist():
    blocked = [c for c in _CASES if c["expected_blocked"]]
    assert len(blocked) >= 5, "Need at least 5 'expected_blocked=true' cases"
