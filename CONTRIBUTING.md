# Contributing

This is a development-stage, local-first agent harness. Contributions should
make project continuity, hardware compatibility, verification or recovery
more reproducible—not just add another model or a longer prompt.

## Before changing code

Start with [Getting started](GETTING-STARTED.md),
[the toolkit](TOOLKIT.md) and the [SSOT trust boundary](BLESSED-SSOT.md).
For a bug, open a GitHub issue describing the affected public version,
platform, minimum reproduction and actual versus expected outcome. For a
security vulnerability, use [private reporting](SECURITY.md), not an issue.

Keep changes focused. Each PR should identify a specific source defect,
the original behavior, the proposed behavior, tests and a rollback route.
Avoid copying an installed private Pi, Claude, Codex or model-runtime file
wholesale: its paths, credentials, permissive tool guards and versions may
not match the portable public contract.

## Validation

The GitHub release workflow exercises Python 3.11 on Linux and Python 3.13
on Windows. It runs the package lint policy and the offline acceptance suite.

```bash
python -m pip install ruff==0.16.10
python -m ruff check .
python scripts/verify_ssot_release.py
```

Run the focused tests for your changed component as well. Tests for
external model servers, GPUs, browsers and native Pi installations need
their exact runtime and source pins; a synthetic unit test does not
substitute for their separate acceptance.

A good PR includes an explicit **negative control**: not just what should
succeed, but what must remain blocked (for example stale source hashes,
wrong project, attempted task-authority escalation, changed output or
a second session writer).

## Scope and privacy

Do not include personal chat history, API keys, customer data, native
private agent sessions, live provider payloads, private rig manifests,
model weights or absolute machine paths. Redact before opening an issue.
A model response or a green build alone is not evidence that work is
externally accepted.

The default installer targets Linux x86_64 with glibc. Other platforms
currently have smaller direct-install routes; document platform-specific
limitations rather than implying universal support. New model and tool
integrations must preserve the host-controlled work contract and
source-bound audit trail.

Core code is [MIT licensed](LICENSE); imported dependencies retain their
own licenses.
