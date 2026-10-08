# Repository Instructions

- Keep local inference, agent harnesses, and SSOT control separate. Each must work without the others.
- Treat model and agent output as untrusted input. Only host-side checks can raise authority.
- The starter SSOT is a portable reference implementation, not the private source system.
- Preserve the `scaffolded -> compiled -> configured -> enforced -> tested` state order. The local controller cannot issue `blessed`; that requires a protected external trust provider.
- Keep PRD onboarding fail-closed: `init` may pin source bytes but cannot infer intent. `doctor` must block unresolved contracts before `next`, `prepare`, or `run` issues work.
- Keep the host-run adapter argument-array based (`shell=False`). Workers may write declared project outputs and model telemetry, but not `.ssot` control state.
- Use Python 3.9+ standard-library code for the core. Run all offline self-tests before completion.
- Do not add credentials, model files, generated `.ssot` run state, or private source material.
- For performance symptoms, apply `DIAGNOSTICS.md` before proposing an optimization. Separate observed delay from its suspected cause. Use existing authorized telemetry first. Record unknowns and the next discriminating check.
- Record reusable upgrades and their exact parent commit in `UPGRADES.md`. Public guidance must distinguish source changes, package tests, and target adoption.
