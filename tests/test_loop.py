# tests/test_loop.py
import pytest
from tiny_harness._loop import ErrorBudget, LoopDetector


def test_error_budget_records_errors():
    budget = ErrorBudget(max_total=10, max_consecutive=3)
    assert budget.record_error() is True
    assert budget.record_error() is True


def test_error_budget_exhausted_consecutive():
    budget = ErrorBudget(max_total=10, max_consecutive=2)
    assert budget.record_error() is True
    assert budget.record_error() is False


def test_error_budget_exhausted_total():
    budget = ErrorBudget(max_total=2, max_consecutive=10)
    assert budget.record_error() is True
    assert budget.record_error() is False


def test_error_budget_success_resets_consecutive():
    budget = ErrorBudget(max_total=10, max_consecutive=2)
    budget.record_error()
    budget.record_success()
    assert budget.record_error() is True
    assert budget.record_error() is False


def test_loop_detector_rejects_repeated_calls():
    detector = LoopDetector(max_repeats=2)
    args = {"path": "/tmp/x"}
    assert detector.check("read_file", args) is True
    assert detector.check("read_file", args) is False


def test_loop_detector_allows_different_args():
    detector = LoopDetector(max_repeats=2)
    assert detector.check("read_file", {"path": "/tmp/a"}) is True
    assert detector.check("read_file", {"path": "/tmp/b"}) is True
