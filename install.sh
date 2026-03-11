#!/bin/bash
set -e

# Bouncer installer
# Usage: curl -sL github.com/buildingopen/bouncer/raw/main/install.sh | bash

GREEN='\033[0;32m'
DIM='\033[2m'
BOLD='\033[1m'
RESET='\033[0m'

echo ""
echo -e "${GREEN}${BOLD}bouncer${RESET} installer"
echo -e "${DIM}Gemini audits Claude Code.${RESET}"
echo ""

# Check Python
if ! command -v python3 &>/dev/null; then
    echo "Error: python3 not found. Install Python 3.8+ first."
    exit 1
fi

# Check pip
if ! python3 -m pip --version &>/dev/null; then
    echo "Error: pip not found. Install pip first."
    exit 1
fi

# Install dependency
echo -e "${DIM}Installing google-genai...${RESET}"
python3 -m pip install --quiet google-genai

# Create directories
mkdir -p ~/.claude/hooks
mkdir -p ~/.claude/skills/bouncer/scripts

# Download files
REPO="https://raw.githubusercontent.com/buildingopen/bouncer/main"
echo -e "${DIM}Downloading bouncer...${RESET}"

curl -sL "$REPO/gemini-audit.py"   -o ~/.claude/hooks/gemini-audit.py
curl -sL "$REPO/gemini-audit.sh"   -o ~/.claude/hooks/gemini-audit.sh
curl -sL "$REPO/skill/SKILL.md"    -o ~/.claude/skills/bouncer/SKILL.md
curl -sL "$REPO/skill/scripts/bouncer-check.py" -o ~/.claude/skills/bouncer/scripts/bouncer-check.py
curl -sL "$REPO/skill/scripts/bouncer-deep.py"  -o ~/.claude/skills/bouncer/scripts/bouncer-deep.py

chmod +x ~/.claude/hooks/gemini-audit.sh ~/.claude/hooks/gemini-audit.py
chmod +x ~/.claude/skills/bouncer/scripts/bouncer-check.py
chmod +x ~/.claude/skills/bouncer/scripts/bouncer-deep.py

# Register Stop hook in settings.json
SETTINGS="$HOME/.claude/settings.json"
if [ -f "$SETTINGS" ]; then
    # Check if hook already registered
    if grep -q "gemini-audit" "$SETTINGS" 2>/dev/null; then
        echo -e "${DIM}Hook already registered in settings.json${RESET}"
    else
        # Add hook to existing settings using Python for safe JSON manipulation
        python3 -c "
import json, sys

with open('$SETTINGS', 'r') as f:
    settings = json.load(f)

hook_entry = {
    'type': 'command',
    'command': '~/.claude/hooks/gemini-audit.sh',
    'timeout': 60
}

hooks = settings.setdefault('hooks', {})
stop = hooks.setdefault('Stop', [{'matcher': '', 'hooks': []}])

# Find the matcher='' entry or create one
target = None
for entry in stop:
    if entry.get('matcher', '') == '':
        target = entry
        break
if not target:
    target = {'matcher': '', 'hooks': []}
    stop.append(target)

target.setdefault('hooks', []).append(hook_entry)

with open('$SETTINGS', 'w') as f:
    json.dump(settings, f, indent=2)
"
        echo -e "${DIM}Hook registered in settings.json${RESET}"
    fi
else
    # Create settings.json from scratch
    python3 -c "
import json
settings = {
    'hooks': {
        'Stop': [{
            'matcher': '',
            'hooks': [{
                'type': 'command',
                'command': '~/.claude/hooks/gemini-audit.sh',
                'timeout': 60
            }]
        }]
    }
}
with open('$SETTINGS', 'w') as f:
    json.dump(settings, f, indent=2)
"
    echo -e "${DIM}Created settings.json with hook${RESET}"
fi

# Enable
touch ~/.claude/.gemini-audit-enabled

# Check API key
if [ -z "$GEMINI_API_KEY" ] && [ -z "$GOOGLE_API_KEY" ]; then
    echo ""
    echo -e "${GREEN}${BOLD}Installed!${RESET} One step left:"
    echo ""
    echo "  export GEMINI_API_KEY=\"your-key-here\""
    echo ""
    echo -e "${DIM}Add to your .bashrc/.zshrc. Get a free key at:${RESET}"
    echo "  https://aistudio.google.com/apikey"
else
    echo ""
    echo -e "${GREEN}${BOLD}Installed and ready.${RESET}"
fi

echo ""
echo -e "  Stop hook: ${GREEN}active${RESET} (every Claude response is audited)"
echo -e "  Skill:     ${GREEN}active${RESET} (type /bouncer for on-demand audit)"
echo ""
echo -e "${DIM}Disable: rm ~/.claude/.gemini-audit-enabled${RESET}"
echo ""
