#!/usr/bin/env python3
"""
Gemini independent audit hook for Claude Code Stop events.
Sends assistant output + user request + CLAUDE.md + workplan + git diff to Gemini.
If score < threshold, feeds back issues to Claude to keep working.

Enable: touch ~/.claude/.gemini-audit-enabled
Disable: rm ~/.claude/.gemini-audit-enabled
Skip: only trivial responses (<50 chars).
"""

import glob
import json
import os
import subprocess
import sys
import time
from pathlib import Path

GEMINI_API_KEY = os.environ.get(
    "GEMINI_API_KEY",
    os.environ.get("GOOGLE_API_KEY", ""),
)
FLAG_FILE = os.path.expanduser("~/.claude/.gemini-audit-enabled")
LOG_FILE = os.path.expanduser("~/.claude/hooks/gemini-audit.log")
THRESHOLD = 10  # Minimum score to pass - only 10/10 is acceptable


def log(msg):
    with open(LOG_FILE, "a") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")


def get_git_diff():
    """Get recent changes from git diff."""
    try:
        result = subprocess.run(
            ["git", "diff", "HEAD~1", "--stat", "--no-color"],
            capture_output=True, text=True, timeout=5, cwd=os.getcwd(),
        )
        if result.returncode == 0 and result.stdout.strip():
            stat = result.stdout.strip()
            diff_result = subprocess.run(
                ["git", "diff", "HEAD~1", "--no-color"],
                capture_output=True, text=True, timeout=5, cwd=os.getcwd(),
            )
            diff_text = diff_result.stdout[:100_000] if diff_result.returncode == 0 else ""
            return stat, diff_text
    except Exception:
        pass
    try:
        result = subprocess.run(
            ["git", "diff", "--stat", "--no-color"],
            capture_output=True, text=True, timeout=5, cwd=os.getcwd(),
        )
        if result.returncode == 0 and result.stdout.strip():
            stat = result.stdout.strip()
            diff_result = subprocess.run(
                ["git", "diff", "--no-color"],
                capture_output=True, text=True, timeout=5, cwd=os.getcwd(),
            )
            diff_text = diff_result.stdout[:100_000] if diff_result.returncode == 0 else ""
            return stat, diff_text
    except Exception:
        pass
    return "", ""


def get_context(data):
    """Extract task context from transcript, CLAUDE.md, and workplans."""
    cwd = data.get("cwd", os.getcwd())
    context_parts = []

    # 1. Extract user messages from transcript FIRST (these define the task)
    transcript_path = data.get("transcript_path", "")
    user_messages = []
    if transcript_path and os.path.exists(transcript_path):
        try:
            with open(transcript_path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        if entry.get("role") == "user":
                            content = entry.get("content", "")
                            if isinstance(content, list):
                                parts = []
                                for block in content:
                                    if isinstance(block, dict) and block.get("type") == "text":
                                        parts.append(block.get("text", ""))
                                content = "\n".join(parts)
                            if isinstance(content, str) and len(content) > 10:
                                user_messages.append(content[:1000])
                    except (json.JSONDecodeError, KeyError):
                        continue
        except Exception:
            pass

    # User messages are PRIMARY context (they define what Claude was asked)
    if user_messages:
        recent = user_messages[-3:]
        msgs = "\n---\n".join(recent)
        context_parts.append(f"USER'S REQUEST (last {len(recent)} messages - THIS defines the task):\n{msgs}")

    # 2. Read CLAUDE.md from project root (quality standards, not task definition)
    claude_md = Path(cwd) / "CLAUDE.md"
    if claude_md.exists():
        try:
            text = claude_md.read_text()
            context_parts.append(f"PROJECT CLAUDE.MD (quality standards):\n{text}")
        except Exception:
            pass

    # 3. Only include workplan if recently modified (within last 2 hours)
    # Stale workplans from old sessions cause false positives
    workplans = sorted(glob.glob(str(Path(cwd) / "WORKPLAN-*.md")), reverse=True)
    if workplans:
        try:
            wp_path = Path(workplans[0])
            age_hours = (time.time() - wp_path.stat().st_mtime) / 3600
            if age_hours < 2:
                text = wp_path.read_text()
                context_parts.append(f"ACTIVE WORKPLAN ({wp_path.name}, modified {age_hours:.1f}h ago):\n{text}")
            else:
                log(f"SKIP stale workplan: {wp_path.name} ({age_hours:.0f}h old)")
        except Exception:
            pass

    return "\n\n".join(context_parts) if context_parts else ""


def audit_with_gemini(assistant_text, diff_stat, diff_text, task_context):
    """Send to Gemini for independent scoring."""
    from google import genai
    from google.genai import types

    # Budget: ~800k chars total to stay under Gemini's 1M token limit
    # Priority: assistant response (most important) > context > diff
    BUDGET_ASSISTANT = 200_000   # Claude's full response
    BUDGET_CONTEXT = 50_000      # User messages + CLAUDE.md + workplan
    BUDGET_DIFF = 50_000         # Git diff

    diff_section = ""
    if diff_stat:
        diff_section = f"""
CODE CHANGES (git diff --stat):
{diff_stat[:5000]}

CODE CHANGES (diff):
{diff_text[:BUDGET_DIFF]}
"""
    else:
        diff_section = "\n(No code diff available - changes may already be committed. Score based on the agent's response quality, completeness, and whether claims seem credible.)\n"

    context_section = ""
    if task_context:
        context_section = f"""
TASK CONTEXT (what Claude was asked to do, project rules, active workplan):
{task_context[:BUDGET_CONTEXT]}
"""

    prompt = f"""You are an independent reviewer auditing an AI coding agent (Claude).
Score the output 1-10 and list specific issues. Be harsh but fair.

THRESHOLD: Only {THRESHOLD}/10 passes. Claude must not stop until BOTH you (Gemini) AND Claude agree the work is genuinely {THRESHOLD}/10. If it is {THRESHOLD - 1}/10, block it and tell Claude what to fix. Only score {THRESHOLD}/10 when:
- Every claim is verified (not just stated)
- All tasks are complete, not "almost done" or "needs manual step"
- Code/config changes are tested and confirmed working
- No hand-waving, no "this will work when you restart"

SCORING CRITERIA:
- 10/10: Verified complete, every claim backed by evidence, nothing left undone
- 8-9/10: Good work but has gaps (unverified claims, untested changes, loose ends)
- 6-7/10: Notable problems (incomplete, vague, missing verification)
- 4-5/10: Significant issues (unverified claims, likely bugs, wrong approach)
- 1-3/10: Fundamentally broken, wrong, or fabricated

IMPORTANT RULES:
- The agent handles many task types: coding, research, configuration, answering questions, debugging.
- The git diff may be UNRELATED to the current response. Do NOT penalize for diff/response mismatch unless the agent explicitly claims to have made specific code changes that aren't in the diff.
- Score the response on its OWN merits: accuracy, completeness, helpfulness, specificity.
- Only use the diff to verify if the agent explicitly claims "I changed X" or "I fixed Y".
- When the agent shows verified command output (e.g., curl responses, file contents, test results), treat those as evidence. Do not call them "unverifiable" just because you cannot run the commands yourself.
- SELF-SCORING IS EXPECTED: Claude is instructed by its CLAUDE.md to self-score work (score tables, 10/10 assessments). This is the standard workflow, not a conflict of interest. Do NOT penalize Claude for including score tables or self-assessments. YOUR job is to independently verify whether the self-score is accurate.
- TOOL OUTPUT IS EVIDENCE: When Claude shows tool results (command output, file reads, curl responses, grep results), these are real executed commands with real output. Treat them as verified evidence.
- Use the TASK CONTEXT below to understand what Claude was asked to do. The USER'S REQUEST section defines the task. Score whether Claude completed THAT request. A workplan may be included but could be from a different task; if it contradicts the user messages, trust the user messages.
{context_section}
WHAT THE AGENT SAID:
{assistant_text[:BUDGET_ASSISTANT]}
{diff_section}
RESPOND IN EXACTLY THIS FORMAT (no markdown, no extra text):
SCORE: X/10
ISSUES:
- issue 1
- issue 2
- issue 3
VERDICT: PASS or FAIL
"""

    client = genai.Client(api_key=GEMINI_API_KEY)
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            max_output_tokens=1024,
            temperature=0.2,
        ),
    )
    return response.text


