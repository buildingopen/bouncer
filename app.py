"""
Floom app entrypoint for bouncer.

Bouncer uses Gemini as an independent reviewer that scores another agent's
work 1-10 and lists issues. On Floom, we expose that as a stateless
`audit` action: you pass in the assistant text (and optionally a diff and
task context), and you get back a score, issues list, and PASS/FAIL verdict.

The full bouncer CLI also includes a Stop-hook runner, log rotation, and
deep-audit agent (tool-calling Gemini that reads files). None of that is
useful in a stateless action, so we inline just the scoring prompt from
`gemini-audit.py` and call Gemini directly.
"""

import os
import re

from floom import app, context

# Budgets mirror gemini-audit.py so long inputs do not blow the token limit.
BUDGET_ASSISTANT = 200_000
BUDGET_CONTEXT = 50_000
BUDGET_DIFF = 50_000

AUDIT_PROMPT_TEMPLATE = """You are an independent reviewer auditing an AI agent's output.
Score the output 1-10 and list specific issues. Be harsh but fair.

FIRST: Determine the TASK TYPE from the user's request:
- CODING: writing/editing code, fixing bugs, configuration, deployment
- ADVISORY: answering questions, giving advice, strategy, negotiation, legal guidance, analysis, research, explanations

SCORING CRITERIA FOR CODING TASKS:
- 10/10: Code changes verified working (tests pass, builds succeed), every claim backed by evidence
- 8-9/10: Good work but has gaps (untested changes, unverified claims)
- 6-7/10: Notable problems (incomplete, missing verification)
- 1-5/10: Broken, wrong, or fabricated

SCORING CRITERIA FOR ADVISORY TASKS:
- 10/10: Accurate, complete, actionable advice that fully addresses the user's question. Covers all angles the user asked about. No factual errors.
- 8-9/10: Good advice but misses an important angle or has minor gaps
- 6-7/10: Partially addresses the question, vague, or missing key considerations
- 1-5/10: Wrong, misleading, or unhelpful

FOR ADVISORY TASKS: Do NOT demand command output, code verification, or test results. Score based on the quality, accuracy, completeness, and actionability of the advice itself.

IMPORTANT RULES:
- The git diff may be UNRELATED to the current response. Do NOT penalize for diff/response mismatch unless the agent explicitly claims to have made specific code changes that aren't in the diff.
- Score the response on its OWN merits: accuracy, completeness, helpfulness, specificity.
- SELF-SCORING IS EXPECTED. YOUR job is to independently verify whether the self-score is accurate.
- TOOL OUTPUT IS EVIDENCE.

{context_section}
WHAT THE AGENT SAID:
{assistant_text}
{diff_section}
RESPOND IN EXACTLY THIS FORMAT (no markdown, no extra text):
SCORE: X/10
ISSUES:
- issue 1
- issue 2
- issue 3
VERDICT: PASS or FAIL
"""


def _build_prompt(assistant_text: str, diff_text: str, task_context: str) -> str:
    diff_section = (
        f"\nCODE CHANGES (diff):\n{diff_text[:BUDGET_DIFF]}\n"
        if diff_text
        else "\n(No code diff available. Score based on response quality.)\n"
    )
    context_section = (
        f"\nTASK CONTEXT (user request, project rules, workplan):\n{task_context[:BUDGET_CONTEXT]}\n"
        if task_context
        else ""
    )
    return AUDIT_PROMPT_TEMPLATE.format(
        context_section=context_section,
        assistant_text=assistant_text[:BUDGET_ASSISTANT],
        diff_section=diff_section,
    )


def _parse_response(text: str) -> dict:
    """Extract score, issues list, and verdict from Gemini's freeform response."""
    score_match = re.search(r"SCORE:\s*(\d+)\s*/\s*10", text, re.IGNORECASE)
    verdict_match = re.search(r"VERDICT:\s*(PASS|FAIL)", text, re.IGNORECASE)

    score = int(score_match.group(1)) if score_match else 0
    verdict = verdict_match.group(1).upper() if verdict_match else "FAIL"

    # Pull lines between ISSUES: and VERDICT:
    issues: list = []
    issues_block = re.search(
        r"ISSUES:\s*(.*?)\s*VERDICT:", text, re.IGNORECASE | re.DOTALL
    )
    if issues_block:
        for line in issues_block.group(1).splitlines():
            line = line.strip()
            if line.startswith(("-", "*", "•")):
                issues.append(line.lstrip("-*• ").strip())
            elif line:
                issues.append(line)

    return {
        "score": score,
        "verdict": verdict,
        "passed": verdict == "PASS" and score >= 10,
        "issues": issues,
        "raw": text,
    }


@app.action
def audit(
    assistant_text: str,
    diff_text: str = "",
    task_context: str = "",
    model: str = "gemini-2.5-flash",
) -> dict:
    """
    Score an AI agent's output using Gemini as an independent reviewer.

    Returns a dict with `score` (0-10), `verdict` (PASS/FAIL), `issues`
    (list of strings), `passed` (bool, True only when score == 10 and
    verdict == PASS), and the raw Gemini response.
    """
    if not assistant_text or not assistant_text.strip():
        return {
            "error": "assistant_text is required",
            "score": 0,
            "verdict": "FAIL",
            "passed": False,
            "issues": ["no assistant_text provided"],
        }

    api_key = context.get_secret("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")
    if not api_key:
        return {
            "error": "GEMINI_API_KEY secret is not set",
            "score": 0,
            "verdict": "FAIL",
            "passed": False,
            "issues": ["missing GEMINI_API_KEY"],
        }

    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        return {
            "error": f"google-genai not available: {exc}",
            "score": 0,
            "verdict": "FAIL",
            "passed": False,
            "issues": ["google-genai dependency missing"],
        }

    prompt = _build_prompt(assistant_text, diff_text, task_context)

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(max_output_tokens=1024, temperature=0.0),
    )

    return _parse_response(response.text or "")
