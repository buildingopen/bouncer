"""Tests for gemini-audit.py"""

import json
import os
import sys
import tempfile
import textwrap
from pathlib import Path
from unittest import mock

import pytest

# Import the module under test
sys.path.insert(0, os.path.dirname(__file__))
import importlib
ga = importlib.import_module("gemini-audit")


# --- Transcript parsing ---

class TestGetContext:
    def _make_transcript(self, entries):
        """Write JSONL entries to a temp file, return path."""
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
        for entry in entries:
            f.write(json.dumps(entry) + "\n")
        f.close()
        return f.name

    def test_extracts_user_messages_from_correct_format(self):
        """type=user, content in message.content"""
        path = self._make_transcript([
            {"type": "user", "message": {"role": "user", "content": "Fix the login bug please"}, "uuid": "1"},
            {"type": "assistant", "message": {"role": "assistant", "content": "Done."}, "uuid": "2"},
        ])
        try:
            data = {"transcript_path": path, "cwd": "/tmp"}
            ctx = ga.get_context(data)
            assert "Fix the login bug" in ctx
        finally:
            os.unlink(path)

    def test_ignores_old_role_format(self):
        """Old format with role=user at top level is NOT matched."""
        path = self._make_transcript([
            {"role": "user", "content": "This uses the old format"},
        ])
        try:
            data = {"transcript_path": path, "cwd": "/tmp"}
            ctx = ga.get_context(data)
            assert "old format" not in ctx
        finally:
            os.unlink(path)

    def test_handles_list_content(self):
        """content can be a list of blocks."""
        path = self._make_transcript([
            {"type": "user", "message": {"role": "user", "content": [
                {"type": "text", "text": "Deploy the app"},
                {"type": "image", "source": "screenshot.png"},
            ]}, "uuid": "1"},
        ])
        try:
            data = {"transcript_path": path, "cwd": "/tmp"}
            ctx = ga.get_context(data)
            assert "Deploy the app" in ctx
        finally:
            os.unlink(path)

    def test_takes_last_3_messages(self):
        """Only last 3 user messages included."""
        entries = [
            {"type": "user", "message": {"role": "user", "content": f"Message number {i}"}, "uuid": str(i)}
            for i in range(5)
        ]
        path = self._make_transcript(entries)
        try:
            data = {"transcript_path": path, "cwd": "/tmp"}
            ctx = ga.get_context(data)
            assert "Message number 0" not in ctx
            assert "Message number 1" not in ctx
            assert "Message number 2" in ctx
            assert "Message number 3" in ctx
            assert "Message number 4" in ctx
        finally:
            os.unlink(path)

    def test_uses_deque_for_large_transcripts(self):
        """Large transcripts only read the tail (200 lines)."""
        entries = [
            {"type": "user", "message": {"role": "user", "content": f"Msg {i} padding" + "x" * 50}, "uuid": str(i)}
            for i in range(500)
        ]
        path = self._make_transcript(entries)
        try:
            data = {"transcript_path": path, "cwd": "/tmp"}
            ctx = ga.get_context(data)
            # First messages beyond the 200 tail window are not present
            assert "Msg 0 padding" not in ctx
            assert "Msg 499 padding" in ctx
        finally:
            os.unlink(path)

    def test_missing_transcript(self):
        """No transcript path returns empty context (no crash)."""
        ctx = ga.get_context({"cwd": "/tmp"})
        assert ctx == "" or "USER'S REQUEST" not in ctx

    def test_skips_short_messages(self):
        """Messages <= 10 chars are skipped."""
        path = self._make_transcript([
            {"type": "user", "message": {"role": "user", "content": "hi"}, "uuid": "1"},
        ])
        try:
            data = {"transcript_path": path, "cwd": "/tmp"}
            ctx = ga.get_context(data)
            assert "hi" not in ctx
        finally:
            os.unlink(path)


# --- Score parsing ---

class TestScoreParsing:
    def test_standard_format(self):
        result = "SCORE: 8/10\nISSUES:\n- missing tests\nVERDICT: FAIL"
        score = None
        for line in result.split("\n"):
            line = line.strip()
            if line.startswith("SCORE:"):
                score_str = line.split(":")[1].strip().split("/")[0].strip()
                score = int(score_str)
                break
        assert score == 8

    def test_score_10(self):
        result = "SCORE: 10/10\nISSUES:\n- none\nVERDICT: PASS"
        score = None
        for line in result.split("\n"):
            line = line.strip()
            if line.startswith("SCORE:"):
                score_str = line.split(":")[1].strip().split("/")[0].strip()
                score = int(score_str)
                break
        assert score == 10

    def test_unparseable_returns_none(self):
        result = "This is garbage output with no score"
        score = None
        for line in result.split("\n"):
            line = line.strip()
            if line.startswith("SCORE:"):
                try:
                    score_str = line.split(":")[1].strip().split("/")[0].strip()
                    score = int(score_str)
                except (ValueError, IndexError):
                    pass
                break
        assert score is None