def main():
    # Check opt-in flag
    if not os.path.exists(FLAG_FILE):
        sys.exit(0)

    if not GEMINI_API_KEY:
        log("ERROR: GEMINI_API_KEY or GOOGLE_API_KEY not set")
        sys.exit(0)

    # Read hook input from stdin
    try:
        raw = sys.stdin.read()
        data = json.loads(raw)
    except (json.JSONDecodeError, Exception):
        log("ERROR: could not parse stdin")
        sys.exit(0)

    # Log available fields for debugging
    log(f"FIELDS: {list(data.keys())}")

    # Don't run if already in a stop-hook loop (prevents infinite retries)
    if data.get("stop_hook_active"):
        log("SKIP: stop_hook_active=true (already continuing from previous hook)")
        sys.exit(0)

    # Extract assistant's message
    assistant_text = data.get("last_assistant_message", "")
    if not assistant_text:
        tool_input = data.get("tool_input", {})
        if isinstance(tool_input, dict):
            assistant_text = tool_input.get("result", "")
        if not assistant_text:
            assistant_text = data.get("result", data.get("message", ""))
    if isinstance(assistant_text, list):
        parts = []
        for block in assistant_text:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        assistant_text = "\n".join(parts)

    # Skip trivial responses
    if len(str(assistant_text)) < 50:
        log(f"SKIP: trivial response ({len(str(assistant_text))} chars)")
        sys.exit(0)

    # Gather context: user request, CLAUDE.md, workplan
    task_context = get_context(data)
    log(f"CONTEXT: {len(task_context)} chars")

    # Check for code changes
    diff_stat, diff_text = get_git_diff()

    # Run Gemini audit
    try:
        log("AUDIT: sending to Gemini...")
        start = time.time()
        result = audit_with_gemini(str(assistant_text), diff_stat, diff_text, task_context)
        elapsed = time.time() - start
        log(f"AUDIT: Gemini responded in {elapsed:.1f}s")
    except Exception as e:
        log(f"ERROR: Gemini call failed: {e}")
        sys.exit(0)  # Don't block on API errors

    # Parse score
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

    if score is None:
        log(f"WARN: could not parse score from: {result[:200]}")
        sys.exit(0)

    log(f"SCORE: {score}/10")

    if score >= THRESHOLD:
        log(f"PASS: {score}/10 >= {THRESHOLD}")
        print(json.dumps({"decision": "approve"}))
        sys.exit(0)
    else:
        log(f"FAIL: {score}/10 < {THRESHOLD}")
        reason = f"[Gemini Independent Audit: {score}/10 - BELOW THRESHOLD]\n\n{result}\n\nFix the issues listed above before returning."
        print(json.dumps({"decision": "block", "reason": reason}))
        sys.exit(2)


if __name__ == "__main__":
    main()
