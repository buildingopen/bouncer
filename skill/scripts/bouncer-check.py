#!/usr/bin/env python3
"""
Bouncer on-demand audit: reads JSON from stdin, calls Gemini 2.5 Flash,
prints human-readable score and issues.

Input JSON: {"assistant_text": "...", "diff_stat": "...", "diff_text": "...", "context": "..."}
Output: Human-readable score, issues, and verdict to stdout.
"""

import json
import os
import sys

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")

BUDGET_ASSISTANT = 200_000
BUDGET_CONTEXT = 50_000
BUDGET_DIFF = 50_000


def audit(assistant_text, diff_stat, diff_text, context):
    """Send to Gemini for independent scoring. Returns raw Gemini response text."""
    from google import genai
    from google.genai import types

    diff_section = ""
    if diff_stat:
        diff_section = f"""
CODE CHANGES (git diff --stat):
{diff_stat[:5000]}

CODE CHANGES (diff):
{diff_text[:BUDGET_DIFF]}
"""
    else:
        diff_section = "\n(No code diff available. Score based on the agent's response quality, completeness, and whether claims seem credible.)\n"

    context_section = ""
    if context:
        context_section = f"""
TASK CONTEXT (project rules from CLAUDE.md):
{context[:BUDGET_CONTEXT]}
"""

    prompt = f"""You are an independent reviewer auditing an AI agent's output.
Score the output 1-10 and list specific issues. Be harsh but fair.

FIRST: Determine the TASK TYPE from the agent's summary:
- CODING: writing/editing code, fixing bugs, configuration, deployment
- ADVISORY: answering questions, giving advice, strategy, negotiation, legal guidance, analysis, research, explanations
- CREATIVE: writing content (posts, copy, emails), creating videos, designing visuals, crafting social media, storytelling
- OPERATIONS: deploying, server config, Docker, CI/CD, infrastructure, DevOps, database migrations
- RESEARCH: exploring codebases, investigating bugs, finding information, reading docs, analyzing data

SCORING CRITERIA FOR CODING TASKS:
- 10/10: Code changes verified working (tests pass, builds succeed), every claim backed by evidence
- 8-9/10: Good work but has gaps (untested changes, unverified claims)
- 6-7/10: Notable problems (incomplete, missing verification)
- 1-5/10: Broken, wrong, or fabricated

SCORING CRITERIA FOR ADVISORY TASKS:
- 10/10: Accurate, complete, actionable advice that fully addresses the user's question. Covers all angles. No factual errors.
- 8-9/10: Good advice but misses an important angle or has minor gaps
- 6-7/10: Partially addresses the question, vague, or missing key considerations
- 1-5/10: Wrong, misleading, or unhelpful

SCORING CRITERIA FOR CREATIVE TASKS:
- 10/10: Compelling, authentic, well-crafted output that achieves its goal (engagement, clarity, persuasion). Matches the intended tone and audience.
- 8-9/10: Good creative output but could be more original, punchy, or polished
- 6-7/10: Generic, formulaic, or misses the audience/tone
- 1-5/10: Off-brand, tone-deaf, or low effort

SCORING CRITERIA FOR OPERATIONS TASKS:
- 10/10: Successfully completed with verification (service running, deploy confirmed, config tested). Idempotent, no side effects.
- 8-9/10: Completed but missing verification or has minor gaps in rollback plan
- 6-7/10: Partially done, untested, or risky approach
- 1-5/10: Broke something, wrong config, or dangerous without safeguards

SCORING CRITERIA FOR RESEARCH TASKS:
- 10/10: Thorough, accurate findings with clear conclusions. All relevant sources checked. Actionable summary.
- 8-9/10: Good research but missed an obvious source or left a question unanswered
- 6-7/10: Shallow, incomplete, or inconclusive
- 1-5/10: Wrong conclusions or missed critical information

FOR ADVISORY TASKS: Do NOT demand command output, code verification, or test results. Score based on the quality, accuracy, completeness, and actionability of the advice itself.
FOR CREATIVE TASKS: Do NOT demand code verification or tests. Score based on originality, voice, audience fit, and whether it achieves its creative goal.
FOR RESEARCH TASKS: Do NOT demand code changes. Score based on thoroughness, accuracy, and whether the findings are actionable.

IMPORTANT RULES:
- The git diff may be UNRELATED to the current response. Do NOT penalize for diff/response mismatch unless the agent explicitly claims specific code changes that aren't in the diff.
- Score the response on its OWN merits: accuracy, completeness, helpfulness, specificity.
- TOOL OUTPUT IS EVIDENCE: When the agent mentions tool results (command output, file reads, test results), treat them as verified evidence.
- SELF-SCORING IS EXPECTED: Don't penalize for self-assessments, verify if they're accurate.
{context_section}
WHAT THE AGENT DID (agent's own summary):
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
            temperature=0.0,
        ),
    )
    return response.text


def parse_score(result):
    """Extract numeric score from Gemini response. Returns None if unparseable."""
    for line in result.split("\n"):
        line = line.strip()
        if line.startswith("SCORE:"):
            try:
                score_str = line.split(":")[1].strip().split("/")[0].strip()
                return int(score_str)
            except (ValueError, IndexError):
                return None
    return None


def main():
    # Fail-open if no API key
    if not GEMINI_API_KEY:
        print("WARNING: No GEMINI_API_KEY or GOOGLE_API_KEY set. Cannot run audit.")
        sys.exit(0)

    # Read input JSON from stdin
    try:
        raw = sys.stdin.read()
        data = json.loads(raw)
    except (json.JSONDecodeError, Exception) as e:
        print(f"ERROR: Could not parse input JSON: {e}")
        sys.exit(1)

    assistant_text = data.get("assistant_text", "")
    diff_stat = data.get("diff_stat", "")
    diff_text = data.get("diff_text", "")
    context = data.get("context", "")

    # Handle empty diff gracefully
    if not assistant_text and not diff_stat and not diff_text:
        print("Nothing to audit: no summary and no diff provided.")
        sys.exit(0)

    # Call Gemini
    try:
        result = audit(assistant_text, diff_stat, diff_text, context)
    except Exception as e:
        print(f"ERROR: Gemini API call failed: {e}")
        sys.exit(0)  # Fail-open

    # Parse and display
    score = parse_score(result)
    if score is not None:
        print(f"\n{'=' * 40}")
        print(f"  BOUNCER AUDIT: {score}/10")
        print(f"{'=' * 40}\n")
    else:
        print("\n(Could not parse score from Gemini response)\n")

    print(result)
    sys.exit(0)


if __name__ == "__main__":
    main()
