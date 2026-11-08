# Security policy

## Development-stage software

This project coordinates local agent tools, filesystem actions, memory
and command-line workers. It is not a verified production sandbox or a
guarantee against unsafe model-generated instructions.

Use a restricted OS account and appropriate sandbox/host permissions for
any agent that can execute commands. Review network access, process
ownership, credentials and write permissions for your deployment.
Optional research tools may contact external services.

## Report a vulnerability privately

Use GitHub's **[Report a vulnerability](https://github.com/scruge1/lowvram-agentic-harness/security/advisories/new)** feature rather than posting exploit details,
tokens, prompt injections or private logs in public issues.

A useful report includes the affected public commit or tag, supported
platform, minimal redacted reproduction, expected authority boundary,
observed behavior and impact. Avoid attaching private session bodies,
model credentials or customer material.

There is no guaranteed response SLA or fixed security support window.
Security fixes require separate source review and regression checks;
a passing test suite does not establish that every deployment is safe.

## Important boundaries

The SSOT controller's local acceptance is capped at `tested` and
requires independent checks. A model, a retrieved memory, a source
summary or a native session file cannot grant its own work permission.
Any apparent bypass of task scope, project identity, source-hash
validation, safe session reuse, model-service ownership or protected
file operations should be reported privately.

For non-sensitive bugs and usability problems, use
[GitHub Issues](https://github.com/scruge1/lowvram-agentic-harness/issues).