# --- Git diff ---

class TestGetGitDiff:
    @mock.patch("subprocess.run")
    def test_combines_staged_and_unstaged(self, mock_run):
        # Staged stat, staged diff, unstaged stat, unstaged diff
        mock_run.side_effect = [
            mock.Mock(returncode=0, stdout="file1.py | 2 +-\n"),  # staged stat
            mock.Mock(returncode=0, stdout="+staged change\n"),     # staged diff
            mock.Mock(returncode=0, stdout="file2.py | 1 +\n"),   # unstaged stat
            mock.Mock(returncode=0, stdout="+unstaged change\n"),   # unstaged diff
        ]
        stat, diff = ga.get_git_diff()
        assert "STAGED:" in stat
        assert "UNSTAGED:" in stat
        assert "+staged change" in diff
        assert "+unstaged change" in diff

    @mock.patch("subprocess.run")
    def test_empty_when_no_changes(self, mock_run):
        mock_run.return_value = mock.Mock(returncode=0, stdout="")
        stat, diff = ga.get_git_diff()
        assert stat == ""
        assert diff == ""

    @mock.patch("subprocess.run", side_effect=Exception("not a git repo"))
    def test_handles_non_git_dir(self, mock_run):
        stat, diff = ga.get_git_diff()
        assert stat == ""
        assert diff == ""


# --- Retry limit ---

class TestRetryLimit:
    def test_starts_at_zero(self):
        count = ga.get_retry_count("nonexistent-session-id-12345")
        assert count == 0

    def test_increments(self):
        sid = f"test-session-{os.getpid()}"
        retry_file = ga.RETRY_DIR / sid
        try:
            ga.increment_retry(sid)
            assert ga.get_retry_count(sid) == 1
            ga.increment_retry(sid)
            assert ga.get_retry_count(sid) == 2
        finally:
            retry_file.unlink(missing_ok=True)

    def test_empty_session_id_returns_zero(self):
        assert ga.get_retry_count("") == 0

    def test_empty_session_id_no_op_increment(self):
        ga.increment_retry("")  # no crash


# --- Fail-open behavior ---

class TestFailOpen:
    def test_no_api_key_exits_zero(self):
        """Without API key, script exits 0 (fail-open)."""
        with mock.patch.dict(os.environ, {}, clear=True):
            # Reimport to get GEMINI_API_KEY = None
            with mock.patch.object(ga, "GEMINI_API_KEY", None):
                with mock.patch("os.path.exists", return_value=True):
                    with mock.patch("sys.stdin", mock.Mock(read=lambda: '{"last_assistant_message": "hello world test response that is long enough"}')):
                        with pytest.raises(SystemExit) as exc_info:
                            ga.main()
                        assert exc_info.value.code == 0


# --- Decision JSON format ---

