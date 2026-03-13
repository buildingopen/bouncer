"""Tests for bouncer-deep.py (and skill/scripts/bouncer-deep.py)"""

import json
import os
import sys
import tempfile
from unittest import mock

import pytest

# Import the module under test
sys.path.insert(0, os.path.dirname(__file__))
import importlib
bd = importlib.import_module("bouncer-deep")


# --- Score parsing ---

class TestScoreParsing:
    def test_standard_format(self):
        result = "SCORE: 8/10\nVERIFIED:\n- tests pass -> verified\nISSUES:\n- none\nVERDICT: PASS"
        assert bd.parse_score(result) == 8

    def test_score_10(self):
        assert bd.parse_score("SCORE: 10/10\nVERDICT: PASS") == 10

    def test_score_1(self):
        assert bd.parse_score("SCORE: 1/10\nVERDICT: FAIL") == 1

    def test_unparseable_returns_none(self):
        assert bd.parse_score("No score here") is None

    def test_malformed_score_line(self):
        assert bd.parse_score("SCORE: xyz/10") is None


# --- Tool functions ---

class TestReadFile:
    def test_reads_existing_file(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello world")
        with mock.patch.object(bd, "CWD", str(tmp_path)):
            result = bd.read_file("test.txt")
        assert result == "hello world"

    def test_absolute_path(self, tmp_path):
        f = tmp_path / "abs.txt"
        f.write_text("absolute")
        result = bd.read_file(str(f))
        assert result == "absolute"

    def test_missing_file_returns_error(self):
        result = bd.read_file("/nonexistent/file.txt")
        assert "ERROR" in result

    def test_truncates_large_files(self, tmp_path):
        f = tmp_path / "big.txt"
        f.write_text("x" * 60_000)
        result = bd.read_file(str(f))
        assert "truncated" in result
        assert len(result) < 55_000


class TestRunCommand:
    def test_basic_command(self):
        result = bd.run_command("echo hello")
        assert "hello" in result

    def test_blocked_rm_rf(self):
        result = bd.run_command("rm -rf /")
        assert "BLOCKED" in result

    def test_blocked_mkfs(self):
        result = bd.run_command("mkfs.ext4 /dev/sda")
        assert "BLOCKED" in result

    def test_blocked_dd(self):
        result = bd.run_command("dd if=/dev/zero of=/dev/sda")
        assert "BLOCKED" in result

    def test_blocked_chmod_777(self):
        result = bd.run_command("chmod -R 777 /")
        assert "BLOCKED" in result

    def test_nonzero_exit_code_shown(self):
        result = bd.run_command("false")
        assert "EXIT CODE" in result

    def test_stderr_captured(self):
        result = bd.run_command("echo err >&2")
        assert "err" in result

    def test_timeout_handled(self):
        with mock.patch.object(bd, "TIMEOUT_CMD", 1):
            result = bd.run_command("sleep 10")
        assert "TIMEOUT" in result


class TestSearchCode:
    def test_search_finds_pattern(self, tmp_path):
        f = tmp_path / "code.py"
        f.write_text("def hello_world():\n    pass\n")
        with mock.patch.object(bd, "CWD", str(tmp_path)):
            result = bd.search_code("hello_world", "*.py")
        assert "hello_world" in result

    def test_no_matches(self, tmp_path):
        f = tmp_path / "empty.py"
        f.write_text("nothing here")
        with mock.patch.object(bd, "CWD", str(tmp_path)):
            result = bd.search_code("nonexistent_pattern_xyz", "*.py")
        assert "no matches" in result.lower() or result.strip() == ""

    def test_grep_fallback_no_matches(self):
        rg_missing = FileNotFoundError()
        grep_result = mock.Mock(returncode=1, stdout="", stderr="")
        with mock.patch("subprocess.run", side_effect=[rg_missing, grep_result]):
            result = bd.search_code("nonexistent_pattern_xyz", "*.py")
        assert "no matches" in result.lower()


class TestListFiles:
    def test_lists_directory(self, tmp_path):
        (tmp_path / "file1.py").touch()
        (tmp_path / "file2.txt").touch()
        (tmp_path / "subdir").mkdir()
        with mock.patch.object(bd, "CWD", str(tmp_path)):
            result = bd.list_files(".")
        assert "file1.py" in result
        assert "file2.txt" in result
        assert "subdir/" in result

    def test_glob_pattern(self, tmp_path):
        (tmp_path / "a.py").touch()
        (tmp_path / "b.txt").touch()
        with mock.patch.object(bd, "CWD", str(tmp_path)):
            result = bd.list_files(".", "*.py")
        assert "a.py" in result
        assert "b.txt" not in result

    def test_missing_directory(self):
        result = bd.list_files("/nonexistent/path")
        assert "ERROR" in result


# --- Fail-open on missing API key ---

class TestFailOpen:
    def test_no_api_key_prints_warning_exits_zero(self, capsys):
        with mock.patch.object(bd, "GEMINI_API_KEY", None):
            with pytest.raises(SystemExit) as exc_info:
                bd.main()
            assert exc_info.value.code == 0
            out = capsys.readouterr().out
            assert "WARNING" in out or "No GEMINI_API_KEY" in out


# --- Input JSON parsing ---

class TestInputParsing:
    def test_invalid_json_exits_one(self, capsys):
        with mock.patch.object(bd, "GEMINI_API_KEY", "fake-key"):
            with mock.patch("sys.stdin", mock.Mock(read=lambda: "not json {")):
                with pytest.raises(SystemExit) as exc_info:
                    bd.main()
                assert exc_info.value.code == 1
                out = capsys.readouterr().out
                assert "ERROR" in out

    def test_empty_input_exits_zero(self, capsys):
        with mock.patch.object(bd, "GEMINI_API_KEY", "fake-key"):
            with mock.patch("sys.stdin", mock.Mock(read=lambda: json.dumps({
                "assistant_text": "",
                "diff_text": "",
                "context": "",
            }))):
                with pytest.raises(SystemExit) as exc_info:
                    bd.main()
                assert exc_info.value.code == 0
                out = capsys.readouterr().out
                assert "Nothing to audit" in out


# --- Deep audit with mocked Gemini ---

class TestDeepAudit:
    def _mock_response(self, text=None, function_calls=None):
        """Create a mock Gemini response."""
        parts = []
        if text:
            part = mock.Mock()
            part.function_call = None
            part.text = text
            parts.append(part)
        if function_calls:
            for name, args in function_calls:
                part = mock.Mock()
                part.function_call = mock.Mock()
                part.function_call.name = name
                part.function_call.args = args
                part.text = None
                parts.append(part)

        candidate = mock.Mock()
        candidate.content = mock.Mock()
        candidate.content.parts = parts
        candidate.content.role = "model"

        response = mock.Mock()
        response.candidates = [candidate]
        return response

    def test_direct_text_response(self, capsys):
        """Gemini returns final text without tool calls."""
        final_text = "SCORE: 9/10\nVERIFIED:\n- claim -> verified\nISSUES:\n- minor\nVERDICT: PASS"
        mock_response = self._mock_response(text=final_text)

        with mock.patch.object(bd, "GEMINI_API_KEY", "fake-key"):
            mock_client = mock.Mock()
            mock_client.models.generate_content.return_value = mock_response
            with mock.patch("google.genai.Client", return_value=mock_client):
                result = bd.deep_audit("I fixed the bug", "diff here", "")

        assert result == final_text

    def test_tool_call_then_text(self, capsys):
        """Gemini calls a tool, then returns final text."""
        tool_response = self._mock_response(
            function_calls=[("list_files", {"path": "."})]
        )
        final_response = self._mock_response(
            text="SCORE: 8/10\nVERIFIED:\n- files listed\nISSUES:\n- none\nVERDICT: PASS"
        )

        with mock.patch.object(bd, "GEMINI_API_KEY", "fake-key"):
            mock_client = mock.Mock()
            mock_client.models.generate_content.side_effect = [tool_response, final_response]
            with mock.patch("google.genai.Client", return_value=mock_client):
                with mock.patch.object(bd, "list_files", return_value="file1.py\nfile2.py"):
                    result = bd.deep_audit("Did some work", "", "")

        assert "8/10" in result

    def test_max_turns_reached(self, capsys):
        """If Gemini keeps calling tools without a final answer, returns incomplete."""
        tool_response = self._mock_response(
            function_calls=[("list_files", {"path": "."})]
        )

        with mock.patch.object(bd, "GEMINI_API_KEY", "fake-key"):
            with mock.patch.object(bd, "MAX_TURNS", 2):
                mock_client = mock.Mock()
                mock_client.models.generate_content.return_value = tool_response
                with mock.patch("google.genai.Client", return_value=mock_client):
                    with mock.patch.object(bd, "list_files", return_value="files"):
                        result = bd.deep_audit("work", "", "")

        assert "INCOMPLETE" in result

    def test_api_error_breaks_loop(self, capsys):
        """API errors break out of the loop gracefully."""
        with mock.patch.object(bd, "GEMINI_API_KEY", "fake-key"):
            mock_client = mock.Mock()
            mock_client.models.generate_content.side_effect = Exception("rate limited")
            with mock.patch("google.genai.Client", return_value=mock_client):
                result = bd.deep_audit("work", "", "")

        assert "INCOMPLETE" in result


# --- Main with mocked deep_audit ---

class TestMain:
    def test_full_run_with_score(self, capsys):
        audit_result = "SCORE: 7/10\nVERIFIED:\n- claim -> unverified\nISSUES:\n- missing tests\nVERDICT: FAIL"
        with mock.patch.object(bd, "GEMINI_API_KEY", "fake-key"):
            with mock.patch.object(bd, "deep_audit", return_value=audit_result):
                with mock.patch("sys.stdin", mock.Mock(read=lambda: json.dumps({
                    "assistant_text": "Fixed bugs",
                    "diff_text": "+code",
                    "context": "",
                    "cwd": "/tmp",
                }))):
                    with pytest.raises(SystemExit) as exc_info:
                        bd.main()
                    assert exc_info.value.code == 0
                    out = capsys.readouterr().out
                    assert "BOUNCER DEEP AUDIT" in out
                    assert "7/10" in out
                    assert "SIDE ENTRANCE" in out

    def test_audit_exception_exits_zero(self, capsys):
        with mock.patch.object(bd, "GEMINI_API_KEY", "fake-key"):
            with mock.patch.object(bd, "deep_audit", side_effect=Exception("boom")):
                with mock.patch("sys.stdin", mock.Mock(read=lambda: json.dumps({
                    "assistant_text": "Did work",
                    "diff_text": "+x",
                    "context": "",
                }))):
                    with pytest.raises(SystemExit) as exc_info:
                        bd.main()
                    assert exc_info.value.code == 0
                    out = capsys.readouterr().out
                    assert "ERROR" in out
