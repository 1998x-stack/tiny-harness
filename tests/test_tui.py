# tests/test_tui.py
from tiny_harness.tui import _rich_available


def test_rich_available():
    assert _rich_available() is True


def test_tui_module_imports():
    from tiny_harness.tui import run_tui_session
    assert run_tui_session is not None