class TestDecisionFormat:
    def test_approve_format(self, capsys):
        """Approve outputs correct JSON."""
        with mock.patch.object(ga, "GEMINI_API_KEY", "fake-key"):
            with mock.patch("os.path.exists", return_value=True):
                with mock.patch.object(ga, "get_context", return_value=""):
                    with mock.patch.object(ga, "get_git_diff", return_value=("", "")):
                        with mock.patch.object(ga, "audit_with_gemini", return_value="SCORE: 10/10\nISSUES:\n- none\nVERDICT: PASS"):
                            with mock.patch("sys.stdin", mock.Mock(read=lambda: json.dumps({
                                "last_assistant_message": "x" * 100,
                                "session_id": "test-approve",
                            }))):
                                with pytest.raises(SystemExit) as exc_info:
                                    ga.main()
                                assert exc_info.value.code == 0
                                out = capsys.readouterr().out.strip()
                                parsed = json.loads(out)
                                assert parsed["decision"] == "approve"

    def test_block_format(self, capsys):
        """Block outputs correct JSON with reason."""
        retry_file = ga.RETRY_DIR / "test-block"
        retry_file.unlink(missing_ok=True)
        try:
            with mock.patch.object(ga, "GEMINI_API_KEY", "fake-key"):
                with mock.patch("os.path.exists", return_value=True):
                    with mock.patch.object(ga, "get_context", return_value=""):
                        with mock.patch.object(ga, "get_git_diff", return_value=("", "")):
                            with mock.patch.object(ga, "audit_with_gemini", return_value="SCORE: 7/10\nISSUES:\n- incomplete\nVERDICT: FAIL"):
                                with mock.patch("sys.stdin", mock.Mock(read=lambda: json.dumps({
                                    "last_assistant_message": "x" * 100,
                                    "session_id": "test-block",
                                }))):
                                    with pytest.raises(SystemExit) as exc_info:
                                        ga.main()
                                    assert exc_info.value.code == 0
                                    out = capsys.readouterr().out.strip()
                                    parsed = json.loads(out)
                                    assert parsed["decision"] == "block"
                                    assert "reason" in parsed
                                    assert "7/10" in parsed["reason"]
        finally:
            retry_file.unlink(missing_ok=True)

    def test_block_exit_code_is_zero(self, capsys):
        """Even on block, exit code is 0 (JSON carries the decision)."""
        retry_file = ga.RETRY_DIR / "test-exit-0"
        retry_file.unlink(missing_ok=True)
        try:
            with mock.patch.object(ga, "GEMINI_API_KEY", "fake-key"):
                with mock.patch("os.path.exists", return_value=True):
                    with mock.patch.object(ga, "get_context", return_value=""):
                        with mock.patch.object(ga, "get_git_diff", return_value=("", "")):
                            with mock.patch.object(ga, "audit_with_gemini", return_value="SCORE: 5/10\nISSUES:\n- bad\nVERDICT: FAIL"):
                                with mock.patch("sys.stdin", mock.Mock(read=lambda: json.dumps({
                                    "last_assistant_message": "x" * 100,
                                    "session_id": "test-exit-0",
                                }))):
                                    with pytest.raises(SystemExit) as exc_info:
                                        ga.main()
                                    assert exc_info.value.code == 0
        finally:
            retry_file.unlink(missing_ok=True)


# --- Trivial skip ---

class TestTrivialSkip:
    def test_short_response_skipped(self):
        with mock.patch.object(ga, "GEMINI_API_KEY", "fake-key"):
            with mock.patch("os.path.exists", return_value=True):
                with mock.patch("sys.stdin", mock.Mock(read=lambda: json.dumps({
                    "last_assistant_message": "ok",
                }))):
                    with pytest.raises(SystemExit) as exc_info:
                        ga.main()
                    assert exc_info.value.code == 0


# --- stop_hook_active re-audit ---

class TestStopHookActive:
    def test_reaudits_when_active(self, capsys):
        """stop_hook_active=true does NOT skip; it re-audits via Gemini."""
        with mock.patch.object(ga, "GEMINI_API_KEY", "fake-key"):
            with mock.patch("os.path.exists", return_value=True):
                with mock.patch.object(ga, "get_context", return_value=""):
                    with mock.patch.object(ga, "get_git_diff", return_value=("", "")):
                        with mock.patch.object(ga, "audit_with_gemini", return_value="SCORE: 10/10\nISSUES:\n- none\nVERDICT: PASS") as mock_audit:
                            with mock.patch("sys.stdin", mock.Mock(read=lambda: json.dumps({
                                "last_assistant_message": "x" * 100,
                                "stop_hook_active": True,
                                "session_id": "test-reaudit",
                            }))):
                                with pytest.raises(SystemExit) as exc_info:
                                    ga.main()
                                assert exc_info.value.code == 0
                                mock_audit.assert_called_once()
                                out = capsys.readouterr().out.strip()
                                parsed = json.loads(out)
                                assert parsed["decision"] == "approve"


# --- Log rotation ---

class TestLogRotation:
    def test_rotates_when_over_limit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "test.log"
            # Write > 1MB
            log_path.write_text("x" * 1_100_000)
            with mock.patch.object(ga, "LOG_FILE", str(log_path)):
                with mock.patch.object(ga, "LOG_MAX_BYTES", 1_000_000):
                    ga.rotate_log()
            assert not log_path.exists() or log_path.stat().st_size < 1_000_000
            backup = log_path.with_suffix(".log.1")
            assert backup.exists()

    def test_no_rotation_when_small(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "test.log"
            log_path.write_text("small log")
            with mock.patch.object(ga, "LOG_FILE", str(log_path)):
                ga.rotate_log()
            assert log_path.exists()
            assert log_path.read_text() == "small log"
