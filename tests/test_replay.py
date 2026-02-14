"""Tests for the prompt replay engine."""

from __future__ import annotations

from nit.agents.replay import compute_diff


class TestComputeDiff:
    """Tests for the compute_diff utility."""

    def test_identical_texts_produce_empty_diff(self) -> None:
        assert compute_diff("hello\nworld\n", "hello\nworld\n") == ""

    def test_different_texts_produce_unified_diff(self) -> None:
        diff = compute_diff("line1\nline2\n", "line1\nchanged\n", "a", "b")
        assert "--- a" in diff
        assert "+++ b" in diff
        assert "-line2" in diff
        assert "+changed" in diff

    def test_custom_labels(self) -> None:
        diff = compute_diff("a\n", "b\n", "original (gpt-4o)", "replay (claude)")
        assert "original (gpt-4o)" in diff
        assert "replay (claude)" in diff

    def test_empty_to_content(self) -> None:
        diff = compute_diff("", "new content\n")
        assert "+new content" in diff

    def test_content_to_empty(self) -> None:
        diff = compute_diff("old content\n", "")
        assert "-old content" in diff

    def test_multiline_diff(self) -> None:
        text_a = "def test():\n    assert True\n    return 1\n"
        text_b = "def test():\n    assert False\n    return 2\n"
        diff = compute_diff(text_a, text_b)
        assert "-    assert True" in diff
        assert "+    assert False" in diff
        assert "-    return 1" in diff
        assert "+    return 2" in diff
