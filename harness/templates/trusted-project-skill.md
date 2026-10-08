---
name: trusted-project
description: Explicitly activate the installed trusted project workflow from ordinary language.
---

# Trusted Project Activation

Use this skill only when the user explicitly asks for the trusted, receipt-gated, or
blessed-SSOT workflow. Do not intercept ordinary tasks by default.

1. Resolve the exact target root under the host's normal instruction precedence.
2. Preserve the user's exact request. Do not rewrite it before capture.
3. For a new request, run `trusted-project plan "REQUEST" --root TARGET`.
4. If the user explicitly requested execution, run
   `trusted-project execute "REQUEST_OR_PROJECT_ID" --root TARGET`.
5. Use `trusted-project status PROJECT_ID --root TARGET` for status questions and
   `trusted-project resume PROJECT_ID --root TARGET` when asked to continue.
6. Use the host's normal planning and research tools to draft the PRD manifest and a
   separate reinforcement report. Preserve all open material decisions.
   For a performance problem, first establish the symptom, comparable baseline,
   time spent in each relevant stage, and a check that distinguishes competing
   causes. Use existing authorized telemetry. Optimize only after evidence locates
   the constraint. Verify the result against the same workload and correctness
   checks. Keep unmeasured stages explicit; do not add a diagnostic framework to
   tasks without a performance symptom.
7. Run `trusted-project admit-prd PROJECT_ID --root TARGET --contract CONTRACT`.
   The drafter, critic, and independent reviewer must be distinct identities.
8. Compile the reviewed PRD only with
   `trusted-project compile-ssot PROJECT_ID --root TARGET --contract CONTRACT`.
   Preserve the all-unresolved seed. Treat verifier candidates as untrusted until the
   independent compile reviewer promotes their exact bytes and scopes.
9. Never bypass a hold returned by the command. Explain its exact
   `next_allowed_action`.
10. After compilation, call `trusted-project execute PROJECT_ID --root TARGET` only
    when the captured mode is `execute`. If a stage declares external effects, pass
    its fresh exact authorization as `--authorization STAGE=PATH`.
11. Do not claim testing or blessing merely because outputs exist. Only receipt-
    derived executable state is authoritative. `tested` is local; `blessed` requires
    the configured external authority.
