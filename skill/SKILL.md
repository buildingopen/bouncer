---
name: bouncer
description: >
  On-demand Gemini quality audit for ANY work: code, videos, stories, advice,
  research, creative output. Use when user says "audit", "bouncer", "score",
  "score this", "score using gemini", "check my work", "quality check",
  "review my changes", "rate this", "how did I do".
  Quick mode (default): Gemini scores based on context. Fast (5-10s).
  Deep mode ("deep audit", "verify everything"): Gemini independently
  reads files, runs tests, searches code, verifies every claim (30-120s).
---

# Bouncer - On-Demand Quality Audit

Works for any task type: code, creative work, videos, advice, research, operations.

## Mode Selection

- **Quick** (default): `/bouncer` or "score" or "audit"
- **Deep**: `/bouncer deep` or "deep audit" or "verify everything"

---

## Quick Audit

### Step 1: Gather context (adapt to the task type)

**For code changes:** Run git diff:
```bash
git diff --stat --no-color
git diff --no-color
git diff --cached --stat --no-color
git diff --cached --no-color
```

**For non-code work (videos, stories, advice, research):** Skip git diff. The `assistant_text` summary is the primary input.

### Step 2: Read `CLAUDE.md` from the current working directory (if it exists).

### Step 3: Build a JSON object and pipe it to the bouncer script:

- `assistant_text`: **THE MOST IMPORTANT FIELD.** A thorough summary of what you did this session. Be specific:
  - For code: files changed, bugs fixed, tests written, commands run
  - For creative: what you created, the goal, the audience, key decisions made
  - For videos: the script/story, visual choices, duration, format, iterations
  - For advice: the question asked, your recommendation, reasoning, alternatives considered
  - For research: what you found, sources checked, conclusions drawn
  - **CRITICAL: If the staged diff includes changes from prior sessions, note this.**
- `diff_stat`: Git diff stat (empty string if no code changes or not applicable)
- `diff_text`: Git diff (empty string if not applicable)
- `context`: The CLAUDE.md contents (empty string if no CLAUDE.md)

### Step 4: Run:
```bash
echo '<the JSON object>' | python3 ~/.claude/skills/bouncer/scripts/bouncer-check.py
```

### Step 5: Present results exactly as printed.

---

## Deep Audit

For code-heavy tasks where you want Gemini to independently verify claims.

### Step 1: Gather context (same as quick audit).

### Step 2: Read `CLAUDE.md` from the current working directory (if it exists).

### Step 3: Build a JSON object with:
- `assistant_text`: Same thorough summary as quick audit
- `diff_text`: Git diff (empty string if not applicable)
- `context`: The CLAUDE.md contents (empty string if no CLAUDE.md)
- `cwd`: The current working directory (absolute path)

### Step 4: Run:
```bash
echo '<the JSON object>' | python3 ~/.claude/skills/bouncer/scripts/bouncer-deep.py
```

### Step 5: Present ALL results exactly as printed.

---

## Important

- Do NOT skip or filter any output from the scripts.
- If the script fails (missing API key, import error), show the error to the user.
- The `assistant_text` field should be YOUR honest, detailed summary. Not a copy of user messages. The richer the summary, the better the audit.
- Deep audit takes 30-120 seconds. Tell the user it will take a moment.
- For non-code tasks, `assistant_text` carries all the weight. Make it thorough.
