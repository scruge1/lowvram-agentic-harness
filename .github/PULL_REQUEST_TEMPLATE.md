## Problem and scope

Describe the reproducible problem, platform, exact public revision,
and the user-visible or security-relevant behavior being changed.

## Change and evidence

Explain the specific files changed, source/version pins, and what remains
unqualified. Link to a relevant issue or reproducible example.

## Verification

- [ ] Focused positive test passed, with command and observed result
- [ ] Negative control passed (wrong project, stale source, unauthorized effect, or relevant equivalent)
- [ ] `python -m ruff check .` passed
- [ ] `python scripts/verify_ssot_release.py` passed, or the limitation is documented
- [ ] No private sessions, credentials, host paths, customer records, model weights or generated run state were committed
- [ ] Existing installed Homes and GPU/model ownership are unchanged unless explicitly in scope

## Risks and rollback

State compatibility limits, supported platform(s), and how to revert
without rewriting a user's managed Home or accepted project state.
