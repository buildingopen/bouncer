---
name: bouncer
description: >
  On-demand Gemini quality audit. Use when user says "audit", "bouncer",
  "check my work", "quality check", "review my changes", "score this".
  Sends git diff + context to Gemini 2.5 Flash for independent scoring 1-10.
---

# Bouncer - On-Demand Quality Audit

Run a Gemini audit on the current work, right now. No hook needed.

## Steps

1. Gather the git diff (staged and unstaged):

```bash
git diff --stat --no-color
git diff --no-color
git diff --cached --stat --no-color
git diff --cached --no-color
```

2. Read `CLAUDE.md` from the current working directory (if it exists) for project context.

3. Build a JSON object with these fields and pipe it to the bouncer script:
   - `assistant_text`: A summary of what you've done so far in this session (your own words, be specific about changes made, files touched, commands run)
   - `diff_stat`: The combined `--stat` output from step 1
   - `diff_text`: The combined full diff output from step 1
   - `context`: The CLAUDE.md contents (empty string if no CLAUDE.md)

4. Run the audit:

```bash
echo '<the JSON object>' | python3 ~/.claude/skills/bouncer/scripts/bouncer-check.py
```

5. Present the results to the user exactly as printed. If the score is below 10, explain what needs fixing. If 10/10, confirm the work passes audit.

## Important

- Do NOT skip or filter any output from the script.
- If the script fails (missing API key, import error), show the error to the user.
- The `assistant_text` field should be YOUR honest summary of what was accomplished, not a copy of user messages.
