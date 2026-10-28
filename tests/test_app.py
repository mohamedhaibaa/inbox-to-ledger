"""Step 8a: the Streamlit app runs in a headless browser-free test (Streamlit's AppTest), in offline
demo mode, so no API key or money is needed. Proves every tab renders and a sample is processed."""
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "app" / "streamlit_app.py")


def run_app(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")                  # empty: .env can't fill it -> offline demo
    return AppTest.from_file(APP, default_timeout=60).run()


def test_app_starts_with_four_tabs(monkeypatch):
    app = run_app(monkeypatch)
    assert not app.exception
    assert [t.label for t in app.tabs] == ["Process a document", "Reconciliation", "Review queue", "Ask"]


def test_processing_a_scan_shows_why_it_needs_review(monkeypatch):
    app = run_app(monkeypatch)
    app.selectbox[0].set_value("HD-0004.pdf (hard set)").run()
    app.button[0].click().run()
    assert "needs review" in app.subheader[0].value
    assert "OCR" in app.error[0].value


def test_reconciliation_tab_shows_breaks(monkeypatch):
    app = run_app(monkeypatch)
    app.selectbox[1].set_value("BS-0009").run()
    metrics = {m.label: m.value for m in app.metric}
    assert metrics["Fund"] == "FND-009" and metrics["Need review"] == "5"