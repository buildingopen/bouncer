#!/usr/bin/env python3
"""
Bouncer Deep Audit: Gemini independently verifies Claude's work.

Unlike the quick audit (bouncer-check.py) which scores based on what Claude
reports, this agent has full access to the codebase. It reads files, runs
tests, searches code, and verifies every claim independently.

Input JSON on stdin: {"assistant_text": "...", "diff_text": "...", "cwd": "...", "context": "..."}
Output: Human-readable audit report to stdout.
"""

import json
import os
import subprocess
import sys
import time

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
MAX_TURNS = 25
TIMEOUT_CMD = 30  # seconds per command
CWD = os.getcwd()


# -- Tools that Gemini can call --

def read_file(path: str) -> str:
    """Read a file's contents. Use for inspecting source code, configs, tests.

    Args:
        path: Absolute or relative file path to read.
    """
    try:
        full = os.path.join(CWD, path) if not os.path.isabs(path) else path
        with open(full) as f:
            content = f.read()
        if len(content) > 50_000:
            return content[:50_000] + f"\n\n... (truncated, {len(content)} chars total)"
        return content
    except Exception as e:
        return f"ERROR: {e}"


def run_command(cmd: str) -> str:
    """Run a shell command and return stdout+stderr. Use for running tests, builds, linting.

    Args:
        cmd: Shell command to execute.
    """
    # Safety: block destructive commands
    blocked = ["rm -rf", "rm -r /", "mkfs", "dd if=", "> /dev/", "chmod -R 777"]
    for b in blocked:
        if b in cmd:
            return f"BLOCKED: '{b}' is not allowed in audit commands."
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=TIMEOUT_CMD, cwd=CWD
        )
        output = ""
        if result.stdout:
            output += result.stdout
        if result.stderr:
            output += "\nSTDERR:\n" + result.stderr
        if result.returncode != 0:
            output += f"\nEXIT CODE: {result.returncode}"
        if len(output) > 30_000:
            output = output[:30_000] + "\n... (truncated)"
        return output or "(no output)"
    except subprocess.TimeoutExpired:
        return f"TIMEOUT: command exceeded {TIMEOUT_CMD}s limit"
    except Exception as e:
        return f"ERROR: {e}"


def search_code(pattern: str, glob: str = "") -> str:
    """Search for a regex pattern in the codebase using ripgrep.

    Args:
        pattern: Regex pattern to search for.
        glob: Optional file glob filter, e.g. "*.py" or "*.ts".
    """
    cmd = ["rg", "--no-heading", "-n", "--max-count", "50", pattern]
    if glob:
        cmd += ["--glob", glob]
    cmd.append(CWD)
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=15
        )
        output = result.stdout
        if len(output) > 20_000:
            output = output[:20_000] + "\n... (truncated)"
        return output or "(no matches)"
    except FileNotFoundError:
        # Fallback to grep if rg not available
        grep_cmd = ["grep", "-rn", pattern, CWD]
        if glob:
            grep_cmd += ["--include", glob]
        try:
            result = subprocess.run(
                grep_cmd, capture_output=True, text=True, timeout=15
            )
            output = result.stdout
            if result.stderr:
                output += ("\nSTDERR:\n" if output else "STDERR:\n") + result.stderr
            if result.returncode == 1 and not result.stderr:
                return "(no matches)"
            if result.returncode not in (0, 1):
                output += f"\nEXIT CODE: {result.returncode}"
            if len(output) > 20_000:
                output = output[:20_000] + "\n... (truncated)"
            return output or "(no matches)"
        except Exception as e:
            return f"ERROR: {e}"
    except Exception as e:
        return f"ERROR: {e}"


def list_files(path: str = ".", pattern: str = "") -> str:
    """List files in a directory, optionally filtered by glob pattern.

    Args:
        path: Directory path (relative to project root).
        pattern: Optional glob pattern like "*.py" or "**/*.test.ts".
    """
    full = os.path.join(CWD, path) if not os.path.isabs(path) else path
    if pattern:
        import glob as globmod
        matches = sorted(globmod.glob(os.path.join(full, pattern), recursive=True))
        return "\n".join(matches[:200]) or "(no matches)"
    else:
        try:
            entries = sorted(os.listdir(full))
            result = []
            for e in entries[:200]:
                fp = os.path.join(full, e)
                marker = "/" if os.path.isdir(fp) else ""
                result.append(f"{e}{marker}")
            return "\n".join(result) or "(empty directory)"
        except Exception as e:
            return f"ERROR: {e}"


def git_log(n: int = 10) -> str:
    """Show recent git commits.

    Args:
        n: Number of commits to show (default 10).
    """
    return run_command(f"git log --oneline -n {n}")


def git_diff() -> str:
    """Show current git diff (staged and unstaged)."""
    staged = run_command("git diff --cached --stat")
    unstaged = run_command("git diff --stat")
    full = run_command("git diff --cached")
    full2 = run_command("git diff")
    output = ""
    if staged.strip() and staged != "(no output)":
        output += f"STAGED:\n{staged}\n"
    if unstaged.strip() and unstaged != "(no output)":
        output += f"UNSTAGED:\n{unstaged}\n"
    if full.strip() and full != "(no output)":
        output += f"\nSTAGED DIFF:\n{full}\n"
    if full2.strip() and full2 != "(no output)":
        output += f"\nUNSTAGED DIFF:\n{full2}\n"
    return output or "(no changes)"


TOOLS = [read_file, run_command, search_code, list_files, git_log, git_diff]


def deep_audit(assistant_text, diff_text, context):
    """Run Gemini as an independent agent that verifies Claude's work."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=GEMINI_API_KEY)

    system_prompt = f"""You are an independent code auditor. Another AI agent (Claude) claims to have
