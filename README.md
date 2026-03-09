# Bouncer

Gemini stands at the door. Independent quality gate that audits Claude Code's output before it can stop. Score below threshold? Claude keeps working.

[![Tests](https://github.com/buildingopen/bouncer/actions/workflows/test.yml/badge.svg)](https://github.com/buildingopen/bouncer/actions/workflows/test.yml)

```
User prompt → Claude Code → [Stop Hook] → Gemini 2.5 Flash
                                              ↓
                                         Score 1-10
                                              ↓
                                    ┌─────────┴─────────┐
                                    │                    │
                               Score = 10           Score < 10
                                    │                    │
                              ✓ Approve              ✗ Block
                           (Claude stops)      (Claude keeps working
                                                with Gemini's feedback)
```

## How it works

1. Claude Code triggers the Stop hook when it's about to return a response
2. The hook extracts context: user messages from transcript, tool call results, git diff, CLAUDE.md, workplan
3. Everything is sent to Gemini 2.5 Flash for independent scoring (1-10)
4. If score < threshold (default: 10/10), Claude is blocked and given Gemini's feedback
5. If score >= threshold, Claude is allowed to stop
6. On re-audit (`stop_hook_active=true`), the hook audits again rather than skipping

## Security note

This hook sends the following data to the Google Gemini API:
- Claude's assistant response (up to 200k chars)
- User messages from the conversation transcript (last 3, up to 50k chars total)
- Tool call activity and results from the transcript (evidence of work done)
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

Add this to your shell profile (`.bashrc`, `.zshrc`). The shell wrapper sources your profile automatically. If no key is set, the hook fails open (exits 0, does not block).

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
- `BUDGET_ASSISTANT` (default: 200,000) - max chars of Claude's response to send
- `BUDGET_CONTEXT` (default: 50,000) - max chars of context (user messages, CLAUDE.md, workplan)
- `BUDGET_DIFF` (default: 50,000) - max chars of git diff

## Context gathered

The hook automatically extracts from the conversation transcript:

- **User messages**: last 3 messages (defines the task). Hook feedback messages are filtered out to prevent stale context loops.
- **Tool calls and results**: Bash commands, file reads, grep patterns, and their output. Paired together so Gemini sees the evidence (e.g., `[Bash] $ git rev-parse HEAD → OUTPUT: ac3db3c...`).
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

- **Re-audits on retry**: when `stop_hook_active=true`, the hook audits again (does not skip)
- **Skips trivial responses**: responses under 50 chars are auto-approved
- **Skips system errors**: rate limit messages, connection errors, and similar system messages are auto-approved to prevent infinite loops
- **Filters hook feedback**: the hook's own block messages are excluded from the transcript context sent to Gemini
- **Fails open**: API errors or missing API key result in auto-approve (exit 0)
- **Log rotation**: rotates at 1 MB, keeps 1 backup
- **File locking**: uses `fcntl.flock` on log writes to prevent interleaved entries from concurrent invocations
- **Logs**: `~/.claude/hooks/gemini-audit.log`

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
