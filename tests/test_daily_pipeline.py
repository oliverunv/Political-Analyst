"""Smoke tests for :mod:`src.daily_pipeline`.

These keep to simple, readable checks so newcomers can see that the
main pipeline pieces import and handle tiny examples without error.
"""

import importlib


def test_import_daily_pipeline():
    """Module should import cleanly."""

    import src.daily_pipeline as daily_pipeline

    # Reload to ensure import side effects do not raise.
    importlib.reload(daily_pipeline)


def test_clean_rank_filters_and_scores(tmp_path):
    """Only Venezuela-related items with keywords are kept and scored."""

    from src import daily_pipeline

    sample = [
        {
            "title": "Venezuela economic update",
            "description": "Long description mentioning Maduro and PDVSA for testing.",
            "content": "More details about Venezuela and sanctions.",
        },
        {"title": "Other news", "description": "Short", "content": "Irrelevant."},
    ]

    curated = daily_pipeline.clean_rank(sample)

    assert len(curated) == 1  # only the Venezuela article should remain
    assert curated[0]["_score"] > 0


def test_build_context_respects_character_cap():
    """Context builder should stop adding pieces once the cap is reached."""

    from src import daily_pipeline

    items = [
        {"title": "One", "url": "u1", "description": "short desc", "content": "brief"},
        {"title": "Two", "url": "u2", "description": "another desc", "content": "more text"},
    ]

    # Cap that fits the first item but not the second
    context_text = daily_pipeline.build_context(items, cap_chars=40)

    assert "One" in context_text
    assert "Two" not in context_text
