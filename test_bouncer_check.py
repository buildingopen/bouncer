"""Tests for skill/scripts/bouncer-check.py"""

import json
import os
import sys
from unittest import mock

import pytest

# Import the module under test
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "skill", "scripts"))
import importlib
bc = importlib.import_module("bouncer-check")


# --- Score parsing ---

class TestScoreParsing:
    def test_standard_format(self):
        result = "SCORE: 8/10\nISSUES:\n- missing tests\nVERDICT: FAIL"
        assert bc.parse_score(result) == 8

    def test_score_10(self):
        result = "SCORE: 10/10\nISSUES:\n- none\nVERDICT: PASS"
        assert bc.parse_score(result) == 10

    def test_score_1(self):
        result = "SCORE: 1/10\nISSUES:\n- everything wrong\nVERDICT: FAIL"
        assert bc.parse_score(result) == 1

    def test_unparseable_returns_none(self):
        result = "This is garbage output with no score"
        assert bc.parse_score(result) is None

    def test_malformed_score_line(self):
        result = "SCORE: notanumber/10\nISSUES:\n- bad\nVERDICT: FAIL"
        assert bc.parse_score(result) is None


# --- Fail-open on missing API key ---

class TestFailOpen:
    def test_no_api_key_prints_warning_exits_zero(self, capsys):
        with mock.patch.object(bc, "GEMINI_API_KEY", None):
            with pytest.raises(SystemExit) as exc_info:
                bc.main()
            assert exc_info.value.code == 0
            out = capsys.readouterr().out
            assert "WARNING" in out
            assert "GEMINI_API_KEY" in out


# --- Input JSON parsing ---

class TestInputParsing:
    def test_invalid_json_exits_one(self, capsys):
        with mock.patch.object(bc, "GEMINI_API_KEY", "fake-key"):
            with mock.patch("sys.stdin", mock.Mock(read=lambda: "not json {")):
                with pytest.raises(SystemExit) as exc_info:
                    bc.main()
                assert exc_info.value.code == 1
                out = capsys.readouterr().out
                assert "ERROR" in out

    def test_empty_input_exits_zero(self, capsys):
        """Empty diff + empty summary = nothing to audit."""
        with mock.patch.object(bc, "GEMINI_API_KEY", "fake-key"):
            with mock.patch("sys.stdin", mock.Mock(read=lambda: json.dumps({
                "assistant_text": "",
                "diff_stat": "",
                "diff_text": "",
                "context": "",
            }))):
                with pytest.raises(SystemExit) as exc_info:
                    bc.main()
                assert exc_info.value.code == 0
                out = capsys.readouterr().out
                assert "Nothing to audit" in out


# --- Output is human-readable ---

