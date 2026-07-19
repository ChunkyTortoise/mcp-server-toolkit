"""Substrate auditor: inline-XML dispatch vs typed tool-call API.

Runs the stdlib-only substrate auditor against fixture configs and transcripts.
CI picks this up via the main pytest job in .github/workflows/ci.yml.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mcp_toolkit.security.substrate_auditor import audit_path, main

SAMPLES = Path(__file__).parent / "samples"
INLINE_XML_CONFIG = SAMPLES / "inline-xml-config.json"
TYPED_CONFIG = SAMPLES / "typed-toolcall-config.json"
INLINE_XML_TRANSCRIPT = SAMPLES / "before-inline-xml-transcript.jsonl"
TYPED_TRANSCRIPT = SAMPLES / "after-typed-toolcall-transcript.jsonl"


class TestSubstrateAuditorConfigs:
    def test_inline_xml_config_is_high_risk(self) -> None:
        result = audit_path(INLINE_XML_CONFIG)
        assert result["substrate"] == "inline-xml-dispatch"
        assert result["risk"] == "high"

    def test_typed_config_is_low_risk(self) -> None:
        result = audit_path(TYPED_CONFIG)
        assert result["substrate"] == "typed-toolcall-api"
        assert result["risk"] == "low"

    def test_inline_xml_cli_exit_code(self) -> None:
        assert main([str(INLINE_XML_CONFIG)]) == 1

    def test_typed_cli_exit_code(self) -> None:
        assert main([str(TYPED_CONFIG)]) == 0

    def test_expect_risk_high_passes(self) -> None:
        assert main([str(INLINE_XML_CONFIG), "--expect-risk", "high"]) == 0

    def test_expect_risk_low_passes(self) -> None:
        assert main([str(TYPED_CONFIG), "--expect-risk", "low"]) == 0

    def test_expect_risk_mismatch_fails(self) -> None:
        assert main([str(INLINE_XML_CONFIG), "--expect-risk", "low"]) == 1


class TestSubstrateAuditorTranscripts:
    def test_inline_xml_transcript_is_high_risk(self) -> None:
        result = audit_path(INLINE_XML_TRANSCRIPT)
        assert result["substrate"] == "inline-xml-dispatch"
        assert result["risk"] == "high"

    def test_typed_transcript_is_low_risk(self) -> None:
        result = audit_path(TYPED_TRANSCRIPT)
        assert result["substrate"] == "typed-toolcall-api"
        assert result["risk"] == "low"


def test_missing_file_returns_exit_code_2() -> None:
    assert main(["/nonexistent/mcp-config.json"]) == 2


def test_audit_path_missing_file_raises() -> None:
    with pytest.raises(FileNotFoundError):
        audit_path("/nonexistent/mcp-config.json")
