"""Embed shared fixtures in the standalone offline HTML, using only the stdlib."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    fixtures = json.loads(Path(__file__).with_name("fixtures.json").read_text())
    preview = ROOT / "assets/agentic-rag-demo-preview.html"
    text = preview.read_text()
    start = text.index("    const chunks =")
    end = text.index("\n", start)
    preview.write_text(
        text[:start] + "    const chunks = " + json.dumps(fixtures) + ";" + text[end:]
    )


if __name__ == "__main__":
    main()