class TestOutputFormat:
    def test_output_is_human_readable(self, capsys):
        """Output should be human-readable text, not JSON."""
        gemini_response = "SCORE: 9/10\nISSUES:\n- minor gap in tests\nVERDICT: FAIL"
        with mock.patch.object(bc, "GEMINI_API_KEY", "fake-key"):
            with mock.patch.object(bc, "audit", return_value=gemini_response):
                with mock.patch("sys.stdin", mock.Mock(read=lambda: json.dumps({
                    "assistant_text": "Fixed the login bug and updated tests.",
                    "diff_stat": "login.py | 5 +++--",
                    "diff_text": "+fixed line",
                    "context": "",
                }))):
                    with pytest.raises(SystemExit) as exc_info:
                        bc.main()
                    assert exc_info.value.code == 0
                    out = capsys.readouterr().out
                    # Should contain the score banner
                    assert "BOUNCER AUDIT: 9/10" in out
                    # Should contain the raw Gemini output
                    assert "minor gap in tests" in out
                    # Should NOT be JSON
                    try:
                        json.loads(out)
                        pytest.fail("Output should not be valid JSON")
                    except json.JSONDecodeError:
                        pass  # Expected

    def test_score_10_output(self, capsys):
        gemini_response = "SCORE: 10/10\nISSUES:\n- none\nVERDICT: PASS"
        with mock.patch.object(bc, "GEMINI_API_KEY", "fake-key"):
            with mock.patch.object(bc, "audit", return_value=gemini_response):
                with mock.patch("sys.stdin", mock.Mock(read=lambda: json.dumps({
                    "assistant_text": "Completed all tasks with tests.",
                    "diff_stat": "app.py | 10 +++++++---",
                    "diff_text": "+new code",
                    "context": "",
                }))):
                    with pytest.raises(SystemExit) as exc_info:
                        bc.main()
                    assert exc_info.value.code == 0
                    out = capsys.readouterr().out
                    assert "BOUNCER AUDIT: 10/10" in out
                    assert "PASS" in out

    def test_unparseable_score_still_shows_output(self, capsys):
        gemini_response = "The code looks good overall but has some issues."
        with mock.patch.object(bc, "GEMINI_API_KEY", "fake-key"):
            with mock.patch.object(bc, "audit", return_value=gemini_response):
                with mock.patch("sys.stdin", mock.Mock(read=lambda: json.dumps({
                    "assistant_text": "Did some work.",
                    "diff_stat": "f.py | 1 +",
                    "diff_text": "+x",
                    "context": "",
                }))):
                    with pytest.raises(SystemExit) as exc_info:
                        bc.main()
                    assert exc_info.value.code == 0
                    out = capsys.readouterr().out
                    assert "Could not parse score" in out
                    assert "looks good overall" in out


# --- Gemini API failure (fail-open) ---

class TestGeminiFailure:
    def test_api_error_prints_error_exits_zero(self, capsys):
        with mock.patch.object(bc, "GEMINI_API_KEY", "fake-key"):
            with mock.patch.object(bc, "audit", side_effect=Exception("connection timeout")):
                with mock.patch("sys.stdin", mock.Mock(read=lambda: json.dumps({
                    "assistant_text": "Did work.",
                    "diff_stat": "f.py | 1 +",
                    "diff_text": "+x",
                    "context": "",
                }))):
                    with pytest.raises(SystemExit) as exc_info:
                        bc.main()
                    assert exc_info.value.code == 0
                    out = capsys.readouterr().out
                    assert "ERROR" in out
                    assert "connection timeout" in out


# --- Empty diff handling ---

class TestEmptyDiff:
    def test_summary_only_no_diff_still_audits(self, capsys):
        """If there's a summary but no diff, still run the audit."""
        gemini_response = "SCORE: 10/10\nISSUES:\n- none\nVERDICT: PASS"
        with mock.patch.object(bc, "GEMINI_API_KEY", "fake-key"):
            with mock.patch.object(bc, "audit", return_value=gemini_response) as mock_audit:
                with mock.patch("sys.stdin", mock.Mock(read=lambda: json.dumps({
                    "assistant_text": "Answered the user's question about deployment.",
                    "diff_stat": "",
                    "diff_text": "",
                    "context": "",
                }))):
                    with pytest.raises(SystemExit) as exc_info:
                        bc.main()
                    assert exc_info.value.code == 0
                    mock_audit.assert_called_once()
                    out = capsys.readouterr().out
                    assert "BOUNCER AUDIT: 10/10" in out

    def test_diff_only_no_summary_still_audits(self, capsys):
        """If there's a diff but no summary, still run the audit."""
        gemini_response = "SCORE: 7/10\nISSUES:\n- no context\nVERDICT: FAIL"
        with mock.patch.object(bc, "GEMINI_API_KEY", "fake-key"):
            with mock.patch.object(bc, "audit", return_value=gemini_response) as mock_audit:
                with mock.patch("sys.stdin", mock.Mock(read=lambda: json.dumps({
                    "assistant_text": "",
                    "diff_stat": "file.py | 3 ++-",
                    "diff_text": "+new line",
                    "context": "",
                }))):
                    with pytest.raises(SystemExit) as exc_info:
                        bc.main()
                    assert exc_info.value.code == 0
                    mock_audit.assert_called_once()
