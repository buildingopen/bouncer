# Gemini Audit Hook for Claude Code

Independent quality gate that uses Gemini to review Claude Code's output before it stops. If the score is below threshold, Claude is blocked from stopping and told what to fix.

## How it works

1. Claude Code triggers the Stop hook when it's about to return a response
2. The hook sends Claude's response + context (user messages, CLAUDE.md, workplan, git diff) to Gemini
3. Gemini scores the output 1-10
4. If score < threshold (default: 10/10), Claude is blocked and given Gemini's feedback to fix
5. If score >= threshold, Claude is allowed to stop

## Security note

This hook sends the following data to the Google Gemini API:
- Claude's assistant response (up to 200k chars)
- User messages from the conversation transcript (last 3, up to 50k chars total)
- Project CLAUDE.md and active workplan
- Git diff of staged and unstaged changes (up to 50k chars)

Review Google's data handling policies before use.

## Setup

### 1. Install dependency

```bash
pip install -r requirements.txt
```

Or directly:

```bash
pip install google-genai
```

### 2. Copy files

```bash
cp gemini-audit.py ~/.claude/hooks/gemini-audit.py
cp gemini-audit.sh ~/.claude/hooks/gemini-audit.sh
chmod +x ~/.claude/hooks/gemini-audit.sh ~/.claude/hooks/gemini-audit.py
```

### 3. Set API key

```bash
export GEMINI_API_KEY="your-gemini-api-key"
```

Add this to your shell profile (`.bashrc`, `.zshrc`). If no key is set, the hook fails open (exits 0, does not block).

### 4. Register the hook

Add to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "Stop": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "~/.claude/hooks/gemini-audit.sh",
            "timeout": 60
          }
        ]
      }
    ]
  }
}
```

If you already have Stop hooks, add the gemini-audit entry to the existing hooks array.

### 5. Enable

```bash
touch ~/.claude/.gemini-audit-enabled
```

### Disable

```bash
rm ~/.claude/.gemini-audit-enabled
```

## Configuration

Edit `gemini-audit.py` to customize:

- `THRESHOLD` (default: 10) - minimum score to pass. Set to 8 for a less strict gate.
- `MAX_RETRIES` (default: 3) - after this many blocks in one session, auto-approve to prevent infinite loops.
- `BUDGET_ASSISTANT` (default: 200,000) - max chars of Claude's response to send
- `BUDGET_CONTEXT` (default: 50,000) - max chars of context (user messages, CLAUDE.md, workplan)
- `BUDGET_DIFF` (default: 50,000) - max chars of git diff

## Context gathered

The hook automatically gathers:

- **User messages**: last 3 messages from the conversation transcript (defines the task)
- **CLAUDE.md**: project-level instructions from the working directory
- **Workplan**: most recent `WORKPLAN-*.md` if modified within the last 2 hours
- **Git diff**: staged (`--cached`) and unstaged changes

## How scoring works

Gemini scores based on:

- Whether claims are verified with evidence (command output, test results)
- Whether all requested tasks are complete
- Whether code changes are tested
- Response accuracy and specificity

The prompt uses neutral scoring criteria without anchoring Gemini toward any particular score. The threshold is applied post-hoc in Python.

## Behavior

- Skips trivial responses (< 50 chars)
- Skips when `stop_hook_active` is true (prevents infinite retry loops)
- **Per-session retry limit**: after 3 blocks in a session, auto-approves (prevents stuck sessions)
- Fails open on API errors or missing API key
- **Log rotation**: rotates at 1 MB, keeps 1 backup
- **File locking**: uses `fcntl.flock` on log writes to prevent interleaved entries from concurrent invocations
- Logs to `~/.claude/hooks/gemini-audit.log`
- Retry state tracked in `/tmp/gemini-audit-retries/` (auto-cleaned after 24h)

## Running tests

```bash
pip install pytest
python3 -m pytest test_gemini_audit.py -v
```

## Requirements

- Python 3.8+
- `google-genai` package (see `requirements.txt`)
- A Gemini API key (free tier works)
- Claude Code with hooks support
