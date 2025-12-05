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


def test_determine_report_date_allows_override():
    """Report date helper should be reproducible with a supplied time."""

    from src import daily_pipeline
    now = daily_pipeline.datetime(2024, 5, 1, 7, 0, tzinfo=daily_pipeline.timezone.utc)
    assert daily_pipeline.determine_report_date(now) == now.date() - daily_pipeline.timedelta(days=1)

    now = daily_pipeline.datetime(2024, 5, 1, 14, 0, tzinfo=daily_pipeline.timezone.utc)
    assert daily_pipeline.determine_report_date(now) == now.date() - daily_pipeline.timedelta(days=1)


def test_time_window_for_date_spans_full_day():
    """The window helper should cover the full local calendar day."""

    from src import daily_pipeline

    report_date = daily_pipeline.datetime(2024, 5, 10).date()
    start_local, end_local = daily_pipeline.time_window_for_date(report_date)

    assert start_local.hour == 0 and start_local.minute == 0
    assert end_local - start_local == daily_pipeline.timedelta(days=1)
    assert start_local.date() == report_date
    # End should roll into the next local day
    assert end_local.date() == report_date + daily_pipeline.timedelta(days=1)


def test_latest_report_date_detects_most_recent(tmp_path):
    """Helper should parse the latest ISO date from report filenames."""

    from src import daily_pipeline

    daily_dir = tmp_path / "outputs" / "daily"
    daily_dir.mkdir(parents=True)
    (daily_dir / "venezuela_2024-05-01.md").write_text("one", encoding="utf-8")
    (daily_dir / "venezuela_2024-05-03.md").write_text("two", encoding="utf-8")
    (daily_dir / "ignored.txt").write_text("skip", encoding="utf-8")

    assert daily_pipeline.latest_report_date(str(daily_dir)) == daily_pipeline.datetime(2024, 5, 3).date()
