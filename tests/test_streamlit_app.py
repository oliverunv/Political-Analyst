"""Smoke tests for :mod:`streamlit_app`.

Because the Streamlit UI uses many interactive calls, these tests
replace the real :mod:`streamlit` module with a tiny stub so that the
module can be imported and helper functions exercised without needing a
running web app.
"""

import importlib
import sys


class _DummyContext:
    def __enter__(self):
        return None

    def __exit__(self, exc_type, exc, tb):
        return False


class _DummyStreamlit:
    """Lightweight stand-in for :mod:`streamlit` used during imports."""

    def __init__(self):
        class _SessionState(dict):
            def __getattr__(self, key):
                return self.get(key)

            def __setattr__(self, key, value):
                self[key] = value

        self.session_state = _SessionState()

    # Decorators -----------------------------------------------------
    def cache_data(self, ttl=None):
        def decorator(fn):
            return fn

        return decorator

    # Layout / widgets -----------------------------------------------
    def tabs(self, labels):
        return [_DummyContext() for _ in labels]

    def chat_message(self, role):
        return _DummyContext()

    def spinner(self, *args, **kwargs):
        return _DummyContext()

    def columns(self, cols):
        return [self] * len(cols)

    def button(self, *args, **kwargs):
        return False

    def selectbox(self, *args, **kwargs):
        options = kwargs.get("options") or (len(args) > 1 and args[1]) or []
        if not options:
            return None
        index = kwargs.get("index", 0)
        return options[index]

    def radio(self, *args, **kwargs):
        options = kwargs.get("options") or (len(args) > 1 and args[1]) or []
        return options[0] if options else None

    def text_input(self, *args, **kwargs):
        return kwargs.get("value", "")

    def text_area(self, *args, **kwargs):
        return kwargs.get("value", "")

    def checkbox(self, *args, **kwargs):
        return kwargs.get("value", False)

    def chat_input(self, *args, **kwargs):
        return None

    # Generic no-op handlers -----------------------------------------
    def __getattr__(self, name):
        def noop(*args, **kwargs):
            return None

        return noop


def _install_streamlit_stub():
    sys.modules["streamlit"] = _DummyStreamlit()


def test_streamlit_app_imports_with_stub():
    """The Streamlit app should import cleanly when the UI is stubbed."""

    _install_streamlit_stub()

    import streamlit_app

    importlib.reload(streamlit_app)


def test_load_recent_reasoning_handles_missing_file(tmp_path, monkeypatch):
    """Helper should return a friendly message when no log exists."""

    _install_streamlit_stub()
    monkeypatch.chdir(tmp_path)

    import streamlit_app

    assert "No reasoning logs" in streamlit_app.load_recent_reasoning()
