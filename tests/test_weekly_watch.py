"""Smoke tests for :mod:`src.weekly_watch`.

These tests avoid network calls and simply exercise helper functions
with tiny, artificial inputs.
"""

import importlib
import pytest


def test_import_weekly_watch():
    """Module should import without crashing."""

    import src.weekly_watch as weekly_watch

    importlib.reload(weekly_watch)


def test_clean_rank_filters_relevant_items(tmp_path):
    """Only Venezuela-related articles with keywords should remain."""

    from src import weekly_watch

    sample = [
        {
            "title": "Venezuela politics",
            "description": "Detailed update mentioning sanctions and Caracas.",
            "content": "Extra context about PDVSA and opposition actors.",
        },
        {
            "title": "Unrelated",
            "description": "Brief note about another country.",
            "content": "Nothing about Venezuela here.",
        },
    ]

    curated = weekly_watch.clean_rank(sample)

    assert len(curated) == 1
    assert curated[0]["_score"] > 0


def test_build_context_truncates_when_cap_reached():
    """Context builder should stop once it would exceed the cap."""

    from src import weekly_watch

    items = [
        {"title": "One", "url": "u1", "description": "short desc", "content": "brief"},
        {"title": "Two", "url": "u2", "description": "another desc", "content": "more text"},
    ]

    context_text = weekly_watch.build_context(items, cap_chars=40)

    assert "One" in context_text
    assert "Two" not in context_text


def test_load_scenarios_missing_file_raises(tmp_path, monkeypatch):
    """Without the context file, a clear error should surface."""

    from src import weekly_watch

    # Point to a guaranteed-missing location
    monkeypatch.chdir(tmp_path)

    with pytest.raises(FileNotFoundError):
        weekly_watch.load_scenarios()


def test_load_context_handles_absent_file(tmp_path, monkeypatch):
    """When no context file exists, an empty string should be returned."""

    from src import weekly_watch

    monkeypatch.chdir(tmp_path)

    assert weekly_watch.load_context() == ""