completed some work. Your job is to INDEPENDENTLY VERIFY every claim.

You have tools to read files, run commands, search code, and inspect the git history.
Use them aggressively. DO NOT trust the agent's self-report. Verify everything yourself.

AUDIT PROCESS:
1. Read the agent's summary to understand what it claims to have done
2. Check the git diff to see what actually changed
3. Read the changed files to verify the code is correct
4. Run tests if they exist (look for test files, package.json scripts, pytest, etc.)
5. Check for common issues: security vulnerabilities, broken imports, missing error handling
6. Verify any specific claims ("tests pass", "builds succeed", "bug is fixed")
7. Check if CLAUDE.md rules were followed (if provided)

BE THOROUGH. Take your time. Call multiple tools. Read multiple files.
A surface-level review is worthless, you must actually verify.

PROJECT ROOT: {CWD}
{"PROJECT RULES (CLAUDE.md):" + chr(10) + context[:30000] if context else ""}

WHEN DONE, output your final report in EXACTLY this format:
SCORE: X/10
VERIFIED:
- [claim] -> [verified/unverified/false] [evidence]
ISSUES:
- [issue description]
VERDICT: PASS or FAIL
"""

    user_msg = f"""The AI agent claims:

{assistant_text[:100_000]}

{"GIT DIFF:" + chr(10) + diff_text[:50_000] if diff_text else "(no diff provided)"}

Now verify these claims independently. Read the actual files, run the tests, check the code.
Start by listing the project files and reading the diff."""

    contents = [types.Content(role="user", parts=[types.Part.from_text(text=user_msg)])]

    print(f"  Starting deep audit ({MAX_TURNS} turns max)...", flush=True)
    print(f"  Project: {CWD}", flush=True)
    print(flush=True)

    for turn in range(MAX_TURNS):
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    tools=TOOLS,
                    temperature=0.0,
                ),
            )
        except Exception as e:
            print(f"  ERROR on turn {turn + 1}: {e}")
            break

        candidate = response.candidates[0]
        model_content = candidate.content

        # Check for function calls
        has_calls = False
        function_responses = []

        for part in model_content.parts:
            if part.function_call:
                has_calls = True
                name = part.function_call.name
                args = dict(part.function_call.args) if part.function_call.args else {}

                # Execute
                func_map = {
                    "read_file": read_file,
                    "run_command": run_command,
                    "search_code": search_code,
                    "list_files": list_files,
                    "git_log": git_log,
                    "git_diff": git_diff,
                }

                arg_summary = ", ".join(f"{k}={repr(v)[:60]}" for k, v in args.items())
                print(f"  [{turn + 1}] {name}({arg_summary})", flush=True)

                func = func_map.get(name)
                if func:
                    result = func(**args)
                else:
                    result = f"Unknown function: {name}"

                function_responses.append(
                    types.Part.from_function_response(
                        name=name,
                        response={"content": result}
                    )
                )

        if has_calls:
            # Send function results back
            contents.append(model_content)
            contents.append(
                types.Content(role="user", parts=function_responses)
            )
        else:
            # Final text response
            text = ""
            for part in model_content.parts:
                if part.text:
                    text += part.text
            return text

    return "AUDIT INCOMPLETE: reached maximum turns without final verdict."


def parse_score(result):
    for line in result.split("\n"):
        line = line.strip()
        if line.startswith("SCORE:"):
            try:
                return int(line.split(":")[1].strip().split("/")[0].strip())
            except (ValueError, IndexError):
                return None
    return None


def main():
    global CWD

    if not GEMINI_API_KEY:
        print("WARNING: No GEMINI_API_KEY or GOOGLE_API_KEY set. Cannot run audit.")
        sys.exit(0)

    try:
        raw = sys.stdin.read()
        data = json.loads(raw)
    except (json.JSONDecodeError, Exception) as e:
        print(f"ERROR: Could not parse input JSON: {e}")
        sys.exit(1)

    assistant_text = data.get("assistant_text", "")
    diff_text = data.get("diff_text", "")
    context = data.get("context", "")
    CWD = data.get("cwd", os.getcwd())

    if not assistant_text and not diff_text:
        print("Nothing to audit: no summary and no diff provided.")
        sys.exit(0)

    start = time.time()

    try:
        result = deep_audit(assistant_text, diff_text, context)
    except Exception as e:
        print(f"ERROR: Deep audit failed: {e}")
        sys.exit(0)

    elapsed = time.time() - start

    score = parse_score(result)
    if score is not None:
        reactions = {
            10: ("VIP ENTRY", "velvet rope parts"),
            9:  ("GUEST LIST", "almost flawless"),
            8:  ("STAMP APPROVED", "solid work, minor nits"),
            7:  ("SIDE ENTRANCE", "decent but gaps showing"),
            6:  ("PAT DOWN", "needs another pass"),
            5:  ("HELD AT DOOR", "half-baked"),
            4:  ("TURNED AWAY", "come back dressed better"),
            3:  ("BANNED TONIGHT", "serious problems"),
            2:  ("LIFETIME BAN", "what happened here"),
            1:  ("CALLING POLICE", "everything is wrong"),
        }
        label, quip = reactions.get(score, ("???", ""))
        bar_filled = score * 3
        bar_empty = 30 - bar_filled
        bar = f"[{'#' * bar_filled}{'.' * bar_empty}]"

        print(f"\n  {'~' * 42}")
        print(f"    BOUNCER DEEP AUDIT  {bar}  {score}/10")
        print(f"    {label}: {quip}")
        print(f"    Verified in {elapsed:.1f}s")
        print(f"  {'~' * 42}\n")
    else:
        print(f"\n(Could not parse score, audit took {elapsed:.1f}s)\n")

    print(result)
    sys.exit(0)


if __name__ == "__main__":
    main()
