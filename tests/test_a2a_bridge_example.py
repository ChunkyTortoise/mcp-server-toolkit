"""The A2A example server listens on loopback."""

from pathlib import Path

_SERVER = Path(__file__).resolve().parents[1] / "examples" / "a2a_bridge" / "server.py"


def test_bridge_binds_loopback():
    text = _SERVER.read_text()
    assert 'host="0.0.0.0"' not in text
    assert 'host="127.0.0.1"' in text


def test_bridge_example_suppresses_credential_bearing_httpx_info_logs(monkeypatch, caplog):
    import logging
    import runpy
    import httpx

    logger = logging.getLogger("httpx")
    monkeypatch.setattr(logger, "level", logger.level)
    runpy.run_path(str(_SERVER), run_name="bridge_example_test")
    assert logger.level == logging.WARNING
    caplog.set_level(logging.INFO)
    with httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200))) as client:
        client.get("https://example.test/hook?token=bridge-query-sentinel")
    assert "bridge-query-sentinel" not in caplog.text
