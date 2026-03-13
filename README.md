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

## What it looks like

Quick audit:

```text
========================================
  BOUNCER AUDIT: 9/10
========================================

SCORE: 9/10
ISSUES:
- missing explicit test command output in final message
VERDICT: FAIL
```

Deep audit:

```text
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    BOUNCER DEEP AUDIT  [###########################...]  9/10
    GUEST LIST: almost flawless
    Verified in 12.4s
  ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
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

### Quick install (recommended)

```bash
curl -fsSL https://raw.githubusercontent.com/buildingopen/bouncer/master/install.sh | bash
```

This installs `google-genai` into your Python user site, copies hook + skill files, registers the Stop hook in `settings.json`, and enables bouncer. You just need to set your API key:

```bash
export GEMINI_API_KEY="your-gemini-api-key"
```

Add this to your `.bashrc`/`.zshrc`. Get a free key at [aistudio.google.com/apikey](https://aistudio.google.com/apikey). If no key is set, the hook fails open (exits 0, does not block).

### Manual install

<details>
<summary>Step-by-step instructions</summary>

#### 1. Install dependency

```bash
python3 -m pip install --user --break-system-packages google-genai
```

#### 2. Copy files

```bash
cp gemini-audit.py ~/.claude/hooks/gemini-audit.py
cp gemini-audit.sh ~/.claude/hooks/gemini-audit.sh
chmod +x ~/.claude/hooks/gemini-audit.sh ~/.claude/hooks/gemini-audit.py
```

#### 3. Set API key

```bash
export GEMINI_API_KEY="your-gemini-api-key"
```

Add this to your shell profile (`.bashrc`, `.zshrc`).

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

#### 5. Enable

```bash
touch ~/.claude/.gemini-audit-enabled
```

</details>

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

## Skill variant (on-demand audit)

The skill lets you run a Bouncer audit on demand via `/bouncer` in Claude Code. Two modes:

### Quick audit

```
/bouncer
```

Or say "audit my work", "score this", "quality check". Gemini scores based on the diff + Claude's summary. Fast (5-10s).

### Deep audit

```
/bouncer deep
```

Or say "deep audit", "verify everything". Gemini gets full tool access: reads files, runs tests, searches code, checks git history. It independently verifies every claim Claude makes. Thorough (30-120s).

**What the deep auditor can do:**
- Read any file in the project
- Run shell commands (tests, builds, linting)
- Search code with regex
- Check git log and diff
- Verify specific claims ("tests pass", "bug is fixed")

### Install the skill

Included in the one-liner install. Or manually:

```bash
mkdir -p ~/.claude/skills/bouncer/scripts
cp skill/SKILL.md ~/.claude/skills/bouncer/SKILL.md
cp skill/scripts/bouncer-check.py ~/.claude/skills/bouncer/scripts/bouncer-check.py
cp skill/scripts/bouncer-deep.py ~/.claude/skills/bouncer/scripts/bouncer-deep.py
chmod +x ~/.claude/skills/bouncer/scripts/*.py
```

### Comparison

| Mode | Speed | Verification | Use case |
|------|-------|-------------|----------|
| Hook (auto) | 5-15s | Transcript-based | Every response |
| Quick (`/bouncer`) | 5-10s | Diff + summary | Spot check |
| Deep (`/bouncer deep`) | 30-120s | Independent tool access | Before merging, final review |

## Running tests

```bash
pip install pytest
python3 -m pytest test_gemini_audit.py test_bouncer_check.py test_bouncer_deep.py -v
```

## Requirements

- Python 3.8+
- `google-genai` package (see `requirements.txt`)
- A Gemini API key (free tier works)
- Claude Code with hooks support
