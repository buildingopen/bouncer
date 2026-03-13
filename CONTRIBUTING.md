# Contributing to Bouncer

Thanks for improving Bouncer.

## Before you open a PR

1. Open an issue if the change is substantial or changes the audit contract.
2. Keep changes focused. Small PRs review faster and are easier to verify.
3. Add or update tests for behavior changes.

## Local checks

```bash
python3 -m pytest test_gemini_audit.py test_bouncer_check.py test_bouncer_deep.py -v
```

If you touch the installer, also verify a clean-home install:

```bash
HOME="$(mktemp -d)" bash ./install.sh
```

## Areas that need extra care

- Transcript parsing in `gemini-audit.py`
- Deep audit tool safety in `bouncer-deep.py`
- Installer changes in `install.sh`
- README or docs changes that affect copy-paste commands

## PR expectations

- Describe what changed and why.
- Include verification steps and results.
- Call out breaking changes or behavior changes in the audit decision path.
