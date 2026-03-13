# Security

## Data flow

Bouncer can send the following data to the Google Gemini API during an audit:

- Claude's assistant response
- Recent user messages from the transcript
- Tool calls and tool output from the transcript
- Git diff
- Project `CLAUDE.md`
- Active `WORKPLAN-*.md`

Do not use Bouncer on projects where sending that data to Gemini would violate
your security, privacy, or contractual requirements.

## Reporting

If you find a security issue in Bouncer itself, open a private security advisory
through GitHub if available, or email the maintainer listed on the Building Open
GitHub profile.

## Scope

Security reports are most useful when they include:

- The affected file or code path
- Reproduction steps
- Expected vs actual behavior
- Whether the issue affects the hook, the on-demand skill, the installer, or docs
