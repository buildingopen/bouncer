#!/bin/bash
# Gemini independent audit - Stop hook wrapper
# Opt-in: touch ~/.claude/.gemini-audit-enabled
# Opt-out: rm ~/.claude/.gemini-audit-enabled

# Quick check before spawning Python
[ -f "$HOME/.claude/.gemini-audit-enabled" ] || exit 0

# Pass stdin through to Python
exec python3 "$HOME/.claude/hooks/gemini-audit.py"
