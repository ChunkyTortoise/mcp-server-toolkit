"""Optional Streamlit interaction regression, runnable in an existing UI environment."""

from pathlib import Path
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[2]


def test_streamlit_form_retains_completed_result_and_handles_empty_input():

    at = AppTest.from_file(str(ROOT / "examples/agentic_rag/app.py")).run()
    assert not at.exception
    assert at.slider[0].max == 5
    at.text_input[0].set_value("What is RAG?")
    at.button[0].click().run()
    completed = at.session_state["completed_result"]
    assert len(completed["chunks"]) == 4
    at.slider[0].set_value(2).run()
    assert at.session_state["completed_result"] == completed
    assert "Settings changed" in at.warning[0].value
    assert len(at.expander) == 5
    at.button[0].click().run()
    assert len(at.session_state["completed_result"]["chunks"]) == 2
    assert not at.warning
    at.text_input[0].set_value("   ")
    at.button[0].click().run()
    assert "Enter a question" in at.info[-1].value
    assert len(at.session_state["completed_result"]["chunks"]) == 2
    assert not at.exception
