"""The router example hides httpx request logs and exits when no key is set."""

from __future__ import annotations

import importlib.util
import logging
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "examples" / "multi_llm_router.py"
_KEY_NAMES = ("GEMINI_API_KEY", "OPENAI_API_KEY", "XAI_API_KEY")


def test_no_providers_exits_zero_with_one_line():
    env = os.environ.copy()
    for name in _KEY_NAMES:
        env.pop(name, None)
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout.splitlines() == ["No providers are configured."]


async def test_main_sets_httpx_logger_to_warning(monkeypatch, capsys):
    for name in _KEY_NAMES:
        monkeypatch.delenv(name, raising=False)
    spec = importlib.util.spec_from_file_location("multi_llm_router_example", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    logging.getLogger("httpx").setLevel(logging.INFO)
    await module.main()
    assert logging.getLogger("httpx").level == logging.WARNING
    assert capsys.readouterr().out.splitlines() == ["No providers are configured."]
